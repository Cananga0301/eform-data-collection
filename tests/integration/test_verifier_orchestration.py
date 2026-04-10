"""
Integration tests for the sync → auto-verify orchestration.

Covers:
1. SyncerService.run() returns the correct affected segment IDs.
2. run_auto_checks(segment_ids=...) only logs for in-scope, eligible segments.
   - Segments not in segment_ids → no log
   - Segments in 'Dữ liệu sai hoặc lỗi' → skipped even when in segment_ids
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.clients.collection_client import AbstractCollectionClient
from src.models.eform_models import CollectedRecord, Segment, UnmappedRecord, VerificationLog
from src.repository.eform_repository import EformRepository
from src.service.syncer_service import SyncerService
from src.service.verifier_service import VerifierService


# ── Test helpers ──────────────────────────────────────────────────────────────

class DummyPostgreSQLClient:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_session(self):
        return self._session_factory()


class ListCollectionClient(AbstractCollectionClient):
    """Serves a fixed list of records — used for deterministic sync tests."""

    def __init__(self, records: list[dict]):
        self._records = records

    def fetch_records(self, since, page, page_size, last_record_id=None):
        if page == 1:
            return {'records': self._records, 'has_next': False}
        return {'records': [], 'has_next': False}


def _build_services(db_engine):
    session_factory = sessionmaker(bind=db_engine)
    repo = EformRepository(DummyPostgreSQLClient(session_factory))
    syncer = SyncerService(repo, ListCollectionClient([]))  # default: empty client
    verifier = VerifierService(repo)
    return repo, syncer, verifier


def _create_segment(db_engine, **kwargs) -> int:
    """Insert a Segment row directly and return its id."""
    defaults = dict(
        tinh_thanh='Ho Chi Minh',
        xa_phuong='Quan 1',
        ten_duong='Duong A',
        doan='Doan 1',
        doan_key='Doan 1',
        tinh_thanh_norm='ho chi minh',
        xa_phuong_norm='quan 1',
        ten_duong_norm='duong a',
        doan_key_norm='doan 1',
        so_can_vt1=3,
        trang_thai='Đủ vị trí',
        is_active=True,
    )
    defaults.update(kwargs)
    Session = sessionmaker(bind=db_engine)
    s = Session()
    try:
        seg = Segment(**defaults)
        s.add(seg)
        s.commit()
        return seg.id
    finally:
        s.close()


# ── Test 1: sync returns correct affected segment IDs ─────────────────────────

def test_sync_run_returns_affected_segment_ids(db_engine):
    repo, _, verifier = _build_services(db_engine)

    # Create a segment whose normalized keys match the record below
    seg_id = _create_segment(db_engine, trang_thai='Chưa bắt đầu')

    record = {
        'id': 'TEST-SYNC-001',
        'tinh_thanh': 'Ho Chi Minh',
        'xa_phuong': 'Quan 1',
        'ten_duong': 'Duong A',
        'doan': 'Doan 1',
        'vi_tri': 1,
        'updated_at': '2024-01-01T00:00:00Z',
        'is_deleted': False,
    }

    Session = sessionmaker(bind=db_engine)
    client = ListCollectionClient([record])
    syncer = SyncerService(repo, client)

    affected_ids = syncer.run()

    assert seg_id in affected_ids, (
        f"Expected segment {seg_id} in affected_ids, got {affected_ids}"
    )

    # Confirm the record was actually stored
    s = Session()
    try:
        assert s.query(CollectedRecord).filter_by(source_record_id='TEST-SYNC-001').count() == 1
    finally:
        s.close()


def test_sync_resolves_stale_unmapped_rows_when_same_source_id_later_maps(db_engine):
    repo, _, _ = _build_services(db_engine)

    seg_id = _create_segment(db_engine, trang_thai='Chưa bắt đầu')
    Session = sessionmaker(bind=db_engine)

    bad_record = {
        'id': 'TEST-REMATCH-001',
        'tinh_thanh': 'Ho Chi Minh',
        'xa_phuong': 'Wrong Ward',
        'ten_duong': 'Duong A',
        'doan': 'Doan 1',
        'vi_tri': 1,
        'updated_at': '2024-01-01T00:00:00Z',
        'is_deleted': False,
    }
    good_record = {
        'id': 'TEST-REMATCH-001',
        'tinh_thanh': 'Ho Chi Minh',
        'xa_phuong': 'Quan 1',
        'ten_duong': 'Duong A',
        'doan': 'Doan 1',
        'vi_tri': 1,
        'updated_at': '2024-01-02T00:00:00Z',
        'is_deleted': False,
    }

    SyncerService(repo, ListCollectionClient([bad_record])).run()
    affected_ids = SyncerService(repo, ListCollectionClient([good_record])).run()

    assert seg_id in affected_ids

    s = Session()
    try:
        cr = s.query(CollectedRecord).filter_by(source_record_id='TEST-REMATCH-001').one()
        assert cr.segment_id == seg_id

        unresolved = s.query(UnmappedRecord).filter_by(
            source_record_id='TEST-REMATCH-001',
            resolved=False,
        ).count()
        resolved = s.query(UnmappedRecord).filter_by(
            source_record_id='TEST-REMATCH-001',
            resolved=True,
        ).count()
        seg = s.query(Segment).filter_by(id=seg_id).one()

        assert unresolved == 0
        assert resolved == 1
        assert seg.trang_thai == 'Đang thu thập'
    finally:
        s.close()


def test_sync_still_unmapped_rerun_does_not_resolve_or_duplicate_rows(db_engine):
    repo, _, _ = _build_services(db_engine)
    Session = sessionmaker(bind=db_engine)

    bad_record_v1 = {
        'id': 'TEST-STILL-BAD-001',
        'tinh_thanh': 'Ho Chi Minh',
        'xa_phuong': 'Wrong Ward',
        'ten_duong': 'Duong A',
        'doan': 'Doan 1',
        'vi_tri': 1,
        'updated_at': '2024-01-01T00:00:00Z',
        'is_deleted': False,
    }
    bad_record_v2 = {
        'id': 'TEST-STILL-BAD-001',
        'tinh_thanh': 'Ho Chi Minh',
        'xa_phuong': 'Wronger Ward',
        'ten_duong': 'Duong A',
        'doan': 'Doan 1',
        'vi_tri': 1,
        'updated_at': '2024-01-02T00:00:00Z',
        'is_deleted': False,
    }

    SyncerService(repo, ListCollectionClient([bad_record_v1])).run()
    affected_ids = SyncerService(repo, ListCollectionClient([bad_record_v2])).run()

    assert affected_ids == set()

    s = Session()
    try:
        unresolved = s.query(UnmappedRecord).filter_by(
            source_record_id='TEST-STILL-BAD-001',
            resolved=False,
        ).count()
        resolved = s.query(UnmappedRecord).filter_by(
            source_record_id='TEST-STILL-BAD-001',
            resolved=True,
        ).count()
        cr = s.query(CollectedRecord).filter_by(source_record_id='TEST-STILL-BAD-001').one()

        assert unresolved == 1
        assert resolved == 0
        assert cr.segment_id is None
    finally:
        s.close()


def test_replay_unmapped_resolves_all_rows_for_same_source_id(db_engine):
    repo, syncer, _ = _build_services(db_engine)
    seg_id = _create_segment(db_engine, trang_thai='Chưa bắt đầu')
    Session = sessionmaker(bind=db_engine)

    s = Session()
    try:
        row1 = UnmappedRecord(
            source_record_id='TEST-REPLAY-001',
            raw_data={'vi_tri': 1, 'foo': 'bar'},
            reason='segment_not_found',
            resolved=False,
        )
        row2 = UnmappedRecord(
            source_record_id='TEST-REPLAY-001',
            raw_data={'vi_tri': 1, 'foo': 'baz'},
            reason='segment_not_found_on_update',
            resolved=False,
        )
        s.add_all([row1, row2])
        s.commit()
        chosen_unmapped_id = row1.id
    finally:
        s.close()

    with repo.session_scope() as session:
        affected_id = syncer.replay_unmapped(session, chosen_unmapped_id, seg_id)

    assert affected_id == seg_id

    s = Session()
    try:
        unresolved = s.query(UnmappedRecord).filter_by(
            source_record_id='TEST-REPLAY-001',
            resolved=False,
        ).count()
        resolved = s.query(UnmappedRecord).filter_by(
            source_record_id='TEST-REPLAY-001',
            resolved=True,
        ).count()
        cr = s.query(CollectedRecord).filter_by(source_record_id='TEST-REPLAY-001').one()
        seg = s.query(Segment).filter_by(id=seg_id).one()

        assert unresolved == 0
        assert resolved == 2
        assert cr.segment_id == seg_id
        assert seg.trang_thai == 'Đang thu thập'
    finally:
        s.close()


# ── Test 4: scope boundary — only segment_ids get checked, error state skipped ─

def test_auto_checks_scope_boundary(db_engine):
    """
    Given 3 segments:
      seg1: 'Đủ vị trí'  → in segment_ids  → gets checked → log created
      seg2: 'Đủ vị trí'  → NOT in segment_ids → no log
      error_seg: 'Dữ liệu sai hoặc lỗi' → in segment_ids → skipped by status filter → no log
    """
    repo, _, verifier = _build_services(db_engine)

    seg1_id = _create_segment(db_engine, trang_thai='Đủ vị trí',
                               ten_duong='Duong A', doan='Doan 1',
                               ten_duong_norm='duong a', doan_key='Doan 1',
                               doan_key_norm='doan 1')
    seg2_id = _create_segment(db_engine, trang_thai='Đủ vị trí',
                               ten_duong='Duong B', doan='Doan 2',
                               ten_duong_norm='duong b', doan_key='Doan 2',
                               doan_key_norm='doan 2')
    error_seg_id = _create_segment(db_engine, trang_thai='Dữ liệu sai hoặc lỗi',
                                    ten_duong='Duong C', doan='Doan 3',
                                    ten_duong_norm='duong c', doan_key='Doan 3',
                                    doan_key_norm='doan 3')

    # Run auto-checks scoped to seg1 and error_seg only (seg2 excluded)
    # seg1 will FAIL (no records, so_can_vt1=3 but count=0)
    verifier.run_auto_checks(
        nguoi_kiem_tra='system',
        segment_ids={seg1_id, error_seg_id},
    )

    Session = sessionmaker(bind=db_engine)
    s = Session()
    try:
        logs = s.query(VerificationLog).all()
        # Only seg1 should have a log
        assert len(logs) == 1, f"Expected 1 log row, got {len(logs)}: {[(l.segment_id, l.ket_qua) for l in logs]}"
        assert logs[0].segment_id == seg1_id
        assert logs[0].loai_kiem_tra == 'auto'
        # seg1 had 0 records with so_can_vt1=3 → FAIL
        assert logs[0].ket_qua.startswith('FAIL:')
    finally:
        s.close()
