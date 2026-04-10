"""Unit tests for VerifierService."""
from contextlib import contextmanager
from unittest.mock import MagicMock, call

import pytest

from src.models.eform_models import Segment, VerificationLog
from src.service.verifier_service import VerifierService


def _make_repo():
    """Return (repo, session) with a fake session_scope context manager."""
    repo = MagicMock()
    session = MagicMock()

    @contextmanager
    def fake_scope():
        yield session

    repo.session_scope = fake_scope
    return repo, session


def _chainable(result):
    """Return a mock query that chains through filter/filter_by/group_by/having/distinct and returns result from .all()."""
    q = MagicMock()
    q.filter.return_value = q
    q.filter_by.return_value = q
    q.group_by.return_value = q
    q.having.return_value = q
    q.distinct.return_value = q
    q.all.return_value = result
    return q


def _make_seg(seg_id=1, trang_thai='Đủ vị trí', so_can_vt1=3, **kwargs):
    seg = MagicMock(spec=Segment)
    seg.id = seg_id
    seg.trang_thai = trang_thai
    seg.so_can_vt1 = so_can_vt1
    seg.so_can_vt2 = None
    seg.so_can_vt3 = None
    seg.so_can_vt4 = None
    for k, v in kwargs.items():
        setattr(seg, k, v)
    return seg


# ── run_auto_checks ───────────────────────────────────────────────────────────

def test_run_auto_checks_pass():
    repo, session = _make_repo()
    seg = _make_seg(seg_id=1, trang_thai='Đủ vị trí', so_can_vt1=3)

    # query(Segment) → [seg], then dup → [], wrong_pos → []
    session.query.side_effect = [
        _chainable([seg]),
        _chainable([]),   # dup check
        _chainable([]),   # wrong position check
    ]
    repo.count_active_collected_by_segment_vitri.return_value = 3

    svc = VerifierService(repo)
    result = svc.run_auto_checks(nguoi_kiem_tra='alice')

    assert result == {'passed': 1, 'failed': 0, 'skipped': 0}
    assert seg.trang_thai == 'Hoàn thành'

    added_log = session.add.call_args[0][0]
    assert isinstance(added_log, VerificationLog)
    assert added_log.ket_qua == 'PASS'
    assert added_log.loai_kiem_tra == 'auto'
    assert added_log.nguoi_kiem_tra == 'alice'
    assert added_log.source_record_ids is None


def test_run_auto_checks_fail_quantity():
    repo, session = _make_repo()
    seg = _make_seg(seg_id=2, trang_thai='Đủ vị trí', so_can_vt1=3)

    session.query.side_effect = [
        _chainable([seg]),
        _chainable([]),
        _chainable([]),
    ]
    repo.count_active_collected_by_segment_vitri.return_value = 1  # only 1 of 3 needed

    svc = VerifierService(repo)
    result = svc.run_auto_checks()

    assert result == {'passed': 0, 'failed': 1, 'skipped': 0}
    assert seg.trang_thai == 'Dữ liệu sai hoặc lỗi'

    added_log = session.add.call_args[0][0]
    assert added_log.ket_qua.startswith('FAIL:')
    assert added_log.loai_kiem_tra == 'auto'


def test_run_auto_checks_segment_ids_filter_applied():
    """When segment_ids is provided the query must include id.in_(segment_ids)."""
    repo, session = _make_repo()

    seg_q = _chainable([])
    session.query.side_effect = [seg_q]

    svc = VerifierService(repo)
    svc.run_auto_checks(segment_ids={99, 100})

    # The query chain must have called .filter(...) at least twice:
    # once for is_active/trang_thai and once for id.in_(...)
    assert seg_q.filter.call_count >= 2


def test_run_auto_checks_skips_error_state_segments():
    """Segments in 'Dữ liệu sai hoặc lỗi' must not appear in the eligible query."""
    repo, session = _make_repo()

    # Capture the trang_thai filter argument
    captured_filter_args = []
    seg_q = _chainable([])

    original_filter = seg_q.filter.side_effect

    def capture_filter(*args, **kwargs):
        captured_filter_args.extend(args)
        return seg_q

    seg_q.filter.side_effect = capture_filter
    session.query.side_effect = [seg_q]

    svc = VerifierService(repo)
    svc.run_auto_checks()

    # Verify 'Dữ liệu sai hoặc lỗi' is NOT in the status filter
    filter_str = str(captured_filter_args)
    assert 'Dữ liệu sai hoặc lỗi' not in filter_str


def test_run_auto_checks_wrong_position_flagged():
    """Records at invalid positions are captured in source_record_ids on the log."""
    repo, session = _make_repo()
    seg = _make_seg(seg_id=3, trang_thai='Đủ vị trí', so_can_vt1=3)

    # Quantity satisfied: 3 active records at vt1
    repo.count_active_collected_by_segment_vitri.return_value = 3

    # Mock row returned by the wrong-position query
    bad_row = MagicMock()
    bad_row.source_record_id = 'ID-BAD'
    bad_row.vi_tri = 3

    session.query.side_effect = [
        _chainable([seg]),    # Segment query
        _chainable([]),       # dup query — no dups (schema prevents this in practice)
        _chainable([bad_row]),  # wrong-pos query
    ]

    svc = VerifierService(repo)
    result = svc.run_auto_checks(nguoi_kiem_tra='system')

    assert result == {'passed': 0, 'failed': 1, 'skipped': 0}
    assert seg.trang_thai == 'Dữ liệu sai hoặc lỗi'

    added_log = session.add.call_args[0][0]
    assert added_log.source_record_ids == ['ID-BAD']
    assert 'invalid positions' in added_log.ket_qua


# ── save_manual_finding ───────────────────────────────────────────────────────

def test_save_manual_finding_approve():
    repo, session = _make_repo()
    seg = _make_seg(seg_id=5, trang_thai='Đủ vị trí')
    repo.get_segment_by_id.return_value = seg

    svc = VerifierService(repo)
    svc.save_manual_finding(
        segment_id=5,
        nguoi_kiem_tra='bob',
        finding_text='Looks good',
        outcome='pass',
    )

    assert seg.trang_thai == 'Hoàn thành'
    added_log = session.add.call_args[0][0]
    assert isinstance(added_log, VerificationLog)
    assert added_log.loai_kiem_tra == 'manual'
    assert added_log.nguoi_kiem_tra == 'bob'
    assert added_log.ket_qua.startswith('MANUAL-PASS:')


def test_save_manual_finding_fail_requires_notes():
    repo, session = _make_repo()

    svc = VerifierService(repo)
    with pytest.raises(ValueError, match='Notes are required'):
        svc.save_manual_finding(
            segment_id=5,
            nguoi_kiem_tra='bob',
            finding_text='   ',
            outcome='fail',
        )

    # Session must not have been opened
    session.add.assert_not_called()


def test_save_manual_finding_blank_inspector_raises():
    repo, _ = _make_repo()

    svc = VerifierService(repo)
    with pytest.raises(ValueError, match='Inspector name must not be empty'):
        svc.save_manual_finding(
            segment_id=5,
            nguoi_kiem_tra='',
            finding_text='something',
            outcome='pass',
        )


def test_save_manual_finding_wrong_state_raises():
    repo, session = _make_repo()
    seg = _make_seg(seg_id=7, trang_thai='Đang thu thập')
    repo.get_segment_by_id.return_value = seg

    svc = VerifierService(repo)
    with pytest.raises(ValueError, match="cannot be manually reviewed"):
        svc.save_manual_finding(
            segment_id=7,
            nguoi_kiem_tra='carol',
            finding_text='',
            outcome='pass',
        )

    # trang_thai must not have changed
    assert seg.trang_thai == 'Đang thu thập'
    session.add.assert_not_called()
