"""
T5 — Data verification.

Auto-checks:
1. Quantity: active collected records per position >= so_can_vtX.
2. No duplicate source_record_ids for the same segment + vi_tri.
3. No wrong position (record tagged vi_tri=X but so_can_vtX is null for segment).
4. Required fields: not configured → treated as passing (auto-advances to Hoàn thành).

If all checks pass:  trang_thai = 'Hoàn thành'
If any check fails:  trang_thai = 'Dữ liệu sai hoặc lỗi'
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func

from src.models.eform_models import CollectedRecord, Segment, VerificationLog
from src.repository.eform_repository import EformRepository

logger = logging.getLogger(__name__)


class VerifierService:
    def __init__(self, repository: EformRepository):
        self.repo = repository

    def run_auto_checks(self, nguoi_kiem_tra: str = 'system') -> dict:
        """
        Run auto-checks on all active segments that are at 'Đủ vị trí' or later.
        Returns a summary dict.
        """
        passed = failed = skipped = 0

        with self.repo.session_scope() as session:
            segs = session.query(Segment).filter(
                Segment.is_active == True,
                Segment.trang_thai.in_(['Đủ vị trí', 'Hoàn thành', 'Dữ liệu sai hoặc lỗi']),
            ).all()

            for seg in segs:
                errors = self._check_segment(session, seg)
                ket_qua = 'PASS' if not errors else ('FAIL: ' + '; '.join(errors))

                log = VerificationLog(
                    segment_id=seg.id,
                    nguoi_kiem_tra=nguoi_kiem_tra,
                    ket_qua=ket_qua,
                    verified_at=datetime.now(timezone.utc),
                )
                session.add(log)

                if not errors:
                    seg.trang_thai = 'Hoàn thành'
                    passed += 1
                else:
                    seg.trang_thai = 'Dữ liệu sai hoặc lỗi'
                    failed += 1

        logger.info(f"run_auto_checks: passed={passed}, failed={failed}, skipped={skipped}")
        return {'passed': passed, 'failed': failed, 'skipped': skipped}

    # ── Private ───────────────────────────────────────────────────────────────

    def _check_segment(self, session, seg: Segment) -> list[str]:
        errors = []

        positions = [
            (1, seg.so_can_vt1),
            (2, seg.so_can_vt2),
            (3, seg.so_can_vt3),
            (4, seg.so_can_vt4),
        ]
        active_positions = {vt for vt, req in positions if req is not None}

        for vt, req in positions:
            if req is None:
                continue
            count = self.repo.count_active_collected_by_segment_vitri(session, seg.id, vt)
            if count < req:
                errors.append(f"vt{vt}: need {req}, have {count}")

        # Check for duplicate source_record_ids per segment + vi_tri
        dup_rows = (
            session.query(CollectedRecord.vi_tri)
            .filter_by(segment_id=seg.id, is_active=True)
            .group_by(CollectedRecord.source_record_id, CollectedRecord.vi_tri)
            .having(func.count(CollectedRecord.id) > 1)
            .all()
        )
        if dup_rows:
            errors.append(f"duplicate source_record_ids at positions: {[r.vi_tri for r in dup_rows]}")

        # Check for wrong position (record at a vi_tri that doesn't exist for this segment)
        wrong_pos = (
            session.query(CollectedRecord.vi_tri)
            .filter(
                CollectedRecord.segment_id == seg.id,
                CollectedRecord.is_active == True,
                CollectedRecord.vi_tri.notin_(list(active_positions)),
            )
            .distinct()
            .all()
        )
        if wrong_pos:
            errors.append(f"records at invalid positions: {[r.vi_tri for r in wrong_pos]}")

        # Required-fields check: not configured → treated as passing.
        # Stub: always passes until business defines required fields.

        return errors
