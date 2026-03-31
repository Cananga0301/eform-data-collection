"""
T4 — Daily progress report and dashboard metrics.

Sheet 1 — Overview: Province → Branch → Group (A/B/C) hierarchy.
           Branch rows highlighted if 0 new first_seen_at records in last 2 days.
Sheet 2 — White Zones: Group A & B segments with insufficient data.
Sheet 3 — Unmapped Records: unresolved records awaiting manual processing.

ETA: (remaining / avg_first_seen_per_day_last_7_days). "Unknown" if velocity = 0.
All queries use first_seen_at (never last_synced_at) for velocity / branch alerts.
Deactivated segments are excluded from all totals.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import openpyxl
from openpyxl.styles import PatternFill
from sqlalchemy import func

from config import BRANCH_ALERT_DAYS, ETA_WINDOW_DAYS
from src.models.eform_models import (
    Assignment, Branch, CollectedRecord, Segment, UnmappedRecord,
)
from src.repository.eform_repository import EformRepository

logger = logging.getLogger(__name__)

YELLOW_FILL = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')


class ReporterService:
    def __init__(self, repository: EformRepository):
        self.repo = repository

    def get_dashboard_metrics(self) -> dict:
        """
        Returns the 4 summary metrics for the Streamlit dashboard.
        Deactivated segments excluded.
        """
        with self.repo.session_scope() as session:
            active_segs = session.query(Segment).filter_by(is_active=True).all()

            total_needed = sum(
                (s.so_can_vt1 or 0) + (s.so_can_vt2 or 0) +
                (s.so_can_vt3 or 0) + (s.so_can_vt4 or 0)
                for s in active_segs
            )
            seg_ids = [s.id for s in active_segs]

            total_collected = session.query(CollectedRecord).filter(
                CollectedRecord.segment_id.in_(seg_ids),
                CollectedRecord.is_active == True,
            ).count() if seg_ids else 0

            pct = round(total_collected / total_needed * 100, 1) if total_needed else 0.0
            eta = self._compute_eta(session, seg_ids, total_needed, total_collected)

            return {
                'total_needed': total_needed,
                'total_collected': total_collected,
                'pct_complete': pct,
                'eta': eta,
            }

    def generate_daily_report(self, report_date: Optional[date] = None) -> bytes:
        """Generate 3-sheet Excel report. Returns raw bytes."""
        if report_date is None:
            report_date = date.today()

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        with self.repo.session_scope() as session:
            self._build_sheet1(wb, session, report_date)
            self._build_sheet2(wb, session)
            self._build_sheet3(wb, session)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # ── Sheet 1: Overview ─────────────────────────────────────────────────────

    def _build_sheet1(self, wb, session, report_date: date):
        ws = wb.create_sheet('Overview')
        cutoff = datetime.combine(report_date - timedelta(days=BRANCH_ALERT_DAYS), datetime.min.time()).replace(tzinfo=timezone.utc)

        headers = ['Province', 'Branch', 'Group', 'Total Needed', 'Collected', '% Done', 'New (last 2d)']
        ws.append(headers)

        active_segs = session.query(Segment).filter_by(is_active=True).all()

        # Build a grouped structure: province → branch_name → group → rows
        from collections import defaultdict
        data: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'needed': 0, 'collected': 0, 'new': 0})))

        for seg in active_segs:
            province = seg.tinh_thanh or 'Unknown'
            branch = seg.branch.name if seg.branch else 'Unassigned'
            group = seg.nhom or '?'

            needed = (
                (seg.so_can_vt1 or 0) + (seg.so_can_vt2 or 0) +
                (seg.so_can_vt3 or 0) + (seg.so_can_vt4 or 0)
            )
            collected = session.query(CollectedRecord).filter_by(
                segment_id=seg.id, is_active=True
            ).count()
            new_count = session.query(CollectedRecord).filter(
                CollectedRecord.segment_id == seg.id,
                CollectedRecord.is_active == True,
                CollectedRecord.first_seen_at >= cutoff,
            ).count()

            d = data[province][branch][group]
            d['needed'] += needed
            d['collected'] += collected
            d['new'] += new_count

        for province, branches in sorted(data.items()):
            for branch_name, groups in sorted(branches.items()):
                new_total = sum(g['new'] for g in groups.values())
                for group, vals in sorted(groups.items()):
                    pct = round(vals['collected'] / vals['needed'] * 100, 1) if vals['needed'] else 0.0
                    row = ws.append([province, branch_name, group, vals['needed'], vals['collected'], pct, vals['new']])
                    # Highlight entire branch block if zero new records
                    if new_total == 0:
                        for cell in ws[ws.max_row]:
                            cell.fill = YELLOW_FILL

    # ── Sheet 2: White Zones ──────────────────────────────────────────────────

    def _build_sheet2(self, wb, session):
        ws = wb.create_sheet('White Zones')
        headers = ['Province', 'Ward/Zone', 'Road', 'Segment', 'Group', 'Branch', 'Person', 'Missing']
        ws.append(headers)

        segs = session.query(Segment).filter(
            Segment.is_active == True,
            Segment.nhom.in_(['A', 'B']),
        ).all()

        rows = []
        for seg in segs:
            needed = (
                (seg.so_can_vt1 or 0) + (seg.so_can_vt2 or 0) +
                (seg.so_can_vt3 or 0) + (seg.so_can_vt4 or 0)
            )
            collected = session.query(CollectedRecord).filter_by(
                segment_id=seg.id, is_active=True
            ).count()
            missing = needed - collected
            if missing <= 0:
                continue

            assignment = self.repo.get_assignment_by_segment(session, seg.id)
            branch_name = ''
            if assignment and assignment.branch:
                branch_name = assignment.branch.name
            elif seg.branch:
                branch_name = seg.branch.name

            rows.append({
                'province': seg.tinh_thanh or '',
                'ward': seg.xa_phuong or '',
                'road': seg.ten_duong or '',
                'segment': seg.doan or '',
                'group': seg.nhom or '',
                'branch': branch_name,
                'person': assignment.phu_trach if assignment else '',
                'missing': missing,
            })

        rows.sort(key=lambda r: -r['missing'])
        for r in rows:
            ws.append([r['province'], r['ward'], r['road'], r['segment'],
                       r['group'], r['branch'], r['person'], r['missing']])

    # ── Sheet 3: Unmapped Records ─────────────────────────────────────────────

    def _build_sheet3(self, wb, session):
        ws = wb.create_sheet('Unmapped Records')
        headers = ['ID', 'Source Record ID', 'Reason', 'Raw Data Preview']
        ws.append(headers)

        unmapped = session.query(UnmappedRecord).filter_by(resolved=False).all()
        for u in unmapped:
            preview = str(u.raw_data)[:200] if u.raw_data else ''
            ws.append([u.id, u.source_record_id, u.reason, preview])

    # ── ETA ───────────────────────────────────────────────────────────────────

    def _compute_eta(self, session, seg_ids: list, total_needed: int, total_collected: int) -> str:
        remaining = total_needed - total_collected
        if remaining <= 0:
            return date.today().isoformat()

        window_start = datetime.now(timezone.utc) - timedelta(days=ETA_WINDOW_DAYS)
        new_in_window = session.query(CollectedRecord).filter(
            CollectedRecord.segment_id.in_(seg_ids),
            CollectedRecord.is_active == True,
            CollectedRecord.first_seen_at >= window_start,
        ).count() if seg_ids else 0

        velocity = new_in_window / ETA_WINDOW_DAYS
        if velocity == 0:
            return 'Unknown'

        days_left = remaining / velocity
        eta_date = date.today() + timedelta(days=days_left)
        return eta_date.isoformat()
