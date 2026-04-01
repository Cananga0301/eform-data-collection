"""
E-Form Data Collection — Streamlit Management UI

9 pages covering all management flows (required in v1).

Run locally:
    poetry run streamlit run src/streamlit_app.py

Or via Makefile:
    make streamlit
"""
import os
import sys

# Allow importing from project root when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st

from src.config.static_config import StaticConfig
from src.config.postgresql.postgresql_client import PostgreSQLClient
from src.repository.eform_repository import EformRepository
from src.service.importer_service import ImporterService, ImportValidationError
from src.service.classifier_service import ClassifierService
from src.service.assigner_service import AssignerService
from src.service.syncer_service import SyncerService
from src.service.reporter_service import ReporterService
from src.service.verifier_service import VerifierService
from src.clients.collection_client import StubCollectionClient

# ── Shared setup ──────────────────────────────────────────────────────────────

@st.cache_resource
def get_services():
    args_env = os.environ.get('FLASK_ENV', 'dev')
    static_config = StaticConfig(app_args={'env': args_env})
    pg = PostgreSQLClient(static_config)
    repo = EformRepository(pg)
    classifier = ClassifierService()
    return {
        'repo': repo,
        'importer': ImporterService(repo, classifier),
        'assigner': AssignerService(repo),
        'syncer': SyncerService(repo, StubCollectionClient()),
        'reporter': ReporterService(repo),
        'verifier': VerifierService(repo),
    }


PAGES = [
    'Import & Classify',
    'HO Review / Group Override',
    'Branch Mapping',
    'Assignment Export / Import',
    'Sync Status',
    'Progress Dashboard',
    'Unmapped Records',
    'Reports',
    'Verification',
]

# ── Sidebar navigation ────────────────────────────────────────────────────────

st.set_page_config(page_title='E-Form Data Collection', layout='wide')
st.sidebar.title('E-Form Data Collection')
page = st.sidebar.radio('Navigate', PAGES)

svc = get_services()

# ── Page 1: Import & Classify ─────────────────────────────────────────────────

if page == 'Import & Classify':
    st.header('Import & Classify')
    st.write('Upload 1–3 Excel files (HCM, Hà Nội, Đồng Nai) to import route segments.')

    uploaded = st.file_uploader('Upload Excel files', type=['xlsx'], accept_multiple_files=True)
    if st.button('Run Import') and uploaded:
        import tempfile, os as _os
        results = []
        errors = []
        for f in uploaded:
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                tmp.write(f.read())
                tmp_path = tmp.name
            try:
                result = svc['importer'].import_excel(tmp_path, source_name=f.name)
                results.append({'file': f.name, 'status': 'success', **result, 'message': ''})
            except ImportValidationError as exc:
                results.append({
                    'file': f.name,
                    'status': 'error',
                    'upserted': None,
                    'deactivated': None,
                    'message': str(exc),
                })
                errors.append(str(exc))
            finally:
                _os.unlink(tmp_path)
        if errors:
            st.warning('Import finished with errors.')
            for message in errors:
                st.error(message)
        else:
            st.success('Import complete.')
        st.dataframe(results)

# ── Page 2: HO Review / Group Override ───────────────────────────────────────

elif page == 'HO Review / Group Override':
    st.header('HO Review / Group Override')
    st.write('Export a review Excel with editable nhom column, then re-import to apply changes.')

    col1, col2 = st.columns(2)

    with col1:
        st.subheader('Export Review File')

        with svc['repo'].session_scope() as session:
            ho_province_options = svc['repo'].get_distinct_tinh_thanh(session)

        ho_province_choice = st.selectbox(
            'Province',
            options=['All provinces'] + ho_province_options,
            key='ho_province',
        )
        ho_selected_province = None if ho_province_choice == 'All provinces' else ho_province_choice

        with svc['repo'].session_scope() as session:
            ho_ward_options = svc['repo'].get_distinct_xa_phuong(session, tinh_thanh=ho_selected_province)

        ho_ward_choice = st.selectbox(
            'Ward / Zone',
            options=['All wards'] + ho_ward_options,
            key='ho_ward',
        )
        ho_selected_ward = None if ho_ward_choice == 'All wards' else ho_ward_choice

        if st.button('Export HO Review Excel'):
            import pandas as pd
            from io import BytesIO
            from src.utils.text import normalize
            with svc['repo'].session_scope() as session:
                from src.models.eform_models import Segment
                q = session.query(Segment).filter_by(is_active=True)
                if ho_selected_province:
                    q = q.filter(Segment.tinh_thanh_norm == normalize(ho_selected_province))
                if ho_selected_ward:
                    q = q.filter(Segment.xa_phuong_norm == normalize(ho_selected_ward))
                segs = q.all()
                rows = [{
                    'segment_id': s.id, 'tinh_thanh': s.tinh_thanh,
                    'xa_phuong': s.xa_phuong, 'ten_duong': s.ten_duong,
                    'doan': s.doan or '', 'nhom': s.nhom or '',
                    'vt1': s.vt1, 'nhom_manual': s.nhom_manual,
                } for s in segs]
            df = pd.DataFrame(rows)
            buf = BytesIO()
            df.to_excel(buf, index=False)
            st.session_state['ho_review_export'] = buf.getvalue()

        if st.session_state.get('ho_review_export'):
            st.download_button('Download', st.session_state['ho_review_export'], 'ho_review.xlsx')

    with col2:
        st.subheader('Re-import Group Changes')
        ho_file = st.file_uploader('Upload filled HO review file', type=['xlsx'], key='ho_reimport')
        if st.button('Apply Group Changes') and ho_file:
            import pandas as pd
            from datetime import datetime
            df = pd.read_excel(ho_file, dtype=str)
            df = df.where(pd.notna(df), None)
            updated = 0
            with svc['repo'].session_scope() as session:
                from src.models.eform_models import Segment
                for _, row in df.iterrows():
                    if not row.get('segment_id'):
                        continue
                    seg = svc['repo'].get_segment_by_id(session, int(row['segment_id']))
                    if seg and row.get('nhom') and row['nhom'] != seg.nhom:
                        seg.nhom = str(row['nhom']).strip().upper()
                        seg.nhom_manual = True
                        seg.updated_at = datetime.utcnow()
                        updated += 1
            st.success(f'Updated nhom for {updated} segments.')

# ── Page 3: Branch Mapping ────────────────────────────────────────────────────

elif page == 'Branch Mapping':
    st.header('Branch Mapping (Admin)')

    with svc['repo'].session_scope() as session:
        from src.models.eform_models import Branch, BranchMapping
        branches = svc['repo'].get_all_branches(session)
        branch_names = [b.name for b in branches]

    st.subheader('Branches')
    st.write(branch_names if branch_names else 'No branches yet.')

    with st.form('add_branch'):
        new_branch_name = st.text_input('New branch name')
        if st.form_submit_button('Add Branch') and new_branch_name.strip():
            from src.models.eform_models import Branch
            with svc['repo'].session_scope() as session:
                session.add(Branch(name=new_branch_name.strip()))
            st.success(f'Branch "{new_branch_name.strip()}" created.')
            st.rerun()

    st.subheader('Add Mapping')

    with svc['repo'].session_scope() as session:
        bm_province_options = svc['repo'].get_distinct_tinh_thanh(session)
    with svc['repo'].session_scope() as session:
        bm_ward_options = svc['repo'].get_distinct_xa_phuong(session)

    key_type = st.selectbox('Key type', ['xa_phuong', 'tinh_thanh'], key='bm_key_type')
    kv_options = bm_province_options if key_type == 'tinh_thanh' else bm_ward_options
    key_value = st.selectbox('Key value', kv_options, key='bm_key_value') if kv_options else None
    branch_target = st.selectbox('Map to branch', branch_names, key='bm_branch') if branch_names else None

    if st.session_state.get('bm_saved'):
        st.success(st.session_state['bm_saved'])
        del st.session_state['bm_saved']

    if st.button('Save Mapping') and key_value and branch_target:
        from src.models.eform_models import Branch, BranchMapping
        from src.utils.text import normalize
        saved_branch_id = None
        norm_key = normalize(key_value.strip())
        with svc['repo'].session_scope() as session:
            branch = session.query(Branch).filter_by(name=branch_target).first()
            if branch:
                existing = session.query(BranchMapping).filter_by(
                    key_type=key_type,
                    key_value=norm_key,
                ).first()
                if existing:
                    existing.branch_id = branch.id  # update existing mapping
                else:
                    session.add(BranchMapping(
                        branch_id=branch.id,
                        key_type=key_type,
                        key_value=norm_key,
                    ))
                saved_branch_id = branch.id
        if saved_branch_id:
            n = svc['importer'].apply_single_mapping(key_type, norm_key, saved_branch_id)
            st.session_state['bm_saved'] = (
                f'Mapping saved: {key_type} "{key_value}" → {branch_target}  '
                f'({n} segment{"s" if n != 1 else ""} updated)'
            )
        st.rerun()


# ── Page 4: Assignment Export / Import ───────────────────────────────────────

elif page == 'Assignment Export / Import':
    st.header('Assignment Export / Import')

    col1, col2 = st.columns(2)
    with col1:
        st.subheader('Export')

        with svc['repo'].session_scope() as session:
            province_options = svc['repo'].get_distinct_tinh_thanh(session)

        province_choice = st.selectbox(
            'Province',
            options=['All provinces'] + province_options,
        )
        selected_province = None if province_choice == 'All provinces' else province_choice

        with svc['repo'].session_scope() as session:
            ward_options = svc['repo'].get_distinct_xa_phuong(session, tinh_thanh=selected_province)

        ward_choice = st.selectbox(
            'Ward / Zone',
            options=['All wards'] + ward_options,
        )
        selected_ward = None if ward_choice == 'All wards' else ward_choice

        if st.button('Export Assignment Excel'):
            data = svc['assigner'].export_assignment_excel(
                tinh_thanh=selected_province,
                xa_phuong=selected_ward,
            )
            st.session_state['assignment_export'] = data  # persist across reruns

        if st.session_state.get('assignment_export'):
            st.download_button('Download', st.session_state['assignment_export'], 'assignment.xlsx')

    with col2:
        st.subheader('Re-import')
        assign_file = st.file_uploader('Upload filled assignment file', type=['xlsx'])
        if st.button('Import Assignments') and assign_file:
            result = svc['assigner'].import_assignment_excel(assign_file.read())
            st.success(f"Updated: {result['updated']}  Skipped: {result['skipped']}")

# ── Page 5: Sync Status ───────────────────────────────────────────────────────

elif page == 'Sync Status':
    st.header('Sync Status')

    with svc['repo'].session_scope() as session:
        cursor = svc['repo'].get_sync_cursor(session)
        from src.models.eform_models import SyncLog
        last_log = session.query(SyncLog).order_by(SyncLog.started_at.desc()).first()

    if cursor:
        st.metric('Last synced at', str(cursor.last_synced_at or 'Never'))
    if last_log:
        st.write(f"Last run: received={last_log.total_received}  "
                 f"mapped={last_log.total_mapped}  unmapped={last_log.total_unmapped}")

    if st.button('Run Sync Now'):
        with st.spinner('Syncing...'):
            svc['syncer'].run()
        st.success('Sync complete.')
        st.rerun()

# ── Page 6: Progress Dashboard ────────────────────────────────────────────────

elif page == 'Progress Dashboard':
    st.header('Progress Dashboard')
    import pandas as pd

    with svc['repo'].session_scope() as session:
        dash_province_options = svc['repo'].get_distinct_tinh_thanh(session)

    dash_province_choice = st.selectbox(
        'Province',
        options=['All provinces'] + dash_province_options,
        key='dash_province',
    )
    dash_selected_province = None if dash_province_choice == 'All provinces' else dash_province_choice

    with svc['repo'].session_scope() as session:
        dash_ward_options = svc['repo'].get_distinct_xa_phuong(session, tinh_thanh=dash_selected_province)

    dash_ward_choice = st.selectbox(
        'Ward / Zone',
        options=['All wards'] + dash_ward_options,
        key='dash_ward',
    )
    dash_selected_ward = None if dash_ward_choice == 'All wards' else dash_ward_choice

    dashboard = svc['reporter'].get_dashboard_data(
        tinh_thanh=dash_selected_province,
        xa_phuong=dash_selected_ward,
    )
    metrics = dashboard['metrics']
    status_counts = dashboard['status_counts']
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Total Needed', metrics['total_needed'])
    col2.metric('Collected', metrics['total_collected'])
    col3.metric('% Complete', f"{metrics['pct_complete']}%")
    col4.metric('ETA', metrics['eta'])

    extra_col1, extra_col2 = st.columns(2)
    extra_col1.metric('Số đoạn đường chưa bắt đầu', status_counts['not_started'])
    extra_col2.metric('Số đoạn đường đang thu thập', status_counts['in_progress'])

    st.progress(min(max(metrics['pct_complete'] / 100, 0.0), 1.0))

    st.subheader('Overview Breakdown')
    overview_df = pd.DataFrame(dashboard['overview'])
    if overview_df.empty:
        st.info('No grouped progress data for the current filter.')
    else:
        st.dataframe(overview_df, use_container_width=True, hide_index=True)

    st.subheader('Branch Activity')
    st.caption(f"Branches with no new records in the last {dashboard['recent_days']} days are flagged.")
    branch_df = pd.DataFrame(dashboard['branch_activity'])
    if branch_df.empty:
        st.info('No branch activity rows for the current filter.')
    else:
        st.dataframe(branch_df, use_container_width=True, hide_index=True)

    st.subheader('White Zones')
    white_zone_df = pd.DataFrame(dashboard['white_zones'])
    if white_zone_df.empty:
        st.success('No A/B white zones in the current filter.')
    else:
        st.dataframe(white_zone_df, use_container_width=True, hide_index=True)

    st.subheader('Export Current View')
    if st.button('Prepare Dashboard Export'):
        st.session_state['dashboard_export'] = svc['reporter'].export_dashboard_excel(
            tinh_thanh=dash_selected_province,
            xa_phuong=dash_selected_ward,
        )

    if st.session_state.get('dashboard_export'):
        st.download_button(
            'Download Dashboard Excel',
            st.session_state['dashboard_export'],
            'dashboard.xlsx',
        )

# ── Page 7: Unmapped Records ──────────────────────────────────────────────────

elif page == 'Unmapped Records':
    st.header('Unmapped Records')

    with svc['repo'].session_scope() as session:
        unmapped = svc['repo'].get_unresolved_unmapped(session)
        from src.models.eform_models import Segment
        active_segs = session.query(Segment).filter_by(is_active=True).order_by(Segment.ten_duong).all()
        seg_options = {s.id: f"[{s.id}] {s.tinh_thanh} / {s.xa_phuong} / {s.ten_duong} {s.doan or ''}" for s in active_segs}

    if not unmapped:
        st.info('No unresolved records.')
    else:
        st.write(f'{len(unmapped)} unresolved record(s).')
        for u in unmapped:
            with st.expander(f'Record {u.id} — source: {u.source_record_id}'):
                st.write(f'**Reason:** {u.reason}')
                st.json(u.raw_data or {})
                chosen = st.selectbox('Assign to segment', list(seg_options.keys()),
                                      format_func=lambda x: seg_options[x],
                                      key=f'seg_{u.id}')
                if st.button('Resolve', key=f'resolve_{u.id}'):
                    with svc['repo'].session_scope() as session:
                        svc['syncer'].replay_unmapped(session, u.id, chosen)
                    st.success('Resolved.')
                    st.rerun()

# ── Page 8: Reports ───────────────────────────────────────────────────────────

elif page == 'Reports':
    st.header('Daily Reports')

    report_date = st.date_input('Report date')
    if st.button('Generate Report'):
        data = svc['reporter'].generate_daily_report(report_date=report_date)
        st.download_button('Download Excel', data, f'report_{report_date}.xlsx')

# ── Page 9: Verification ──────────────────────────────────────────────────────

elif page == 'Verification':
    st.header('Verification')

    inspector = st.text_input('Inspector name', 'system')
    if st.button('Run Auto-Checks'):
        with st.spinner('Running checks...'):
            result = svc['verifier'].run_auto_checks(nguoi_kiem_tra=inspector)
        st.success(f"Passed: {result['passed']}  Failed: {result['failed']}")

    st.subheader('Verification Log')
    with svc['repo'].session_scope() as session:
        from src.models.eform_models import VerificationLog
        logs = session.query(VerificationLog).order_by(VerificationLog.verified_at.desc()).limit(200).all()
        rows = [{
            'segment_id': l.segment_id,
            'inspector': l.nguoi_kiem_tra,
            'result': l.ket_qua,
            'at': str(l.verified_at),
        } for l in logs]
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows))
    else:
        st.info('No verification records yet.')
