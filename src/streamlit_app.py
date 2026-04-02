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
from src.clients.collection_client import StubCollectionClient, FileCollectionClient

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

    # ── Filter row ───────────────────────────────────────────────────────────
    with svc['repo'].session_scope() as session:
        ho_province_options = svc['repo'].get_distinct_tinh_thanh(session)

    f_col1, f_col2, f_col3 = st.columns([3, 3, 2], vertical_alignment='bottom')
    with f_col1:
        ho_province_choice = st.selectbox(
            'Province', ['All provinces'] + ho_province_options, key='ho_province'
        )
    ho_selected_province = None if ho_province_choice == 'All provinces' else ho_province_choice

    with svc['repo'].session_scope() as session:
        ho_ward_options = svc['repo'].get_distinct_xa_phuong(session, tinh_thanh=ho_selected_province)

    with f_col2:
        ho_ward_choice = st.selectbox(
            'Ward / Zone', ['All wards'] + ho_ward_options, key='ho_ward'
        )
    ho_selected_ward = None if ho_ward_choice == 'All wards' else ho_ward_choice

    both_selected = ho_selected_province is not None and ho_selected_ward is not None
    with f_col3:
        load_clicked = st.button(
            'Load Segments', width='stretch', disabled=not both_selected
        )
    if not both_selected:
        st.caption('Select both a province and a ward / zone to load segments.')

    # ── Load ─────────────────────────────────────────────────────────────────
    if load_clicked and both_selected:
        import pandas as pd
        from src.utils.text import normalize
        with svc['repo'].session_scope() as session:
            from src.models.eform_models import Segment
            segs = (
                session.query(Segment)
                .filter(
                    Segment.is_active == True,
                    Segment.tinh_thanh_norm == normalize(ho_selected_province),
                    Segment.xa_phuong_norm == normalize(ho_selected_ward),
                )
                .order_by(Segment.ten_duong, Segment.doan)
                .all()
            )
            rows = [{
                'selected': False,
                'segment_id': s.id,
                'ten_duong': s.ten_duong or '',
                'doan': s.doan or '',
                'vt1': s.vt1,
                'nhom': s.nhom or '',
                'nhom_manual': bool(s.nhom_manual),
            } for s in segs]
        df = pd.DataFrame(rows)
        st.session_state['ho_segments_df'] = df
        st.session_state['ho_segments_original'] = df.copy()
        st.session_state['ho_editor_version'] = st.session_state.get('ho_editor_version', 0) + 1
        # clear stale select-all state so it can't bleed into the new table
        st.session_state.pop('_ho_select_all_prev', None)
        st.session_state.pop('ho_segments_edited', None)

    # ── Table + bulk apply ───────────────────────────────────────────────────
    if 'ho_segments_df' in st.session_state:
        import pandas as pd
        if st.session_state['ho_segments_df'].empty:
            st.info('No segments found for the selected filter.')
        else:
            df = st.session_state['ho_segments_df']
            st.caption(f'{len(df)} segments loaded')

            # ── Select-all + bulk apply controls ────────────────────────────
            ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 4, 2], vertical_alignment='bottom')
            with ctrl_col1:
                sa_c1, sa_c2 = st.columns(2)
                with sa_c1:
                    if st.button('Select all', width='stretch'):
                        upd = st.session_state.get('ho_segments_edited', st.session_state['ho_segments_df']).copy()
                        upd['selected'] = True
                        st.session_state['ho_segments_df'] = upd
                        st.session_state['ho_editor_version'] = (
                            st.session_state.get('ho_editor_version', 0) + 1
                        )
                with sa_c2:
                    if st.button('Deselect all', width='stretch'):
                        upd = st.session_state.get('ho_segments_edited', st.session_state['ho_segments_df']).copy()
                        upd['selected'] = False
                        st.session_state['ho_segments_df'] = upd
                        st.session_state['ho_editor_version'] = (
                            st.session_state.get('ho_editor_version', 0) + 1
                        )
            with ctrl_col2:
                bulk_nhom = st.selectbox(
                    'Set all selected rows to:', ['(no change)', 'A', 'B', 'C'],
                    key='ho_bulk_nhom',
                )
            with ctrl_col3:
                if st.button('Apply to selected', width='stretch') and bulk_nhom != '(no change)':
                    upd = st.session_state.get('ho_segments_edited', st.session_state['ho_segments_df']).copy()
                    mask = upd['selected'].fillna(False).astype(bool)
                    upd.loc[mask, 'nhom'] = bulk_nhom
                    st.session_state['ho_segments_df'] = upd
                    st.session_state['ho_editor_version'] = (
                        st.session_state.get('ho_editor_version', 0) + 1
                    )

            edited_df = st.data_editor(
                st.session_state['ho_segments_df'],
                column_config={
                    'selected': st.column_config.CheckboxColumn('✓', default=False),
                    'segment_id': st.column_config.NumberColumn('ID', disabled=True),
                    'ten_duong': st.column_config.TextColumn('Road', disabled=True),
                    'doan': st.column_config.TextColumn('Segment', disabled=True),
                    'vt1': st.column_config.NumberColumn('VT1 Price', disabled=True),
                    'nhom': st.column_config.SelectboxColumn(
                        'Nhom', options=['A', 'B', 'C'], required=True
                    ),
                    'nhom_manual': st.column_config.CheckboxColumn('Manual?', disabled=True),
                },
                width='stretch',
                hide_index=True,
                key=f'ho_editor_{st.session_state.get("ho_editor_version", 0)}',
            )
            # Mirror only — do NOT overwrite the stable base used by data_editor
            st.session_state['ho_segments_edited'] = edited_df

            if st.button('Save Changes'):
                original = st.session_state['ho_segments_original']

                def _nhom(v):
                    return '' if pd.isna(v) or str(v).strip() == '' else str(v).strip().upper()

                changed_mask = edited_df['nhom'].apply(_nhom) != original['nhom'].apply(_nhom)
                changed_df = edited_df[changed_mask]

                updated = 0
                if not changed_df.empty:
                    changed_ids = changed_df['segment_id'].astype(int).tolist()
                    nhom_by_id = {
                        int(r['segment_id']): _nhom(r['nhom'])
                        for _, r in changed_df.iterrows()
                        if _nhom(r['nhom'])
                    }
                    from datetime import datetime
                    with svc['repo'].session_scope() as session:
                        from src.models.eform_models import Segment
                        segs = session.query(Segment).filter(
                            Segment.id.in_(changed_ids)
                        ).all()
                        for seg in segs:
                            new_nhom = nhom_by_id.get(seg.id)
                            if new_nhom:
                                seg.nhom = new_nhom
                                seg.nhom_manual = True
                                seg.updated_at = datetime.utcnow()
                                updated += 1

                    saved_ids = set(nhom_by_id.keys())
                    refreshed = st.session_state.get('ho_segments_edited', st.session_state['ho_segments_df']).copy()
                    refreshed.loc[refreshed['segment_id'].isin(saved_ids), 'nhom_manual'] = True
                    st.session_state['ho_segments_df'] = refreshed
                    st.session_state['ho_segments_original'] = refreshed.copy()
                    st.session_state['ho_editor_version'] = (
                        st.session_state.get('ho_editor_version', 0) + 1
                    )

                st.success(f'Saved — {updated} segment{"s" if updated != 1 else ""} updated.')

    # ── Excel export ──────────────────────────────────────────────────────────
    st.divider()
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
        df_exp = pd.DataFrame(rows)
        buf = BytesIO()
        df_exp.to_excel(buf, index=False)
        st.session_state['ho_review_export'] = buf.getvalue()
    if st.session_state.get('ho_review_export'):
        st.download_button('Download', st.session_state['ho_review_export'], 'ho_review.xlsx')

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

    use_fixture = st.checkbox('Use test fixture (test_collected_records.json)')

    if st.button('Run Sync Now'):
        if use_fixture:
            syncer_to_run = SyncerService(
                svc['repo'],
                FileCollectionClient(
                    r'C:\Users\phukt\gathering_data\eform-data-collection\test_collected_records.json'
                ),
            )
        else:
            syncer_to_run = svc['syncer']
        with st.spinner('Syncing...'):
            affected_ids = syncer_to_run.run()
            if affected_ids:
                svc['verifier'].run_auto_checks(nguoi_kiem_tra='system', segment_ids=affected_ids)
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

    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric('Số đoạn đường chưa bắt đầu',  status_counts['not_started'])
    sc2.metric('Số đoạn đường đang thu thập',  status_counts['in_progress'])
    sc3.metric('Số đoạn đường đủ vị trí',      status_counts['enough_positions'])
    sc4.metric('Số đoạn đường dữ liệu lỗi',   status_counts['error'])
    sc5.metric('Số đoạn đường đã hoàn thành', status_counts['completed'])

    st.progress(min(max(metrics['pct_complete'] / 100, 0.0), 1.0))

    st.subheader('Overview Breakdown')
    overview_df = pd.DataFrame(dashboard['overview'])
    if overview_df.empty:
        st.info('No grouped progress data for the current filter.')
    else:
        st.dataframe(overview_df, width='stretch', hide_index=True)

    st.subheader('Branch Activity')
    st.caption(f"Branches with no new records in the last {dashboard['recent_days']} days are flagged.")
    branch_df = pd.DataFrame(dashboard['branch_activity'])
    if branch_df.empty:
        st.info('No branch activity rows for the current filter.')
    else:
        st.dataframe(branch_df, width='stretch', hide_index=True)

    st.subheader('White Zones')
    white_zone_df = pd.DataFrame(dashboard['white_zones'])
    if white_zone_df.empty:
        st.success('No A/B white zones in the current filter.')
    else:
        st.dataframe(white_zone_df, width='stretch', hide_index=True)

    st.subheader('Segment Record Detail')

    # ── Own Province → Ward → Segment cascade (independent of main filters) ───
    with svc['repo'].session_scope() as session:
        _detail_province_opts = svc['repo'].get_distinct_tinh_thanh(session)
    _detail_province_choice = st.selectbox(
        'Province',
        options=['All provinces'] + _detail_province_opts,
        key='detail_province',
    )
    _detail_selected_province = None if _detail_province_choice == 'All provinces' else _detail_province_choice

    with svc['repo'].session_scope() as session:
        _detail_ward_opts = svc['repo'].get_distinct_xa_phuong(
            session, tinh_thanh=_detail_selected_province
        )
    _detail_ward_choice = st.selectbox(
        'Ward / Zone',
        options=['All wards'] + _detail_ward_opts,
        key='detail_ward',
    )
    _detail_selected_ward = None if _detail_ward_choice == 'All wards' else _detail_ward_choice

    with svc['repo'].session_scope() as session:
        from src.models.eform_models import Segment as _Seg
        from src.utils.text import normalize as _norm
        _q = session.query(_Seg).filter(_Seg.is_active == True)
        if _detail_selected_province:
            _q = _q.filter(_Seg.tinh_thanh_norm == _norm(_detail_selected_province))
        if _detail_selected_ward:
            _q = _q.filter(_Seg.xa_phuong_norm == _norm(_detail_selected_ward))
        _detail_segs = [
            {
                'id':         seg.id,
                'tinh_thanh': seg.tinh_thanh or '',
                'xa_phuong':  seg.xa_phuong or '',
                'label':      (seg.ten_duong or '') + (' / ' + seg.doan if seg.doan else ''),
                'trang_thai': seg.trang_thai,
                # Only include positions that are actually required for this segment.
                'so_can': {
                    vt: cnt for vt, cnt in {
                        1: seg.so_can_vt1,
                        2: seg.so_can_vt2,
                        3: seg.so_can_vt3,
                        4: seg.so_can_vt4,
                    }.items() if cnt
                },
            }
            for seg in _q.order_by(_Seg.ten_duong, _Seg.doan).all()
        ]

    if not _detail_segs:
        st.info('No segments match the current province / ward filter.')
    else:
        # Use segment id as the select value to avoid label collisions.
        _id_to_seg   = {s['id']: s for s in _detail_segs}
        _seg_options = [s['id'] for s in _detail_segs]

        def _fmt_seg(seg_id: int) -> str:
            """Prefix ward (and province) only when the corresponding filter is
            set to 'All', so labels are always unambiguous."""
            s = _id_to_seg[seg_id]
            parts: list[str] = []
            if not _detail_selected_province:
                parts.append(s['tinh_thanh'])
            if not _detail_selected_ward:
                parts.append(s['xa_phuong'])
            parts.append(s['label'])
            return ' — '.join(p for p in parts if p)

        _chosen_id = st.selectbox(
            'Segment', options=_seg_options, format_func=_fmt_seg, key='detail_seg'
        )
        _chosen = _id_to_seg[_chosen_id]

        # ── Fetch records ──────────────────────────────────────────────────────
        with svc['repo'].session_scope() as session:
            _records = svc['repo'].get_collected_records_for_segment(session, _chosen_id)

        _active   = [r for r in _records if     r['is_active']]
        _inactive = [r for r in _records if not r['is_active']]
        _so_can   = _chosen['so_can']                         # {1: 3, 2: 3, ...}
        _needed   = sum(_so_can.values())                     # total required

        # Per-position active counts — keyed by vi_tri int
        _vt_active: dict[int, int] = {}
        for r in _active:
            vt = r['vi_tri']
            _vt_active[vt] = _vt_active.get(vt, 0) + 1

        # Còn thiếu = sum of per-position deficits (correct, not total-row based)
        _con_thieu = sum(
            max(0, need - _vt_active.get(vt, 0))
            for vt, need in _so_can.items()
        )

        # ── Summary metrics ────────────────────────────────────────────────────
        dc1, dc2, dc3, dc4 = st.columns(4)
        dc1.metric('Trạng thái',   _chosen['trang_thai'])
        dc2.metric('Cần thu thập', _needed)
        dc3.metric('Đã thu thập',  len(_active))
        dc4.metric('Còn thiếu',    _con_thieu)

        # ── Per-position breakdown (all required positions, even zero-count) ───
        if _so_can:
            _vt_parts = [
                f"vt{vt}: {_vt_active.get(vt, 0)}/{need}"
                for vt, need in sorted(_so_can.items())
            ]
            st.caption('Số lượng theo vị trí — ' + '  |  '.join(_vt_parts))
        if _inactive:
            st.caption(f"⚠ {len(_inactive)} bản ghi đã bị xoá mềm (không tính vào Đã thu thập)")

        # ── Records table + raw data ───────────────────────────────────────────
        if _records:
            _tbl = [{k: v for k, v in r.items() if k != 'raw_data'} for r in _records]
            st.dataframe(pd.DataFrame(_tbl), width='stretch', hide_index=True)
            with st.expander('Raw data (JSON)'):
                for r in _records:
                    _del_tag = ' *(deleted)*' if not r['is_active'] else ''
                    st.markdown(f"**{r['source_record_id']}**{_del_tag}")
                    st.json(r['raw_data'])
        else:
            st.info('Chưa có bản ghi nào cho đoạn đường này.')

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

    # Fetch unmapped records as dicts to avoid detached-instance issues.
    with svc['repo'].session_scope() as session:
        _p7_unmapped = [
            {
                'id':               u.id,
                'source_record_id': u.source_record_id,
                'reason':           u.reason,
                'raw_data':         u.raw_data or {},
            }
            for u in svc['repo'].get_unresolved_unmapped(session)
        ]

    if not _p7_unmapped:
        st.info('No unresolved records.')
    else:
        st.write(f'{len(_p7_unmapped)} unresolved record(s).')

        # Province list is the same for every record — fetch once.
        with svc['repo'].session_scope() as session:
            _p7_province_opts = svc['repo'].get_distinct_tinh_thanh(session)

        # Flash message from previous resolve action — st.success() before
        # st.rerun() is never seen, so the message is stored in session state.
        if st.session_state.get('p7_resolved'):
            st.success(st.session_state['p7_resolved'])
            del st.session_state['p7_resolved']

        # ── Unmapped record list ───────────────────────────────────────────────
        for u in _p7_unmapped:
            _uid = u['id']
            with st.expander(f"Record {_uid} — source: {u['source_record_id']}"):
                st.write(f"**Reason:** {u['reason']}")
                st.json(u['raw_data'])

                # Province → Ward → Segment cascade, independent per record.
                _p7_prov_choice = st.selectbox(
                    'Province',
                    options=['All provinces'] + _p7_province_opts,
                    key=f'p7_province_{_uid}',
                )
                _p7_sel_prov = None if _p7_prov_choice == 'All provinces' else _p7_prov_choice

                with svc['repo'].session_scope() as session:
                    _p7_ward_opts = svc['repo'].get_distinct_xa_phuong(
                        session, tinh_thanh=_p7_sel_prov
                    )
                _p7_ward_choice = st.selectbox(
                    'Ward / Zone',
                    options=['All wards'] + _p7_ward_opts,
                    key=f'p7_ward_{_uid}',
                )
                _p7_sel_ward = None if _p7_ward_choice == 'All wards' else _p7_ward_choice

                with svc['repo'].session_scope() as session:
                    from src.models.eform_models import Segment as _P7Seg
                    from src.utils.text import normalize as _p7_norm
                    _p7_q = session.query(_P7Seg).filter(_P7Seg.is_active == True)
                    if _p7_sel_prov:
                        _p7_q = _p7_q.filter(_P7Seg.tinh_thanh_norm == _p7_norm(_p7_sel_prov))
                    if _p7_sel_ward:
                        _p7_q = _p7_q.filter(_P7Seg.xa_phuong_norm == _p7_norm(_p7_sel_ward))
                    _p7_seg_opts = {
                        s.id: (
                            (f"{s.tinh_thanh} / " if not _p7_sel_prov else '')
                            + (f"{s.xa_phuong} / " if not _p7_sel_ward else '')
                            + f"{s.ten_duong or ''}"
                            + (f" / {s.doan}" if s.doan else '')
                        ).strip(' /')
                        for s in _p7_q.order_by(_P7Seg.ten_duong, _P7Seg.doan).all()
                    }

                if not _p7_seg_opts:
                    st.warning('No segments found for the selected province / ward.')
                else:
                    chosen = st.selectbox(
                        'Assign to segment',
                        options=list(_p7_seg_opts.keys()),
                        format_func=lambda x: _p7_seg_opts[x],
                        key=f'seg_{_uid}',
                    )
                    if st.button('Resolve', key=f'resolve_{_uid}'):
                        with svc['repo'].session_scope() as session:
                            affected_id = svc['syncer'].replay_unmapped(session, _uid, chosen)
                        if affected_id:
                            svc['verifier'].run_auto_checks(
                                nguoi_kiem_tra='system', segment_ids={affected_id}
                            )
                        st.session_state['p7_resolved'] = (
                            f"Record {u['source_record_id']} resolved successfully."
                        )
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

    # ── Section A: Inspector name ─────────────────────────────────────────────
    inspector = st.text_input('Inspector name', value='', key='vf_inspector')
    inspector_valid = bool(inspector.strip())
    if st.session_state.pop('vf_flash', None):
        st.success(st.session_state.pop('vf_flash_msg', ''))

    st.divider()

    # ── Section B: Auto-checks (requires inspector name) ─────────────────────
    st.subheader('Auto-Checks')
    if not inspector_valid:
        st.caption('Enter inspector name above to run auto-checks.')
    if st.button('Run Auto-Checks', disabled=not inspector_valid):
        with st.spinner('Running checks...'):
            result = svc['verifier'].run_auto_checks(nguoi_kiem_tra=inspector.strip())
        st.success(f"Passed: {result['passed']}  Failed: {result['failed']}")

    st.divider()

    # ── Section C: Manual review ──────────────────────────────────────────────
    st.subheader('Manual Review')
    from src.models.eform_models import Segment as _VFSeg, VerificationLog
    from src.utils.text import normalize as _vf_norm

    with svc['repo'].session_scope() as session:
        _vf_province_opts = svc['repo'].get_distinct_tinh_thanh(session)
    _vf_prov = st.selectbox('Province', ['All provinces'] + _vf_province_opts, key='vf_prov')
    _vf_sel_prov = None if _vf_prov == 'All provinces' else _vf_prov

    with svc['repo'].session_scope() as session:
        _vf_ward_opts = svc['repo'].get_distinct_xa_phuong(session, tinh_thanh=_vf_sel_prov)
    _vf_ward = st.selectbox('Ward / Zone', ['All wards'] + _vf_ward_opts, key='vf_ward')
    _vf_sel_ward = None if _vf_ward == 'All wards' else _vf_ward

    with svc['repo'].session_scope() as session:
        _vf_q = session.query(_VFSeg).filter(
            _VFSeg.is_active == True,
            _VFSeg.trang_thai.in_(['Đủ vị trí', 'Hoàn thành', 'Dữ liệu sai hoặc lỗi'])
        )
        if _vf_sel_prov:
            _vf_q = _vf_q.filter(_VFSeg.tinh_thanh_norm == _vf_norm(_vf_sel_prov))
        if _vf_sel_ward:
            _vf_q = _vf_q.filter(_VFSeg.xa_phuong_norm == _vf_norm(_vf_sel_ward))
        _vf_segs = _vf_q.order_by(_VFSeg.ten_duong, _VFSeg.doan).all()
        _vf_seg_opts = {
            s.id: (
                (f"{s.tinh_thanh} / " if not _vf_sel_prov else '')
                + (f"{s.xa_phuong} / " if not _vf_sel_ward else '')
                + f"{s.ten_duong or ''}"
                + (f" / {s.doan}" if s.doan else '')
                + f"  ({s.trang_thai})"
            ).strip(' /')
            for s in _vf_segs
        }

    if not _vf_seg_opts:
        st.info('No reviewable segments in this filter.')
    else:
        _vf_chosen_id = st.selectbox(
            'Segment', options=list(_vf_seg_opts.keys()),
            format_func=lambda x: _vf_seg_opts[x], key='vf_seg'
        )

        with svc['repo'].session_scope() as session:
            _vf_seg = svc['repo'].get_segment_by_id(session, _vf_chosen_id)
            _vf_records = svc['repo'].get_collected_records_for_segment(session, _vf_chosen_id)
            _vf_so_can = {
                vt: req for vt, req in [
                    (1, _vf_seg.so_can_vt1), (2, _vf_seg.so_can_vt2),
                    (3, _vf_seg.so_can_vt3), (4, _vf_seg.so_can_vt4),
                ] if req is not None
            }

        _vf_active = [r for r in _vf_records if r['is_active']]
        _vf_inactive = [r for r in _vf_records if not r['is_active']]

        _vf_vt_active: dict[int, int] = {}
        for r in _vf_active:
            vt = r['vi_tri']
            _vf_vt_active[vt] = _vf_vt_active.get(vt, 0) + 1
        _vf_con_thieu = sum(
            max(0, need - _vf_vt_active.get(vt, 0))
            for vt, need in _vf_so_can.items()
        )

        vc1, vc2, vc3, vc4 = st.columns(4)
        vc1.metric('Active', len(_vf_active))
        vc2.metric('Soft-deleted', len(_vf_inactive))
        vc3.metric('Still needed', _vf_con_thieu)
        vc4.metric('Total', len(_vf_records))

        if _vf_so_can:
            _vf_parts = [
                f"vt{vt}: {_vf_vt_active.get(vt, 0)}/{need}"
                for vt, need in sorted(_vf_so_can.items())
            ]
            st.caption('Số lượng theo vị trí — ' + '  |  '.join(_vf_parts))
        if _vf_inactive:
            st.caption(f"⚠ {len(_vf_inactive)} record(s) soft-deleted (not counted)")

        if _vf_records:
            import pandas as pd
            _vf_tbl = [{k: v for k, v in r.items() if k != 'raw_data'} for r in _vf_records]
            st.dataframe(pd.DataFrame(_vf_tbl), hide_index=True)
            with st.expander('Raw data (JSON)'):
                for r in _vf_records:
                    _vf_del_tag = ' *(deleted)*' if not r['is_active'] else ''
                    st.markdown(f"**{r['source_record_id']}**{_vf_del_tag}")
                    st.json(r['raw_data'])
        else:
            st.info('No records for this segment.')

        _vf_outcome = st.radio(
            'Review outcome',
            ['pass — Hoàn thành', 'fail — Dữ liệu sai hoặc lỗi'],
            key='vf_outcome', horizontal=True,
        )
        _vf_outcome_key = 'pass' if _vf_outcome.startswith('pass') else 'fail'
        _vf_notes = st.text_area(
            'Notes' + (' (required for fail)' if _vf_outcome_key == 'fail' else ''),
            key='vf_notes', height=80,
        )

        if not inspector_valid:
            st.caption('Enter inspector name above before saving.')
        if st.button('Save Review', disabled=not inspector_valid):
            try:
                svc['verifier'].save_manual_finding(
                    segment_id=_vf_chosen_id,
                    nguoi_kiem_tra=inspector.strip(),
                    finding_text=_vf_notes,
                    outcome=_vf_outcome_key,
                )
                st.session_state['vf_flash'] = True
                st.session_state['vf_flash_msg'] = (
                    f"Review saved for segment {_vf_chosen_id} — {_vf_outcome_key.upper()}."
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.divider()

    # ── Section D: Verification log ───────────────────────────────────────────
    st.subheader('Verification Log')
    _vf_log_filter = st.radio(
        'Show', ['All', 'auto only', 'manual only'], horizontal=True, key='vf_log_filter'
    )
    with svc['repo'].session_scope() as session:
        _vf_lq = session.query(VerificationLog).order_by(VerificationLog.verified_at.desc())
        if _vf_log_filter == 'auto only':
            _vf_lq = _vf_lq.filter(VerificationLog.loai_kiem_tra == 'auto')
        elif _vf_log_filter == 'manual only':
            _vf_lq = _vf_lq.filter(VerificationLog.loai_kiem_tra == 'manual')
        _vf_logs = _vf_lq.limit(200).all()
        _vf_rows = [{
            'id': l.id,
            'segment_id': l.segment_id,
            'type': l.loai_kiem_tra,
            'inspector': l.nguoi_kiem_tra,
            'result': l.ket_qua,
            'at': str(l.verified_at),
        } for l in _vf_logs]
    if _vf_rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(_vf_rows))
    else:
        st.info('No verification records yet.')
