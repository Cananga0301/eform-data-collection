"""
Data access layer — thin wrapper around SQLAlchemy sessions.
All business logic lives in the service layer.
"""
from contextlib import contextmanager

from src.config.postgresql.postgresql_client import PostgreSQLClient
from src.models.eform_models import (
    Assignment, Branch, BranchMapping, CollectedRecord, Segment,
    SyncCursor, SyncLog, UnmappedRecord, VerificationLog,
)


class EformRepository:
    def __init__(self, postgresql_client: PostgreSQLClient):
        self.pg = postgresql_client

    @contextmanager
    def session_scope(self):
        session = self.pg.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── Segments ──────────────────────────────────────────────────────────────

    def get_segment_by_norm_key(self, session, tinh_thanh_norm, xa_phuong_norm, ten_duong_norm, doan_key_norm):
        return session.query(Segment).filter_by(
            tinh_thanh_norm=tinh_thanh_norm,
            xa_phuong_norm=xa_phuong_norm,
            ten_duong_norm=ten_duong_norm,
            doan_key_norm=doan_key_norm,
        ).first()

    def get_segment_by_id(self, session, segment_id: int):
        return session.query(Segment).filter_by(id=segment_id).first()

    def get_all_active_segments(self, session):
        return session.query(Segment).filter_by(is_active=True).all()

    def deactivate_segments_not_in(self, session, active_ids: list[int]):
        """Set is_active = False for all segments whose id is not in active_ids."""
        session.query(Segment).filter(
            Segment.id.notin_(active_ids),
            Segment.is_active == True,
        ).update({'is_active': False}, synchronize_session='fetch')

    # ── Branches ──────────────────────────────────────────────────────────────

    def get_branch_by_key(self, session, key_type: str, key_value_norm: str):
        mapping = session.query(BranchMapping).filter_by(
            key_type=key_type,
            key_value=key_value_norm,
        ).first()
        return mapping.branch if mapping else None

    def get_all_branches(self, session):
        return session.query(Branch).order_by(Branch.name).all()

    # ── Assignments ───────────────────────────────────────────────────────────

    def get_assignment_by_segment(self, session, segment_id: int):
        return session.query(Assignment).filter_by(segment_id=segment_id).first()

    # ── Collected records ─────────────────────────────────────────────────────

    def get_collected_record_by_source_id(self, session, source_record_id: str):
        return session.query(CollectedRecord).filter_by(
            source_record_id=source_record_id
        ).first()

    def count_active_collected_by_segment_vitri(self, session, segment_id: int, vi_tri: int) -> int:
        return session.query(CollectedRecord).filter_by(
            segment_id=segment_id,
            vi_tri=vi_tri,
            is_active=True,
        ).count()

    # ── Unmapped records ──────────────────────────────────────────────────────

    def get_unresolved_unmapped(self, session):
        return session.query(UnmappedRecord).filter_by(resolved=False).all()

    # ── Sync infrastructure ───────────────────────────────────────────────────

    def get_sync_cursor(self, session):
        return session.query(SyncCursor).first()

    def get_or_create_sync_cursor(self, session):
        cursor = self.get_sync_cursor(session)
        if not cursor:
            cursor = SyncCursor()
            session.add(cursor)
            session.flush()
        return cursor

    # ── Verification ──────────────────────────────────────────────────────────

    def get_verification_logs_by_segment(self, session, segment_id: int):
        return session.query(VerificationLog).filter_by(
            segment_id=segment_id
        ).order_by(VerificationLog.verified_at.desc()).all()
