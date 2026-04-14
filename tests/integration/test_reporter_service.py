"""Integration tests for ReporterService._build_employee_stats_rows()."""

from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.models.eform_models import Assignment, Branch, CollectedRecord, Segment
from src.repository.eform_repository import EformRepository
from src.service.reporter_service import ReporterService

VN_UTC_OFFSET = timedelta(hours=7)


class DummyPostgreSQLClient:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_session(self):
        return self._session_factory()


def _build_reporter(db_engine) -> ReporterService:
    session_factory = sessionmaker(bind=db_engine)
    repo = EformRepository(DummyPostgreSQLClient(session_factory))
    return ReporterService(repo)


def _make_segment(session, tinh_thanh='HCM', xa_phuong='Q1', ten_duong='Duong A', doan='D1',
                  nhom='B', so_can_vt1=3, branch=None):
    seg = Segment(
        tinh_thanh=tinh_thanh,
        xa_phuong=xa_phuong,
        ten_duong=ten_duong,
        doan=doan,
        doan_key=doan or ten_duong,
        tinh_thanh_norm=tinh_thanh.lower(),
        xa_phuong_norm=xa_phuong.lower(),
        ten_duong_norm=ten_duong.lower(),
        doan_key_norm=(doan or ten_duong).lower(),
        nhom=nhom,
        so_can_vt1=so_can_vt1,
        is_active=True,
        trang_thai='Chưa bắt đầu',
        branch=branch,
    )
    session.add(seg)
    session.flush()
    return seg


def _make_assignment(session, segment, phu_trach=None, deadline=None, branch=None):
    a = Assignment(
        segment_id=segment.id,
        phu_trach=phu_trach,
        deadline=deadline,
        branch=branch,
    )
    session.add(a)
    session.flush()
    return a


def _make_record(session, segment, first_seen_at, is_active=True):
    cr = CollectedRecord(
        source_record_id=f'src-{segment.id}-{first_seen_at.isoformat()}',
        segment_id=segment.id,
        vi_tri=1,
        raw_data={},
        is_active=is_active,
        first_seen_at=first_seen_at,
        last_synced_at=first_seen_at,
    )
    session.add(cr)
    session.flush()
    return cr


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_same_name_different_branches_produces_separate_rows(db_engine):
    """Two employees with identical phu_trach in different branches must appear as separate rows."""
    Session = sessionmaker(bind=db_engine)
    session = Session()

    branch_a = Branch(name='Branch A')
    branch_b = Branch(name='Branch B')
    session.add_all([branch_a, branch_b])
    session.flush()

    seg_a = _make_segment(session, ten_duong='Road A', doan='1', branch=branch_a)
    seg_b = _make_segment(session, ten_duong='Road B', doan='2', branch=branch_b)

    _make_assignment(session, seg_a, phu_trach='Lan', branch=branch_a)
    _make_assignment(session, seg_b, phu_trach='Lan', branch=branch_b)
    session.commit()
    session.close()

    reporter = _build_reporter(db_engine)
    data = reporter.get_dashboard_data()
    rows = data['employee_stats']

    lan_rows = [r for r in rows if r['Employee'] == 'Lan']
    assert len(lan_rows) == 2, "Same name in different branches must produce two rows"
    branches = {r['Branch'] for r in lan_rows}
    assert branches == {'Branch A', 'Branch B'}


def test_unassigned_segments_grouped_under_chua_phan_cong(db_engine):
    """Segments with no phu_trach must appear under '(Chưa phân công)' with _unassigned=True."""
    Session = sessionmaker(bind=db_engine)
    session = Session()

    branch = Branch(name='Branch X')
    session.add(branch)
    session.flush()

    seg = _make_segment(session, ten_duong='Road X', doan='1', branch=branch)
    _make_assignment(session, seg, phu_trach=None, branch=branch)
    session.commit()
    session.close()

    reporter = _build_reporter(db_engine)
    data = reporter.get_dashboard_data()
    rows = data['employee_stats']

    unassigned = [r for r in rows if r['_unassigned']]
    assert len(unassigned) >= 1
    assert all(r['Employee'] == '(Chưa phân công)' for r in unassigned)


def test_overdue_takes_precedence_over_idle(db_engine):
    """An employee past deadline with missing work must have _overdue=True and _idle=False."""
    Session = sessionmaker(bind=db_engine)
    session = Session()

    branch = Branch(name='Branch Y')
    session.add(branch)
    session.flush()

    seg = _make_segment(session, ten_duong='Road Y', doan='1', so_can_vt1=3, branch=branch)
    past_deadline = date.today() - timedelta(days=5)
    _make_assignment(session, seg, phu_trach='Minh', deadline=past_deadline, branch=branch)
    # No collected records → missing=3, overdue, no recent activity
    session.commit()
    session.close()

    reporter = _build_reporter(db_engine)
    data = reporter.get_dashboard_data()
    rows = data['employee_stats']

    minh = next(r for r in rows if r['Employee'] == 'Minh')
    assert minh['_overdue'] is True
    assert minh['_idle'] is False


def test_deadline_boundary_record_counts_as_before(db_engine):
    """A record with first_seen_at exactly at midnight Vietnam time on the deadline date
    must appear in Before Deadline, not After Deadline."""
    Session = sessionmaker(bind=db_engine)
    session = Session()

    branch = Branch(name='Branch Z')
    session.add(branch)
    session.flush()

    deadline_date = date.today() - timedelta(days=2)
    # midnight Vietnam time (UTC+7) = 17:00 UTC previous day
    midnight_vn_utc = datetime(
        deadline_date.year, deadline_date.month, deadline_date.day,
        0, 0, 0, tzinfo=timezone(VN_UTC_OFFSET)
    )

    seg = _make_segment(session, ten_duong='Road Z', doan='1', branch=branch)
    _make_assignment(session, seg, phu_trach='Tuan', deadline=deadline_date, branch=branch)
    _make_record(session, seg, first_seen_at=midnight_vn_utc.astimezone(timezone.utc))
    session.commit()
    session.close()

    reporter = _build_reporter(db_engine)
    data = reporter.get_dashboard_data()
    rows = data['employee_stats']

    tuan = next(r for r in rows if r['Employee'] == 'Tuan')
    assert tuan['Before Deadline'] == 1
    assert tuan['After Deadline'] == 0


def test_no_deadline_records_do_not_appear_in_deadline_buckets(db_engine):
    """Records for segments without a deadline must appear only in No Deadline, not Before/After."""
    Session = sessionmaker(bind=db_engine)
    session = Session()

    branch = Branch(name='Branch ND')
    session.add(branch)
    session.flush()

    seg = _make_segment(session, ten_duong='Road ND', doan='1', branch=branch)
    _make_assignment(session, seg, phu_trach='Hoa', deadline=None, branch=branch)
    _make_record(session, seg, first_seen_at=datetime.now(timezone.utc) - timedelta(days=1))
    session.commit()
    session.close()

    reporter = _build_reporter(db_engine)
    data = reporter.get_dashboard_data()
    rows = data['employee_stats']

    hoa = next(r for r in rows if r['Employee'] == 'Hoa')
    assert hoa['Before Deadline'] == 0
    assert hoa['After Deadline'] == 0
    assert hoa['No Deadline'] == 1
