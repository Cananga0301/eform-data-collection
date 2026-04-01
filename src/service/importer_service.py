"""
T1 - Import 3 Excel route files and classify segments.

Performance design:
- 2 bulk SELECTs per file (load all province segments + all branch mappings).
- Zero DB queries per row - all lookups are O(1) in-memory dict.
- Single session.flush() at the end of each file.
- 1 bulk UPDATE for deactivation.
- Total: ~3 DB round-trips per file regardless of row count.

Key rules:
- so_can_vtX = 3 if vtX is not null, else null.
- doan_key = doan if not null, else ten_duong.
- On re-import: nhom_manual=True rows keep their nhom; assignments untouched;
  segments missing from the new file are deactivated; reappearing ones reactivated.
- branch_id resolved via BranchMapping: try xa_phuong_norm, fall back to tinh_thanh_norm.
- Display fields refreshed on every re-import.
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from src.models.eform_models import BranchMapping, Segment
from src.repository.eform_repository import EformRepository
from src.service.classifier_service import ClassifierService
from src.utils.text import normalize

logger = logging.getLogger(__name__)

RECORDS_PER_POSITION = 3

_EXPECTED_COLUMNS = {'stt', 'tinh_thanh', 'xa_phuong', 'ten_duong', 'doan', 'vt1'}
_PRICE_COLUMNS = ('vt1', 'vt2', 'vt3', 'vt4')
_SPACE_RE = re.compile(r'[\s\u00A0\u202F]+')
_CURRENCY_SUFFIX_RE = re.compile(r'(?:vn(?:d|\u0111)|\u0111)\s*$', re.IGNORECASE)
_DOT_GROUP_RE = re.compile(r'^\d{1,3}(?:\.\d{3})+$')
_COMMA_GROUP_RE = re.compile(r'^\d{1,3}(?:,\d{3})+$')
_DOT_GROUP_ZERO_DECIMAL_RE = re.compile(r'^(?P<int>\d{1,3}(?:\.\d{3})+),(?P<frac>0+)$')
_COMMA_GROUP_ZERO_DECIMAL_RE = re.compile(r'^(?P<int>\d{1,3}(?:,\d{3})+)\.(?P<frac>0+)$')
_PLAIN_ZERO_DECIMAL_RE = re.compile(r'^(?P<int>\d+)(?:[.,](?P<frac>0+))$')
_EMPTY_PRICE_MARKERS = {'-', '--', '---', 'n/a', 'na'}


@dataclass(frozen=True)
class ImportCellParseError:
    row_number: int
    column_name: str
    raw_value: str


class ImportValidationError(ValueError):
    def __init__(self, filename: str, errors: list[ImportCellParseError]):
        self.filename = filename
        self.errors = errors
        super().__init__(self._build_message())

    def _build_message(self, max_examples: int = 5) -> str:
        examples = [
            f"row {err.row_number} {err.column_name}={err.raw_value!r}"
            for err in self.errors[:max_examples]
        ]
        suffix = ''
        if len(self.errors) > max_examples:
            suffix = f"; and {len(self.errors) - max_examples} more"
        return (
            f"Could not parse {len(self.errors)} vt cell(s) in {self.filename}. "
            f"Examples: {'; '.join(examples)}{suffix}"
        )


class ImporterService:
    def __init__(self, repository: EformRepository, classifier: ClassifierService):
        self.repo = repository
        self.classifier = classifier

    def import_excel(self, file_path: str, source_name: Optional[str] = None) -> dict:
        """
        Import a single Excel file. Returns a summary dict with counts.
        Safe to call multiple times - fully idempotent.
        """
        df = pd.read_excel(file_path, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]

        missing = _EXPECTED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns in {file_path}: {missing}")

        df = df.where(pd.notna(df), None)
        self._validate_and_parse_prices(
            df,
            os.path.basename(source_name or file_path),
        )

        upserted = 0
        deactivated = 0

        with self.repo.session_scope() as session:
            first_tinh = _str(df['tinh_thanh'].iloc[0]) if not df.empty else None
            tinh_norm = normalize(first_tinh) if first_tinh else ''

            segment_map = self._load_segment_map(session, tinh_norm)
            branch_map = self._load_branch_map(session)

            active_norm_keys = set()

            for row in df.itertuples(index=False):
                seg, _ = self._upsert_segment_fast(session, row, segment_map, branch_map)
                norm_key = (
                    seg.tinh_thanh_norm,
                    seg.xa_phuong_norm,
                    seg.ten_duong_norm,
                    seg.doan_key_norm,
                )
                active_norm_keys.add(norm_key)
                upserted += 1

            session.flush()

            inactive_ids = [
                segment.id
                for key, segment in segment_map.items()
                if key not in active_norm_keys and segment.is_active and segment.id is not None
            ]
            if inactive_ids:
                session.query(Segment).filter(Segment.id.in_(inactive_ids)).update(
                    {'is_active': False},
                    synchronize_session='fetch',
                )
                deactivated = len(inactive_ids)

        logger.info(
            "import_excel: %s -> upserted=%s, deactivated=%s",
            file_path,
            upserted,
            deactivated,
        )
        return {'upserted': upserted, 'deactivated': deactivated}

    def apply_single_mapping(
        self, key_type: str, key_value_norm: str, branch_id: int
    ) -> int:
        """
        Apply one just-saved BranchMapping to matching active segments.
        Only touches rows whose branch_id is NULL or differs from the target —
        so the returned count is genuinely "rows that changed".
        xa_phuong type: update segments where xa_phuong_norm matches.
        tinh_thanh type: same, but skip segments whose xa_phuong_norm already
        has its own ward-level mapping (xa_phuong wins over tinh_thanh).
        """
        from sqlalchemy import or_
        with self.repo.session_scope() as session:
            q = session.query(Segment).filter(
                Segment.is_active == True,
                or_(Segment.branch_id.is_(None), Segment.branch_id != branch_id),
            )
            if key_type == 'xa_phuong':
                q = q.filter(Segment.xa_phuong_norm == key_value_norm)
            else:  # tinh_thanh
                xa_covered = [
                    m.key_value
                    for m in session.query(BranchMapping)
                    .filter_by(key_type='xa_phuong').all()
                ]
                q = q.filter(Segment.tinh_thanh_norm == key_value_norm)
                if xa_covered:
                    q = q.filter(~Segment.xa_phuong_norm.in_(xa_covered))
            return q.update({'branch_id': branch_id}, synchronize_session=False)

    def reapply_all_branch_mappings(self) -> dict:
        """
        Full recompute of segment.branch_id from current BranchMappings.
        Step 1: clear all active segment branch assignments.
        Step 2: apply tinh_thanh (province fallback).
        Step 3: apply xa_phuong (ward wins, overwrites province).
        Returns {'assigned': N, 'unassigned': M}.
        """
        from sqlalchemy import func
        with self.repo.session_scope() as session:
            # Step 1: clear all branch assignments for active segments
            session.query(Segment).filter(
                Segment.is_active == True,
            ).update({'branch_id': None}, synchronize_session=False)

            branch_map = self._load_branch_map(session)
            tt_mappings = {kv: bid for (kt, kv), bid in branch_map.items() if kt == 'tinh_thanh'}
            xa_mappings = {kv: bid for (kt, kv), bid in branch_map.items() if kt == 'xa_phuong'}

            # Step 2: apply province fallback first
            for tt_norm, bid in tt_mappings.items():
                session.query(Segment).filter(
                    Segment.tinh_thanh_norm == tt_norm,
                    Segment.is_active == True,
                ).update({'branch_id': bid}, synchronize_session=False)

            # Step 3: apply ward override (xa_phuong wins over tinh_thanh)
            for xa_norm, bid in xa_mappings.items():
                session.query(Segment).filter(
                    Segment.xa_phuong_norm == xa_norm,
                    Segment.is_active == True,
                ).update({'branch_id': bid}, synchronize_session=False)

            # Step 4: count final state within the same transaction
            total = session.query(func.count(Segment.id)).filter(
                Segment.is_active == True,
            ).scalar() or 0
            assigned = session.query(func.count(Segment.id)).filter(
                Segment.is_active == True,
                Segment.branch_id.isnot(None),
            ).scalar() or 0
            return {'assigned': assigned, 'unassigned': total - assigned}

    def _load_segment_map(self, session, tinh_thanh_norm: str) -> dict:
        """
        Load all segments for one province (active + inactive) into a dict.
        1 query total - used for O(1) lookup during the row loop.
        """
        segments = session.query(Segment).filter_by(tinh_thanh_norm=tinh_thanh_norm).all()
        return {
            (segment.tinh_thanh_norm, segment.xa_phuong_norm, segment.ten_duong_norm, segment.doan_key_norm): segment
            for segment in segments
        }

    def _load_branch_map(self, session) -> dict:
        """
        Load all branch mappings into a dict.
        1 query total - used for O(1) branch lookup during the row loop.
        Returns {(key_type, key_value_norm): branch_id}
        """
        rows = session.query(BranchMapping).all()
        return {(row.key_type, row.key_value): row.branch_id for row in rows}

    def _validate_and_parse_prices(self, df: pd.DataFrame, filename: str) -> None:
        parsed_columns: dict[str, list[Optional[int]]] = {}
        errors: list[ImportCellParseError] = []

        for column_name in _PRICE_COLUMNS:
            if column_name not in df.columns:
                continue

            parsed_values: list[Optional[int]] = []
            for row_number, raw_value in enumerate(df[column_name].tolist(), start=2):
                try:
                    parsed_values.append(_parse_vnd_price(raw_value))
                except ValueError:
                    raw_text = '' if raw_value is None else str(raw_value).strip()
                    errors.append(ImportCellParseError(row_number, column_name, raw_text))
                    parsed_values.append(None)

            parsed_columns[column_name] = parsed_values

        if errors:
            raise ImportValidationError(filename, errors)

        for column_name, parsed_values in parsed_columns.items():
            df[column_name] = pd.Series(parsed_values, index=df.index, dtype='object')

    def _upsert_segment_fast(self, session, row, segment_map: dict, branch_map: dict):
        """
        Upsert one segment using only in-memory dicts. Zero DB queries.
        row is an itertuples() namedtuple - use getattr() for safe access.
        Returns (segment, is_new).
        """
        tinh_thanh = _str(getattr(row, 'tinh_thanh', None))
        xa_phuong = _str(getattr(row, 'xa_phuong', None))
        ten_duong = _str(getattr(row, 'ten_duong', None))
        doan = _str(getattr(row, 'doan', None))
        doan_key = doan if doan else ten_duong

        tinh_norm = normalize(tinh_thanh)
        xa_norm = normalize(xa_phuong)
        ten_norm = normalize(ten_duong)
        doan_key_norm = normalize(doan_key)

        vt1 = _optional_int(getattr(row, 'vt1', None))
        vt2 = _optional_int(getattr(row, 'vt2', None))
        vt3 = _optional_int(getattr(row, 'vt3', None))
        vt4 = _optional_int(getattr(row, 'vt4', None))

        norm_key = (tinh_norm, xa_norm, ten_norm, doan_key_norm)
        segment = segment_map.get(norm_key)
        is_new = segment is None

        branch_id = (
            branch_map.get(('xa_phuong', xa_norm)) or
            branch_map.get(('tinh_thanh', tinh_norm))
        )

        if is_new:
            segment = Segment(
                tinh_thanh=tinh_thanh,
                tinh_thanh_norm=tinh_norm,
                xa_phuong=xa_phuong,
                xa_phuong_norm=xa_norm,
                ten_duong=ten_duong,
                ten_duong_norm=ten_norm,
                doan=doan,
                doan_key=doan_key,
                doan_key_norm=doan_key_norm,
                vt1=vt1,
                vt2=vt2,
                vt3=vt3,
                vt4=vt4,
                so_can_vt1=RECORDS_PER_POSITION if vt1 is not None else None,
                so_can_vt2=RECORDS_PER_POSITION if vt2 is not None else None,
                so_can_vt3=RECORDS_PER_POSITION if vt3 is not None else None,
                so_can_vt4=RECORDS_PER_POSITION if vt4 is not None else None,
                nhom_manual=False,
                is_active=True,
                branch_id=branch_id,
            )
            session.add(segment)
            segment_map[norm_key] = segment
        else:
            segment.is_active = True
            segment.tinh_thanh = tinh_thanh
            segment.xa_phuong = xa_phuong
            segment.ten_duong = ten_duong
            segment.doan = doan
            segment.doan_key = doan_key
            segment.vt1 = vt1
            segment.vt2 = vt2
            segment.vt3 = vt3
            segment.vt4 = vt4
            segment.so_can_vt1 = RECORDS_PER_POSITION if vt1 is not None else None
            segment.so_can_vt2 = RECORDS_PER_POSITION if vt2 is not None else None
            segment.so_can_vt3 = RECORDS_PER_POSITION if vt3 is not None else None
            segment.so_can_vt4 = RECORDS_PER_POSITION if vt4 is not None else None
            segment.branch_id = branch_id
            segment.updated_at = datetime.utcnow()

        if not segment.nhom_manual:
            segment.nhom = self.classifier.classify(xa_norm, vt1)

        return segment, is_new


def _str(val) -> Optional[str]:
    if val is None:
        return None
    value = str(val).strip()
    return value if value else None


def _optional_int(val) -> Optional[int]:
    if val is None or pd.isna(val):
        return None
    return int(val)


def _parse_vnd_price(val) -> Optional[int]:
    if val is None:
        return None

    raw = str(val)
    if not raw.strip():
        return None

    text = _SPACE_RE.sub(' ', raw).strip()
    if text.lower() in _EMPTY_PRICE_MARKERS:
        return None
    text = _CURRENCY_SUFFIX_RE.sub('', text).strip()
    if not text:
        raise ValueError('Invalid empty price after normalization')

    compact = _SPACE_RE.sub('', text)
    if not re.fullmatch(r'[\d.,]+', compact):
        raise ValueError(f'Unsupported characters in price: {raw!r}')

    if compact.isdigit():
        return int(compact)

    match = _PLAIN_ZERO_DECIMAL_RE.fullmatch(compact)
    if match:
        return int(match.group('int'))

    match = _DOT_GROUP_ZERO_DECIMAL_RE.fullmatch(compact)
    if match:
        return int(match.group('int').replace('.', ''))

    match = _COMMA_GROUP_ZERO_DECIMAL_RE.fullmatch(compact)
    if match:
        return int(match.group('int').replace(',', ''))

    if _DOT_GROUP_RE.fullmatch(compact):
        return int(compact.replace('.', ''))

    if _COMMA_GROUP_RE.fullmatch(compact):
        return int(compact.replace(',', ''))

    raise ValueError(f'Could not parse VND price: {raw!r}')
