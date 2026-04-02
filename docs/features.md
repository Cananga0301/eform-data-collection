# E-Form Data Collection Feature Guide

This document explains the current features of the E-Form Data Collection project from a system-behavior and operations perspective. It is intended to be code-accurate to the current repository and to distinguish between fully implemented behavior, partial behavior, and placeholder scaffolding.

For the practical page-by-page operator guide, see [workflow.md](workflow.md).

## Overview

This app is the management backend for the e-form road-data collection process across HCM, Ha Noi, and Dong Nai. It helps the team:

- import the master route Excel files
- classify each road segment into A/B/C groups
- let Head Office (HO) review and override classifications
- map segments to branches and assign responsible people
- pull collected records from the external collection system or local test fixtures
- resolve unmatched records manually
- monitor progress through dashboards and Excel reports
- verify whether collected data is sufficient and structurally valid

The current end-to-end operational flow is:

1. Import route files and classify segments.
2. Review and manually adjust segment groups (A/B/C) in the HO Review page.
3. Maintain branch mappings and export assignment files.
4. Re-import assignment ownership and deadlines.
5. Run sync from the external collection system or a local JSON fixture.
6. Resolve unmapped records when needed.
7. Monitor progress in the dashboard and downloadable reports.
8. Run verification checks automatically after sync / resolve and manually through Page 9 when inspector review is needed.

## Current Status

- Streamlit is the primary user-facing application.
- Flask exists mainly as a lightweight service shell and health-check endpoint.
- PostgreSQL is the system of record for segments, assignments, collected records, sync state, unmapped records, and verification logs.
- The real external collection API is not integrated yet.
- The default sync client is still a stub, but local JSON fixture support exists through `FileCollectionClient`.
- Automatic verification is now wired into sync and unmapped-record resolution for eligible segments.
- Manual inspector review is implemented on Page 9 and can clear or set error status.

## T1 - Import And Classify

### What it does

The importer reads the 3 route Excel files and stores each row as a segment in the `segments` table. Each segment includes:

- original display values such as `tinh_thanh`, `xa_phuong`, `ten_duong`, and `doan`
- a derived `doan_key` (`doan` if present, otherwise `ten_duong`)
- normalized key fields used for matching
- state land price columns `vt1` to `vt4`
- required collection counts `so_can_vt1` to `so_can_vt4`
- the A/B/C priority group `nhom`
- branch defaults when branch mappings are available
- active/inactive state for master-file refreshes

### Position handling

The number of positions is derived from the Excel file itself, not hardcoded by province:

- if `vt1` exists, position 1 exists
- if `vt2` is blank, position 2 does not exist
- if `vt3` is blank, position 3 does not exist
- if `vt4` is blank, position 4 does not exist

Each existing position requires 3 records, so:

- one-position segment -> 3 required records
- four-position segment -> 12 required records

### Classification

Classification is based on `vt1` price.

Thresholds come from `config.py` and are currently global price bands:

- group `A`: `vt1 <= 100,000,000`
- group `B`: `100,000,000 < vt1 <= 200,000,000`
- group `C`: `vt1 > 200,000,000`

If `vt1` is missing, the classifier currently falls back to group `C`.

If a segment has already been manually overridden by HO, the importer preserves that manual value by honoring `nhom_manual = true`.

### Import validation behavior

The importer validates `vt1` to `vt4` before writing rows for a file. It supports Vietnamese-style VND price formats such as:

- `96.249.000`
- `96,249,000`
- `96 249 000`
- whole-number Excel artifacts such as `96249000.0`

It also treats common source placeholders such as `-` as empty values, which means "this position has no price / does not exist".

If a non-empty `vt` cell cannot be parsed, that file import fails and Streamlit shows a per-file error message. Other files in the same upload batch can still succeed.

### Re-import behavior

On master Excel re-import:

- matching is done by normalized route key
- existing segments are updated in place
- display fields are refreshed from the latest source file
- manual `nhom` overrides are preserved
- assignments are not reset by the importer
- rows missing from the new master file are marked `is_active = false`
- previously inactive rows are reactivated if they appear again later

### Performance characteristics

The importer includes the optimized import path. Instead of doing several database queries per row, it:

- bulk-loads all existing segments for the province into memory
- bulk-loads all branch mappings into memory
- uses normalized in-memory dictionary lookups during the row loop
- uses a single flush at the end of the file import
- deactivates missing segments in bulk

This is designed for the current large master dataset.

## HO Review / Group Override

### What it does

This page lets Head Office staff review and manually assign the A/B/C group for any active segment, filtered to a specific province and ward / zone.

### Current implementation

The page uses an in-page editable table with:

- province and ward / zone filters
- explicit **Load Segments** action
- inline `Nhom` editing
- row selection checkboxes
- **Select all** / **Deselect all**
- bulk apply via **Set all selected rows to:**
- **Save Changes**
- filtered Excel export

### Persistence behavior

On save:

- only rows whose `nhom` value actually changed are updated
- changed rows are marked `nhom_manual = true`
- other segment fields are not modified

The current implementation intentionally keeps a stable base table in Streamlit session state and does not feed the live `data_editor` output back into its own base key. This avoids the rerun/checkbox instability that older Streamlit patterns can cause.

### Export behavior

The page can export all active segments in the current province / ward filter to Excel for offline reference. This export is not designed to be re-imported as a data-edit source.

## Branch Mapping

### What it does

Branch Mapping defines which branch is responsible for collecting each segment. It operates on two levels:

- province level (`tinh_thanh`): assigns a branch to all segments in a province that do not have a ward-level override
- ward level (`xa_phuong`): assigns a branch to all segments in a specific ward, taking priority over the province rule

### Current implementation

The page supports:

- listing current branch names
- creating a branch
- creating or updating a mapping rule

Saving a mapping does two things:

1. Writes or updates the mapping rule in the database.
2. Immediately applies that mapping to all currently active matching segments whose `branch_id` is null or different.

Ward-level mappings always take priority over province-level mappings when both could apply to the same segment.

### Current UI limits

The page does not yet provide edit/delete management screens for existing mappings beyond overwriting a rule by saving the same key again.

## T2 - Assignment Files

### What it does

Assignments define who is responsible for collecting a segment and by when. This workflow is used to distribute work to branches or field teams.

### Export

The assignment export produces an Excel file filtered by province and / or ward-zone. Each row represents one segment and includes:

- `segment_id`
- route and segment text
- group `nhom`
- `vt1` to `vt4`
- `so_can_vt1` to `so_can_vt4`
- branch name
- `phu_trach`
- `deadline`

The `segment_id` column is the preferred key for re-import because it is the safest and most stable identifier.

### Re-import

The assignment re-import updates the `assignments` table. Matching behavior is:

- primary key: `segment_id`
- fallback: normalized text key if the ID is missing

The code updates assignment fields in place instead of recreating assignments from scratch. Assignments survive master Excel re-imports.

If the assignment file contains a branch name that does not already exist in the branch list, the importer auto-creates that branch and uses it as the assignment override.

### Branch defaults vs branch overrides

There are two branch layers:

- `segments.branch_id`: the default branch from branch mapping rules
- `assignments.branch_id`: a per-assignment override from the assignment file

That means a segment can have a default office / team while the assignment file can still override who owns that segment operationally.

## T3 - Sync From API

### What it is supposed to do

The sync process is designed to pull newly collected records from the external collection application into local PostgreSQL.

It is intentionally implemented as a standalone script in `sync.py`, not inside Flask/Gunicorn, so scheduled sync can run safely from cron or Task Scheduler without multi-worker duplication.

### Current implementation

The sync subsystem now has these implemented local pieces:

- `sync.py` as the standalone entry point
- `source_record_id` as the dedup key
- `sync_log` for per-run audit counts
- `sync_cursor` for incremental state
- `collected_records` for mapped records
- `unmapped_records` for records that could not be matched
- automatic post-sync verification for eligible affected segments

The real external API client is still not built. Current client options are:

- `StubCollectionClient`: default behavior, returns no records
- `FileCollectionClient`: serves records from a local JSON file for testing

`FileCollectionClient` can be used:

- from Streamlit Page 5 through the `Use test fixture (test_collected_records.json)` toggle
- from `sync.py` by setting `TEST_RECORDS_FILE`

### Matching and storage model

When records are processed, the sync layer stores:

- the upstream source ID
- the mapped `segment_id` if found
- the collected `vi_tri`
- the raw upstream payload in JSON
- `first_seen_at` for velocity and reporting
- `last_synced_at` for later re-sync updates

Unmatched records are written to `unmapped_records` so they can be reviewed manually instead of being discarded.

### Segment status recalculation

After inserts, updates, deletes, or replayed unmapped resolutions, sync recalculates segment status from active collected counts:

- `Chưa bắt đầu`
- `Đang thu thập`
- `Đủ vị trí`
- `Hoàn thành`

If sync detects quick structural problems after quantity is complete, it leaves the segment at `Đủ vị trí` for manual review rather than auto-marking it complete.

If a segment is already in `Dữ liệu sai hoặc lỗi`, sync does not auto-clear that state. Only T5 manual review can clear it.

### Automatic verification after sync and replay

Auto-verification runs automatically in three operational paths:

- after `sync.py`
- after the Streamlit Page 5 **Run Sync Now** action
- after resolving an unmapped record on Page 7

The verifier is scoped to the affected segment IDs returned by sync or replay so it does not rescan every segment on every run.

### Current limits

- The real upstream API is still absent; default app behavior remains stubbed.
- Page 5 fixture mode is currently hardwired to `test_collected_records.json`.
- Auto-verification only checks eligible segments in `Đủ vị trí` or `Hoàn thành`.
- Touched segments that remain in `Chưa bắt đầu` or `Đang thu thập` are not written to `verification_log` by the auto-check path.

## T4 - Progress Reporting

### Dashboard metrics

The reporting service calculates 4 summary metrics for active segments:

- total records needed
- total records collected
- percent complete
- ETA

ETA is based on records first seen within the recent time window, not on later updates to old records.

### first_seen_at vs last_synced_at in reporting

Reporting intentionally uses `first_seen_at` for "new record" and velocity calculations. This avoids counting routine updates to an old record as if they were new collection progress.

### Dashboard status counts

The dashboard also calculates counts for 5 segment statuses:

- `Chưa bắt đầu`
- `Đang thu thập`
- `Đủ vị trí`
- `Dữ liệu sai hoặc lỗi`
- `Hoàn thành`

These are shown as separate cards in the current Streamlit dashboard.

### Dashboard sections

The current Streamlit **Progress Dashboard** page includes:

- province and ward / zone filters for the main dashboard scope
- the 4 top metrics
- 5 status cards
- a progress bar
- **Overview Breakdown**
- **Branch Activity**
- **White Zones**
- **Segment Record Detail**
- dashboard Excel export for the current filtered view

### Segment Record Detail

The current dashboard now includes a segment-level drill-down section with its own independent province / ward / segment cascade. It shows:

- the selected segment's status
- total required records
- active collected count
- remaining deficit
- per-position counts such as `vt1: 2/3`
- all linked collected records
- soft-deleted records for audit
- raw JSON payloads per record

This is the main in-app way to inspect exactly which records are attached to a segment.

### Dashboard Excel export

The dashboard export currently creates a 4-sheet workbook:

1. `Summary`
2. `Dashboard Overview`
3. `Branch Activity`
4. `White Zones`

It is scoped to the main dashboard filters on the page.

### Daily Excel report

The daily report generator still creates a separate 3-sheet workbook:

1. `Overview`
2. `White Zones`
3. `Unmapped Records`

This is exposed through the **Reports** page rather than the dashboard export button.

### Operational meaning of dashboard sections

`Collected` means the total number of active collected records attached to the filtered active segments. It is not limited to segments in `Đủ vị trí` or `Hoàn thành`; even a segment with only one synced record will increase this number.

`White Zones` focuses on active group `A` and `B` segments that are still incomplete and includes assignment ownership and deadline fields where available.

`Branch Activity` highlights branches with no recent new records in the configured recent window.

## T5 - Verification

### What it checks

The verifier currently supports structural checks such as:

- required quantity per position
- duplicate source record IDs within the same segment / position
- wrong-position data, such as a record attached to a `vi_tri` that does not exist on that segment

Verification results are written to `verification_log`.

### Log model

Verification logs now record both the reviewer name and the verification type:

- `loai_kiem_tra = 'auto'`
- `loai_kiem_tra = 'manual'`

This distinguishes system-driven checks from inspector-driven review actions.

### Automatic checks

Auto-checks run automatically in three places:

- after every sync run (`sync.py` and Streamlit Page 5), scoped to touched segments
- after resolving an unmapped record on Page 7, scoped to the affected segment
- from Page 9 when a human explicitly presses **Run Auto-Checks**

Page 9 requires an inspector name to run this manual trigger. Automatic background runs use `system` as the log author.

### Auto-check scope rules

Auto-checks only run on active segments currently in:

- `Đủ vị trí`
- `Hoàn thành`

Segments in `Dữ liệu sai hoặc lỗi` are intentionally excluded from auto-checks. Only manual inspector review can clear that state.

If an auto-check passes:

- the segment becomes `Hoàn thành`
- a verification log row is written with `type = auto`

If an auto-check fails:

- the segment becomes `Dữ liệu sai hoặc lỗi`
- a verification log row is written with `type = auto`

### Manual review workflow

The current Page 9 manual review workflow allows an inspector to:

- enter an inspector name
- filter reviewable segments by province and ward / zone
- inspect all linked records for a chosen segment
- see per-position counts and raw payloads
- record an outcome:
  - `pass` -> `Hoàn thành`
  - `fail` -> `Dữ liệu sai hoặc lỗi`

Manual review is allowed only when the segment is in one of these states:

- `Đủ vị trí`
- `Hoàn thành`
- `Dữ liệu sai hoặc lỗi`

Failing a segment through manual review requires non-empty notes.

Saving a manual review:

- updates `trang_thai`
- writes a `verification_log` row
- records the inspector name
- stores `loai_kiem_tra = 'manual'`

### Current limits

- Required-field verification is still not configured. The current checks are structural only.
- The verification log page shows recent rows only, not a full searchable audit browser.

## Main Streamlit Pages

The current app defines 9 Streamlit pages:

1. **Import & Classify**
   - upload route Excel files and run the importer
2. **HO Review / Group Override**
   - filter by province and ward / zone
   - edit segment groups (A/B/C) in-page with checkbox row selection and bulk apply
   - save changes directly to the database
   - export the current filtered view to Excel
3. **Branch Mapping**
   - create branches and add mapping rules
4. **Assignment Export / Import**
   - export assignment files and re-import filled ownership data
5. **Sync Status**
   - view last sync information
   - optionally use the JSON fixture
   - trigger sync manually
   - automatically verify affected eligible segments after sync
6. **Progress Dashboard**
   - view summary metrics and 5 status cards
   - inspect overview, branch activity, and white zones
   - drill into one segment's collected records
   - export the current dashboard view
7. **Unmapped Records**
   - inspect unresolved records
   - filter candidate segments by province and ward / zone
   - resolve unmatched records into a chosen segment
   - automatically verify the affected eligible segment after resolve
8. **Reports**
   - generate and download the daily 3-sheet Excel report
9. **Verification**
   - run inspector-authored auto-checks across all eligible segments
   - manually review a segment and save an outcome
   - inspect recent verification logs filtered by auto / manual type

For step-by-step page usage, see [workflow.md](workflow.md).

## Supporting Infrastructure

### Normalized matching

The app stores normalized `_norm` fields for route-matching keys. Normalization includes:

- trimming
- lowercasing
- collapsing repeated spaces
- stripping diacritics

This makes matching more resilient across Excel data and collection payloads.

### Segment lifecycle

Segments use `is_active` so the current active master route set can be separated from historical rows. A segment can be:

- active now
- deactivated because it disappeared from a re-imported master file
- reactivated later if the route returns

### Sync state and auditability

The app tracks sync state through:

- `sync_cursor` for incremental progress
- `sync_log` for run-level counts
- `source_record_id` for deduplication
- `verification_log` for verification history

### Timestamps

Collected records store two time concepts:

- `first_seen_at`: when the record first arrived locally
- `last_synced_at`: the last time that source record was refreshed during sync

### Flask, Docker, PostgreSQL, and Alembic

At a high level:

- PostgreSQL stores all operational data
- Alembic manages schema changes
- Docker Compose is the recommended local path for PostgreSQL
- Flask is a minimal service shell with health-check support
- Streamlit is the main operational UI

## Known Limitations And Partial Areas

- The real external collection API client is not implemented yet; default sync behavior still uses a stub client.
- Local fixture support exists, but the Streamlit Page 5 fixture toggle is currently hardwired to `test_collected_records.json`.
- Branch Mapping supports adding branches and saving mapping rules, but not deleting or managing existing mappings through a dedicated UI.
- Required-field verification is still undefined and therefore not enforced.
- Auto-verification is intentionally limited to `Đủ vị trí` and `Hoàn thành`; it is not a general audit pass across every possible segment state.
- The Verification page shows recent log rows only and does not yet provide a full history browser with advanced search.
