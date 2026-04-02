"""
T3 — Incremental sync from the collection app API.

Run via sync.py (standalone script) — NOT called from Flask/Gunicorn.

Key invariants:
- first_seen_at is set once on INSERT, never changed (used for velocity/alerts).
- last_synced_at is updated on every re-sync.
- source_record_id is the dedup key (UNIQUE constraint).
- Soft-deleted records in source → is_active = False locally.
- Cursor (last_synced_at, last_record_id) is persisted in sync_cursor table.
"""
import logging
from datetime import datetime, timezone

from src.clients.collection_client import AbstractCollectionClient
from src.models.eform_models import CollectedRecord, Segment, SyncLog, UnmappedRecord
from src.repository.eform_repository import EformRepository
from src.utils.text import normalize

logger = logging.getLogger(__name__)

PAGE_SIZE = 200


class SyncerService:
    def __init__(self, repository: EformRepository, client: AbstractCollectionClient):
        self.repo = repository
        self.client = client

    def run(self) -> set[int]:
        """Run an incremental sync. Returns the set of segment IDs whose status was recalculated."""
        affected_ids: set[int] = set()

        with self.repo.session_scope() as session:
            cursor = self.repo.get_or_create_sync_cursor(session)
            since = cursor.last_synced_at or datetime(2000, 1, 1, tzinfo=timezone.utc)

            sync_log = SyncLog(started_at=datetime.now(timezone.utc))
            session.add(sync_log)
            session.flush()

            total_received = total_mapped = total_unmapped = 0
            page = 1
            new_max_ts = since
            last_record_id = cursor.last_record_id

            while True:
                result = self.client.fetch_records(
                    since=since,
                    page=page,
                    page_size=PAGE_SIZE,
                    last_record_id=last_record_id if page == 1 else None,
                )
                records = result.get('records', [])
                if not records:
                    break

                for raw in records:
                    total_received += 1
                    mapped = self._process_record(session, raw, sync_log.id, affected_ids)
                    if mapped:
                        total_mapped += 1
                    else:
                        total_unmapped += 1

                    # Track cursor advancement
                    rec_ts_str = raw.get('updated_at') or raw.get('created_at')
                    if rec_ts_str:
                        try:
                            rec_ts = datetime.fromisoformat(rec_ts_str.replace('Z', '+00:00'))
                            if rec_ts > new_max_ts:
                                new_max_ts = rec_ts
                                last_record_id = raw.get('id')
                        except ValueError:
                            pass

                if not result.get('has_next'):
                    break
                page += 1

            # Update sync log
            sync_log.finished_at = datetime.now(timezone.utc)
            sync_log.total_received = total_received
            sync_log.total_mapped = total_mapped
            sync_log.total_unmapped = total_unmapped

            # Advance cursor
            if new_max_ts > since:
                cursor.last_synced_at = new_max_ts
                cursor.last_record_id = last_record_id
                cursor.updated_at = datetime.now(timezone.utc)

            logger.info(
                f"Sync complete: received={total_received} mapped={total_mapped} "
                f"unmapped={total_unmapped} affected_segments={len(affected_ids)}"
            )

        return affected_ids

    def replay_unmapped(self, session, unmapped_id: int, chosen_segment_id: int) -> int | None:
        """
        Resolve an unmapped record by assigning it to the chosen segment.
        Idempotent: if source_record_id is already in collected_records, UPDATE that row.
        Returns the segment ID whose status was recalculated, or None if segment not found.
        """
        from src.models.eform_models import UnmappedRecord
        unmapped = session.query(UnmappedRecord).filter_by(id=unmapped_id).first()
        if not unmapped:
            raise ValueError(f"UnmappedRecord {unmapped_id} not found")

        existing_cr = self.repo.get_collected_record_by_source_id(session, unmapped.source_record_id)
        now = datetime.now(timezone.utc)

        if existing_cr:
            existing_cr.segment_id = chosen_segment_id
            existing_cr.last_synced_at = now
        else:
            raw = unmapped.raw_data or {}
            cr = CollectedRecord(
                source_record_id=unmapped.source_record_id,
                segment_id=chosen_segment_id,
                vi_tri=raw.get('vi_tri'),
                raw_data=raw,
                is_active=True,
                first_seen_at=now,
                last_synced_at=now,
                sync_log_id=unmapped.sync_log_id,
            )
            session.add(cr)

        unmapped.resolved = True
        session.flush()

        segment = self.repo.get_segment_by_id(session, chosen_segment_id)
        if segment:
            self._recalculate_status(session, segment)
            return chosen_segment_id
        return None

    # ── Private ───────────────────────────────────────────────────────────────

    def _process_record(self, session, raw: dict, sync_log_id: int, affected_ids: set) -> bool:
        """Returns True if the record was mapped to a segment. Adds touched segment IDs to affected_ids."""
        source_id = raw.get('id')
        now = datetime.now(timezone.utc)

        # Soft delete
        if raw.get('is_deleted'):
            cr = self.repo.get_collected_record_by_source_id(session, source_id)
            if cr:
                cr.is_active = False
                cr.last_synced_at = now
                if cr.segment_id:
                    affected_ids.add(cr.segment_id)
                    self._recalculate_status(session, self.repo.get_segment_by_id(session, cr.segment_id))
            return bool(cr and cr.segment_id)

        segment = self._find_segment(session, raw)

        existing_cr = self.repo.get_collected_record_by_source_id(session, source_id)
        if existing_cr:
            old_segment_id = existing_cr.segment_id
            existing_cr.last_synced_at = now
            existing_cr.raw_data = raw
            existing_cr.vi_tri = raw.get('vi_tri')
            existing_cr.is_active = True

            if segment:
                existing_cr.segment_id = segment.id
                affected_ids.add(segment.id)
                self._recalculate_status(session, segment)
            else:
                existing_cr.segment_id = None  # clear stale mapping
                already_unmapped = session.query(UnmappedRecord).filter_by(
                    source_record_id=source_id, resolved=False
                ).first()
                if not already_unmapped:
                    session.add(UnmappedRecord(
                        source_record_id=source_id,
                        raw_data=raw,
                        reason='segment_not_found_on_update',
                        resolved=False,
                        sync_log_id=sync_log_id,
                    ))

            # Recalculate old segment if this record was removed from it
            if old_segment_id and old_segment_id != (segment.id if segment else None):
                old_seg = self.repo.get_segment_by_id(session, old_segment_id)
                if old_seg:
                    affected_ids.add(old_segment_id)
                    self._recalculate_status(session, old_seg)

            return segment is not None
        else:
            cr = CollectedRecord(
                source_record_id=source_id,
                segment_id=segment.id if segment else None,
                vi_tri=raw.get('vi_tri'),
                raw_data=raw,
                is_active=True,
                first_seen_at=now,
                last_synced_at=now,
                sync_log_id=sync_log_id,
            )
            session.add(cr)
            session.flush()

            if segment is None:
                unmapped = UnmappedRecord(
                    source_record_id=source_id,
                    raw_data=raw,
                    reason='segment_not_found',
                    resolved=False,
                    sync_log_id=sync_log_id,
                )
                session.add(unmapped)
                return False

            affected_ids.add(segment.id)
            self._recalculate_status(session, segment)
            return True

    def _passes_auto_checks(self, session, segment: Segment, active_positions: list) -> bool:
        """Inline T5 quick-checks. Quantity already confirmed by caller."""
        from sqlalchemy import func
        from src.models.eform_models import CollectedRecord as CR

        active_vtrs = {vt for vt, _ in active_positions}

        # No duplicate source_record_ids per segment + vi_tri
        dup = (
            session.query(CR.vi_tri)
            .filter_by(segment_id=segment.id, is_active=True)
            .group_by(CR.source_record_id, CR.vi_tri)
            .having(func.count(CR.id) > 1)
            .first()
        )
        if dup:
            return False

        # No records at positions that don't exist for this segment
        wrong = (
            session.query(CR.vi_tri)
            .filter(
                CR.segment_id == segment.id,
                CR.is_active == True,
                CR.vi_tri.notin_(list(active_vtrs)),
            )
            .first()
        )
        if wrong:
            return False

        # Required fields: not configured → auto-pass
        return True

    def _find_segment(self, session, raw: dict):
        doan = raw.get('doan') or ''
        doan_key = doan if doan.strip() else (raw.get('ten_duong') or '')
        return self.repo.get_segment_by_norm_key(
            session,
            normalize(raw.get('tinh_thanh') or ''),
            normalize(raw.get('xa_phuong') or ''),
            normalize(raw.get('ten_duong') or ''),
            normalize(doan_key),
        )

    def _recalculate_status(self, session, segment: Segment):
        if segment is None:
            return

        def count(vi_tri):
            return self.repo.count_active_collected_by_segment_vitri(session, segment.id, vi_tri)

        positions = [
            (1, segment.so_can_vt1),
            (2, segment.so_can_vt2),
            (3, segment.so_can_vt3),
            (4, segment.so_can_vt4),
        ]
        active_positions = [(vt, req) for vt, req in positions if req is not None]

        if not active_positions:
            return

        counts = {vt: count(vt) for vt, _ in active_positions}

        if segment.trang_thai == 'Dữ liệu sai hoặc lỗi':
            return  # error status — only T5 / manual can clear it

        if all(c == 0 for c in counts.values()):
            segment.trang_thai = 'Chưa bắt đầu'
        elif all(counts[vt] >= req for vt, req in active_positions):
            if self._passes_auto_checks(session, segment, active_positions):
                segment.trang_thai = 'Hoàn thành'
            else:
                segment.trang_thai = 'Đủ vị trí'  # manual fix needed via Page 9
        else:
            segment.trang_thai = 'Đang thu thập'
