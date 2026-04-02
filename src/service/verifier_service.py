"""
T5 — Data verification.

Auto-checks:
1. Quantity: active collected records per position >= so_can_vtX.
2. No duplicate source_record_ids for the same segment + vi_tri.
3. No wrong position (record tagged vi_tri=X but so_can_vtX is null for segment).
4. Required fields: not configured → treated as passing.

Auto-check scope: only segments in 'Đủ vị trí' or 'Hoàn thành'.
Segments in 'Dữ liệu sai hoặc lỗi' can only be cleared by manual inspector review.

If all checks pass:  trang_thai = 'Hoàn thành'
If any check fails:  trang_thai = 'Dữ liệu sai hoặc lỗi'
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func

from src.models.eform_models import CollectedRecord, Segment, VerificationLog
from src.repository.eform_repository import EformRepository

logger = logging.getLogger(__name__)

_REVIEWABLE_STATES = ('Đủ vị trí', 'Hoàn thành', 'Dữ liệu sai hoặc lỗi')


class VerifierService:
    def __init__(self, repository: EformRepository):
        self.repo = repository

    def run_auto_checks(
        self,
        nguoi_kiem_tra: str = 'system',
        segment_ids: set[int] | None = None,
    ) -> dict:
        """
        Run auto-checks on eligible segments.

        Eligible: is_active=True and trang_thai in ('Đủ vị trí', 'Hoàn thành').
        Segments in 'Dữ liệu sai hoặc lỗi' are intentionally excluded — only
        manual inspector review can clear that state.

        If segment_ids is provided, only those segments are checked (used for
        scoped post-sync verification to avoid noisy full rescans).
        """
        passed = failed = skipped = 0

        with self.repo.session_scope() as session:
            q = session.query(Segment).filter(
                Segment.is_active == True,
                Segment.trang_thai.in_(['Đủ vị trí', 'Hoàn thành']),
            )
            if segment_ids is not None:
                q = q.filter(Segment.id.in_(segment_ids))
            segs = q.all()

            for seg in segs:
                errors = self._check_segment(session, seg)
                ket_qua = 'PASS' if not errors else ('FAIL: ' + '; '.join(errors))

                log = VerificationLog(
                    segment_id=seg.id,
                    nguoi_kiem_tra=nguoi_kiem_tra,
                    ket_qua=ket_qua,
                    loai_kiem_tra='auto',
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

    def save_manual_finding(
        self,
        segment_id: int,
        nguoi_kiem_tra: str,
        finding_text: str,
        outcome: str,
    ) -> None:
        """
        Record a manual inspector review and update the segment's trang_thai.

        outcome: 'pass' → 'Hoàn thành' | 'fail' → 'Dữ liệu sai hoặc lỗi'

        Raises ValueError for blank inspector, invalid outcome, empty notes on fail,
        or segment in a non-reviewable state.
        """
        if not nguoi_kiem_tra or not nguoi_kiem_tra.strip():
            raise ValueError("Inspector name must not be empty.")
        if outcome not in ('pass', 'fail'):
            raise ValueError(f"outcome must be 'pass' or 'fail', got {outcome!r}.")
        if outcome == 'fail' and not finding_text.strip():
            raise ValueError("Notes are required when flagging an error.")

        new_status = 'Hoàn thành' if outcome == 'pass' else 'Dữ liệu sai hoặc lỗi'

        with self.repo.session_scope() as session:
            seg = self.repo.get_segment_by_id(session, segment_id)
            if seg is None:
                raise ValueError(f"Segment {segment_id} not found.")
            if seg.trang_thai not in _REVIEWABLE_STATES:
                raise ValueError(
                    f"Segment {segment_id} is in state '{seg.trang_thai}' and cannot be manually reviewed."
                )
            seg.trang_thai = new_status
            session.add(VerificationLog(
                segment_id=segment_id,
                nguoi_kiem_tra=nguoi_kiem_tra.strip(),
                ket_qua=f"MANUAL-{outcome.upper()}: {finding_text.strip() or 'no notes'}",
                loai_kiem_tra='manual',
                verified_at=datetime.now(timezone.utc),
            ))
        logger.info(
            f"save_manual_finding: segment_id={segment_id}, outcome={outcome}, "
            f"inspector={nguoi_kiem_tra!r}, new_status={new_status!r}"
        )

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
