# CLAUDE.md — eform-data-collection

## What this project is
A Streamlit + Flask + PostgreSQL management tool for Vietnamese road-segment data collection. Head Office staff import route files, assign collection work to branches, track progress, and review group classifications. The Streamlit UI is the primary interface; Flask provides a thin REST layer.

## Commands

```bash
# Local dev (no Docker needed for Streamlit or tests)
poetry run streamlit run src/streamlit_app.py   # main UI (port 8501)
poetry run python app.py                        # Flask API (port 8000)
poetry run alembic upgrade head                 # apply DB migrations
poetry run pytest                               # run all tests locally

# Docker (Flask + PostgreSQL containerised)
make up-d                                       # start services (Flask exposed on host port 38001)
make test                                       # run tests inside the running container
make test-cov                                   # tests + coverage inside container
```

## Architecture

Three-layer stack: **Models → Repository → Services → UI/Controller**

```
src/
  models/eform_models.py         — SQLAlchemy 2.0 ORM (9 tables)
  repository/eform_repository.py — thin data access wrapper
  service/
    importer_service.py          — Excel import, normalisation, classification
    classifier_service.py        — A/B/C classification by vt1 price bands
    assigner_service.py          — assignment export / re-import
    syncer_service.py            — incremental sync (STUBBED — see below)
    reporter_service.py          — dashboard metrics, Excel reports
    verifier_service.py          — data quality auto-checks
  streamlit_app.py               — 9-page Streamlit UI (single file)
  controller/eform_controller.py — Flask routes
config.py                        — business constants (price thresholds, ETA window)
container.py                     — dependency-injector wiring for Flask only
```

**Two separate service-wiring paths:**
- **Streamlit** — services built directly inside `get_services()` and cached process-wide with `@st.cache_resource`. `container.py` is not involved.
- **Flask** — services wired via `container.py` (dependency-injector) and injected into the controller.

## Accessing services in Streamlit

```python
svc = get_services()   # @st.cache_resource singleton — always use this
svc['repo']            # EformRepository
svc['importer']        # ImporterService
svc['assigner']        # AssignerService
svc['reporter']        # ReporterService
svc['verifier']        # VerifierService
```

Never instantiate services directly in page code.

## Database access pattern

Always use the context manager — auto-commits on exit, rolls back on exception:

```python
with svc['repo'].session_scope() as session:
    segs = session.query(Segment).filter(Segment.is_active == True).all()
```

For bulk updates use `.filter(...).update({...}, synchronize_session=False)` to avoid N+1 queries. Use `filter(Model.id.in_(id_list))` to batch-fetch before looping.

## Normalisation — critical

All text matching goes through `normalize()`. Every candidate key stored in the DB is its normalised form. Forget this and nothing will match.

```python
from src.utils.text import normalize
# Strips diacritics via NFD decomposition + removes Unicode combining marks (category Mn).
# Lowercases and collapses whitespace.
# IMPORTANT: "đ" (D WITH STROKE, U+0111) has no NFD decomposition and is NOT transliterated.
# "Hà Nội"   → "ha noi"
# "Đường"    → "đuong"   (đ stays, accent stripped from ư)
# "Phường 1" → "phuong 1"
```

Normalised columns on Segment: `tinh_thanh_norm`, `xa_phuong_norm`, `ten_duong_norm`, `doan_key_norm`.
`key_value` on BranchMapping is also always a normalised string.

## Segment matching key — doan_key

Segments are matched by a derived key, not raw `doan`:

```
doan_key = doan if doan is not null else ten_duong
doan_key_norm = normalize(doan_key)
```

This matters in import (dedup against existing rows) and sync (matching collected records to segments). If you add matching logic, use `doan_key_norm`, not `doan`.

## Sync pipeline is stubbed

`SyncerService` is fully implemented locally but wired to `StubCollectionClient`, which returns no records. The real upstream API integration is not live. Do not treat `syncer_service.py` as a reference for production-quality API calls.

## Branch mapping priority

- `xa_phuong` (ward) beats `tinh_thanh` (province) — always.
- `apply_single_mapping()` in `ImporterService` enforces this: province-level mappings skip segments that already have a ward-level mapping.
- `reapply_all_branch_mappings()` does a full rebuild: clear all → apply province → apply ward override.

## Classification

`ClassifierService.classify(xa_phuong_norm, vt1) → 'A' | 'B' | 'C'`

Thresholds from `config.py`:

| Group | vt1 condition |
|-------|---------------|
| A | ≤ 100 000 000 VND |
| B | ≤ 200 000 000 VND |
| C | anything else |

`nhom_manual = True` means a human override — re-imports must not overwrite it.

## Streamlit session state conventions

Keys follow a page-prefix pattern:

| Prefix | Page |
|--------|------|
| `ho_*` | Page 2 — HO Review / Group Override |
| `bm_*` | Page 3 — Branch Mapping |

Key keys to know:

- `ho_segments_df` — **stable base** passed to `st.data_editor`; only updated by explicit actions (Load, Select All, Deselect All, Apply to selected, Save). **Never assign `edited_df` back into this key on a passive rerun** — doing so causes Streamlit to rebuild the widget's delta state, making checkboxes require two clicks.
- `ho_segments_edited` — mirror of the live `data_editor` output; written every rerun via `st.session_state['ho_segments_edited'] = edited_df`. Action buttons read from this to preserve in-editor changes.
- `ho_segments_original` — snapshot at load time; Save diffs against this to find changed rows.
- `ho_editor_version` — int suffix on the `data_editor` key; increment to force a full widget rebuild (after Select All, Save, etc.).
- `bm_saved` — flash-message flag; set before `st.rerun()`, displayed and deleted on the next render.

## Streamlit rerun pitfalls

- **Do not use `st.checkbox` + compare-prev-value** to trigger side effects. The comparison fires on every rerun, not just on click. Use `st.button` instead.
- **Do not write the data_editor's output back into the same session state key used as its base** (the `ho_segments_df` / `ho_segments_edited` split above). If the base changes every rerun, the widget's delta state conflicts and first clicks are silently ignored.
- `st.success()` before `st.rerun()` is never seen by the user. Store the message in session state, display it on the next render, then delete the key.

## Domain vocabulary

| Vietnamese term | Meaning |
|-----------------|---------|
| `tinh_thanh` | Province |
| `xa_phuong` | Ward / zone |
| `ten_duong` | Street name |
| `doan` | Segment descriptor (can be null — use `doan_key`) |
| `nhom` | Group: A / B / C |
| `nhom_manual` | Human override flag — preserved on re-import |
| `vt1`–`vt4` | State land prices at positions 1–4 |
| `so_can_vtX` | Required sample count at that position (3 if vtX not null, else null) |
| `trang_thai` | Status string (see values below) |
| `phu_trach` | Person in charge |
| `vi_tri` | Position (1–4) in a collected record |

`trang_thai` values: `'Chưa bắt đầu'` · `'Đang thu thập'` · `'Đủ vị trí'` · `'Dữ liệu sai hoặc lỗi'` · `'Hoàn thành'`

## Key models

- **Segment** — core entity; `is_active` is the soft-delete flag.
- **BranchMapping** — unique on `(key_type, key_value)`; `key_value` is always a normalised string.
- **Assignment** — one-to-one with Segment (`segment_id` unique); survives master-file re-imports.
- **CollectedRecord** — `source_record_id` is the dedup key from the external API; `first_seen_at` never changes.
- **SyncCursor** — single-row table used for incremental sync state; never truncate it.

## Configuration

- Business constants (thresholds, ETA window, alert days): `config.py` at project root.
- DB connection: `src/config/env/dev.ini` for local dev; `prod.ini` uses env var placeholders.
- Key env vars: `FLASK_ENV` (default `'dev'`), `POSTGRESQL_HOST/PORT/DATABASE/USER/PASS`.

## Testing

```bash
# Local (no Docker required)
poetry run pytest                  # all tests

# Inside Docker (requires make up-d first)
make test                          # all tests in container
make test-cov                      # tests + coverage in container
```

Unit tests (`tests/unit/`): assigner, classifier, importer, text normalisation.
Integration tests (`tests/integration/`): importer_service against a real temporary PostgreSQL instance (via pytest-postgresql). No DB mocking.
