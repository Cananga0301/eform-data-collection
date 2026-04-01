"""
T2 — Assignment file export and re-import.

Export: one row per segment with segment_id, route info, positions, branch,
        and empty phu_trach / deadline columns for the field team to fill in.
Re-import: match by segment_id (primary); normalized text fallback.
           Assignments survive master Excel re-imports (only changed fields updated).
"""
import logging
from datetime import datetime
from io import BytesIO
from typing import Optional

import openpyxl
import pandas as pd

from src.models.eform_models import Assignment, Branch, Segment
from src.repository.eform_repository import EformRepository
from src.utils.text import normalize

logger = logging.getLogger(__name__)

EXPORT_COLUMNS = [
    'segment_id', 'tinh_thanh', 'xa_phuong', 'ten_duong', 'doan',
    'nhom', 'vt1', 'vt2', 'vt3', 'vt4',
    'so_can_vt1', 'so_can_vt2', 'so_can_vt3', 'so_can_vt4',
    'branch', 'phu_trach', 'deadline',
]


class AssignerService:
    def __init__(self, repository: EformRepository):
        self.repo = repository

    def export_assignment_excel(
        self,
        tinh_thanh: Optional[str] = None,
        xa_phuong: Optional[str] = None,
    ) -> bytes:
        """
        Export an assignment Excel file filtered by area.
        Returns raw bytes of the .xlsx file.
        """
        with self.repo.session_scope() as session:
            q = session.query(Segment).filter_by(is_active=True)
            if tinh_thanh:
                q = q.filter_by(tinh_thanh_norm=normalize(tinh_thanh))
            if xa_phuong:
                q = q.filter_by(xa_phuong_norm=normalize(xa_phuong))
            segments = q.order_by(Segment.tinh_thanh, Segment.xa_phuong, Segment.ten_duong).all()

            rows = []
            for seg in segments:
                assignment = self.repo.get_assignment_by_segment(session, seg.id)
                branch_name = ''
                if assignment and assignment.branch:
                    branch_name = assignment.branch.name
                elif seg.branch:
                    branch_name = seg.branch.name

                rows.append({
                    'segment_id': seg.id,
                    'tinh_thanh': seg.tinh_thanh,
                    'xa_phuong': seg.xa_phuong,
                    'ten_duong': seg.ten_duong,
                    'doan': seg.doan or '',
                    'nhom': seg.nhom or '',
                    'vt1': seg.vt1, 'vt2': seg.vt2, 'vt3': seg.vt3, 'vt4': seg.vt4,
                    'so_can_vt1': seg.so_can_vt1, 'so_can_vt2': seg.so_can_vt2,
                    'so_can_vt3': seg.so_can_vt3, 'so_can_vt4': seg.so_can_vt4,
                    'branch': branch_name,
                    'phu_trach': assignment.phu_trach if assignment else '',
                    'deadline': assignment.deadline.isoformat() if assignment and assignment.deadline else '',
                })

        df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Assignments')
        return buf.getvalue()

    def import_assignment_excel(self, file_bytes: bytes) -> dict:
        """
        Re-import a filled assignment Excel file.
        Matches by segment_id; falls back to normalized text key.
        Updates only phu_trach, deadline, branch_id — preserves everything else.
        """
        df = pd.read_excel(BytesIO(file_bytes), dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.where(pd.notna(df), None)

        updated = 0
        skipped = 0

        with self.repo.session_scope() as session:
            for _, row in df.iterrows():
                seg = self._find_segment(session, row)
                if seg is None:
                    logger.warning(f"No segment found for row: {dict(row)}")
                    skipped += 1
                    continue

                assignment = self.repo.get_assignment_by_segment(session, seg.id)
                if assignment is None:
                    assignment = Assignment(segment_id=seg.id)
                    session.add(assignment)

                if row.get('phu_trach'):
                    assignment.phu_trach = str(row['phu_trach']).strip()
                if row.get('deadline'):
                    try:
                        assignment.deadline = datetime.strptime(str(row['deadline']).strip(), '%Y-%m-%d').date()
                    except ValueError:
                        pass
                if row.get('branch'):
                    branch_name = str(row['branch']).strip()
                    branch = self._get_or_create_branch(session, branch_name)
                    if branch is not None:
                        assignment.branch_id = branch.id

                assignment.imported_at = datetime.utcnow()
                updated += 1

        logger.info(f"import_assignment_excel: updated={updated}, skipped={skipped}")
        return {'updated': updated, 'skipped': skipped}

    # ── Private ───────────────────────────────────────────────────────────────

    def _find_segment(self, session, row):
        # Primary: match by segment_id
        if row.get('segment_id'):
            try:
                seg_id = int(str(row['segment_id']).strip())
                seg = self.repo.get_segment_by_id(session, seg_id)
                if seg:
                    return seg
            except ValueError:
                pass

        # Fallback: normalized text key
        tinh_thanh = row.get('tinh_thanh') or ''
        xa_phuong = row.get('xa_phuong') or ''
        ten_duong = row.get('ten_duong') or ''
        doan = row.get('doan') or ''
        doan_key = doan if doan.strip() else ten_duong
        return self.repo.get_segment_by_norm_key(
            session,
            normalize(str(tinh_thanh)),
            normalize(str(xa_phuong)),
            normalize(str(ten_duong)),
            normalize(str(doan_key)),
        )

    def _get_or_create_branch(self, session, branch_name: str) -> Optional[Branch]:
        branch_name = str(branch_name).strip()
        if not branch_name:
            return None

        branch = session.query(Branch).filter_by(name=branch_name).first()
        if branch is not None:
            return branch

        branch = Branch(name=branch_name)
        session.add(branch)
        session.flush()
        logger.info("Auto-created branch from assignment import: %s", branch_name)
        return branch
