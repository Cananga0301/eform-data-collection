"""
T1 — Import 3 Excel route files (HCM, Hà Nội, Đồng Nai) and classify segments.

Key rules:
- All text fields are normalized before upsert; originals kept for display.
- so_can_vtX = 3 if vtX is not null, else null (same rule for all provinces).
- doan_key = doan if not null, else ten_duong (original casing).
- On re-import: nhom_manual=True rows keep their nhom; assignments are untouched;
  segments missing from the new file are deactivated; reappearing ones reactivated.
- branch_id resolved via BranchMapping: try xa_phuong_norm, fall back to tinh_thanh_norm.
"""
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.models.eform_models import Segment
from src.repository.eform_repository import EformRepository
from src.service.classifier_service import ClassifierService
from src.utils.text import normalize

logger = logging.getLogger(__name__)

RECORDS_PER_POSITION = 3

_EXPECTED_COLUMNS = {'stt', 'tinh_thanh', 'xa_phuong', 'ten_duong', 'doan', 'vt1'}


class ImporterService:
    def __init__(self, repository: EformRepository, classifier: ClassifierService):
        self.repo = repository
        self.classifier = classifier

    def import_excel(self, file_path: str) -> dict:
        """
        Import a single Excel file. Returns a summary dict with counts.
        Can be called multiple times (once per province file).
        """
        df = pd.read_excel(file_path, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]

        missing = _EXPECTED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns in {file_path}: {missing}")

        # Normalize NaN → None
        df = df.where(pd.notna(df), None)

        upserted = 0
        deactivated = 0
        active_ids: list[int] = []

        with self.repo.session_scope() as session:
            for _, row in df.iterrows():
                seg = self._upsert_segment(session, row)
                active_ids.append(seg.id)
                upserted += 1

            # Deactivate segments from this province that are no longer in the file.
            # We scope deactivation to the province so re-imports of one province
            # don't affect segments from other provinces.
            tinh_thanh_norm = normalize(str(df['tinh_thanh'].iloc[0])) if not df.empty else None
            if tinh_thanh_norm:
                affected = session.query(Segment).filter(
                    Segment.tinh_thanh_norm == tinh_thanh_norm,
                    Segment.is_active == True,
                    Segment.id.notin_(active_ids),
                ).update({'is_active': False}, synchronize_session='fetch')
                deactivated = affected

        logger.info(f"import_excel: {file_path} → upserted={upserted}, deactivated={deactivated}")
        return {'upserted': upserted, 'deactivated': deactivated}

    # ── Private ───────────────────────────────────────────────────────────────

    def _upsert_segment(self, session, row) -> Segment:
        tinh_thanh = _str(row.get('tinh_thanh'))
        xa_phuong = _str(row.get('xa_phuong'))
        ten_duong = _str(row.get('ten_duong'))
        doan = _str(row.get('doan'))

        doan_key = doan if doan else ten_duong
        tinh_thanh_norm = normalize(tinh_thanh)
        xa_phuong_norm = normalize(xa_phuong)
        ten_duong_norm = normalize(ten_duong)
        doan_key_norm = normalize(doan_key)

        vt1 = _int(row.get('vt1'))
        vt2 = _int(row.get('vt2'))
        vt3 = _int(row.get('vt3'))
        vt4 = _int(row.get('vt4'))

        seg = self.repo.get_segment_by_norm_key(
            session, tinh_thanh_norm, xa_phuong_norm, ten_duong_norm, doan_key_norm
        )

        if seg is None:
            seg = Segment(
                tinh_thanh=tinh_thanh,
                xa_phuong=xa_phuong,
                ten_duong=ten_duong,
                doan=doan,
                doan_key=doan_key,
                tinh_thanh_norm=tinh_thanh_norm,
                xa_phuong_norm=xa_phuong_norm,
                ten_duong_norm=ten_duong_norm,
                doan_key_norm=doan_key_norm,
                vt1=vt1, vt2=vt2, vt3=vt3, vt4=vt4,
                so_can_vt1=RECORDS_PER_POSITION if vt1 is not None else None,
                so_can_vt2=RECORDS_PER_POSITION if vt2 is not None else None,
                so_can_vt3=RECORDS_PER_POSITION if vt3 is not None else None,
                so_can_vt4=RECORDS_PER_POSITION if vt4 is not None else None,
                nhom_manual=False,
                is_active=True,
            )
            session.add(seg)
            session.flush()  # get seg.id
        else:
            # Reactivate if it was previously deactivated.
            seg.is_active = True
            # Update price and position data from new file.
            seg.vt1 = vt1
            seg.vt2 = vt2
            seg.vt3 = vt3
            seg.vt4 = vt4
            seg.so_can_vt1 = RECORDS_PER_POSITION if vt1 is not None else None
            seg.so_can_vt2 = RECORDS_PER_POSITION if vt2 is not None else None
            seg.so_can_vt3 = RECORDS_PER_POSITION if vt3 is not None else None
            seg.so_can_vt4 = RECORDS_PER_POSITION if vt4 is not None else None
            seg.updated_at = datetime.utcnow()

        # Classify — skip if nhom_manual is set.
        if not seg.nhom_manual:
            seg.nhom = self.classifier.classify(xa_phuong_norm, vt1)

        # Branch lookup: try xa_phuong_norm, fall back to tinh_thanh_norm.
        branch = self.repo.get_branch_by_key(session, 'xa_phuong', xa_phuong_norm)
        if branch is None:
            branch = self.repo.get_branch_by_key(session, 'tinh_thanh', tinh_thanh_norm)
        if branch is not None:
            seg.branch_id = branch.id

        return seg


def _str(val) -> Optional[str]:
    if val is None:
        return None
    v = str(val).strip()
    return v if v else None


def _int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None
