# E-Form Data Collection Feature Guide

This document explains the current features of the E-Form Data Collection project from a workflow and operations perspective. It is code-accurate to the current repository and intentionally distinguishes between fully implemented behavior, partial behavior, and placeholder scaffolding.

## Overview

This app is the management backend for the e-form road-data collection process across HCM, Ha Noi, and Dong Nai. It helps the team:

- import the master route Excel files
- classify each road segment into A/B/C groups
- let Head Office (HO) review and override classifications
- map segments to branches and assign responsible people
- pull collected records from the external collection app
- resolve unmatched records manually
- monitor progress through dashboards and Excel reports
- verify whether collected data is sufficient and structurally valid

The end-to-end workflow is:

1. Import route files and classify segments.
2. Review and manually adjust segment groups (A/B/C) in the HO Review page using the in-page editor.
3. Maintain branch mappings and export assignment files.
4. Re-import assignment ownership and deadlines.
5. Run sync from the external collection system.
6. Resolve unmapped records when needed.
7. Monitor progress in the dashboard and reports.
8. Run verification checks and review verification history.

## Current Status

- Streamlit is the primary user-facing application.
- Flask exists mainly as a lightweight service shell and health-check endpoint.
- PostgreSQL is the system of record for segments, assignments, collected records, sync state, and verification logs.
- The external collection API is not integrated yet; the current sync client is a stub.
- Several workflows are already useful in practice, but some planned capabilities are still partial or not yet wired end-to-end.

## T1 - Import And Classify

### What it does

The importer reads the 3 route Excel files and stores each row as a segment in the `segments` table. Each segment includes:

- original display values such as `tinh_thanh`, `xa_phuong`, `ten_duong`, and `doan`
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

Classification is based on:

- `vt1` price

Thresholds come from `config.py` and are currently global price bands:

- group `A`: `vt1 <= 100,000,000`
- group `B`: `100,000,000 < vt1 <= 200,000,000`
- group `C`: `vt1 > 200,000,000`

If `vt1` is missing, the current classifier falls back to group `C`.

If a segment has already been manually overridden by HO, the importer preserves that manual value by honoring `nhom_manual = true`.

### HO review

HO can review and override segment group assignments directly in the app without touching any Excel file. Manually set values are flagged with `nhom_manual = true` so later master-file re-imports do not overwrite them. An Excel export of the current filtered view is available for offline reference.

### Current import performance

The importer currently includes the optimized import path. Instead of doing several database queries per row, it now:

- bulk-loads all existing segments for the province into memory
- bulk-loads all branch mappings into memory
- uses normalized in-memory dictionary lookups during the row loop
- uses a single flush at the end of the file import
- deactivates missing segments in bulk

This is significantly faster than the earlier row-by-row database lookup approach and is designed for the ~46k-row master dataset.

### Current import validation behavior

The importer now validates `vt1` to `vt4` before writing any rows for a file. It supports Vietnamese-style VND price formats such as:

- `96.249.000`
- `96,249,000`
- `96 249 000`
- whole-number Excel artifacts such as `96249000.0`

It also treats common source placeholders such as `-` as empty values, which means "this position has no price / does not exist".

If a non-empty `vt` cell still cannot be parsed, that file import fails and Streamlit shows a per-file error message with example rows and columns. Other files in the same upload batch can still succeed.

### Re-import behavior

On master Excel re-import:

- matching is done by normalized route key
- existing segments are updated in place
- display fields are refreshed from the latest source file
- manual `nhom` overrides are preserved
- assignments are not reset by the importer
- rows missing from the new master file are marked `is_active = false`
- previously inactive rows are reactivated if they appear again later

## HO Review / Group Override

### What it does

This page lets Head Office staff review and manually assign the A/B/C group for any segment, filtered to a specific province and ward/zone.

### Workflow

1. Select a province from the province dropdown.
2. Select a ward/zone from the ward dropdown (populated from the selected province).
3. Click **Load Segments** — the table shows all active segments for that province/ward pair.
4. Edit the **Nhom** column inline for any row (A, B, or C).
5. Use the **Select all** / **Deselect all** buttons to tick rows in bulk.
6. Use the **Set all selected rows to:** dropdown and **Apply to selected** button to apply one group value to all ticked rows.
7. Click **Save Changes** to persist to the database. Changed rows are marked `nhom_manual = true`.

### Table columns

| Column | Description |
|--------|-------------|
| ✓ | Row selection checkbox for bulk apply |
| ID | Internal segment ID (read-only) |
| Road | Street name (read-only) |
| Segment | Segment descriptor (read-only) |
| VT1 Price | State land price for position 1 (read-only) |
| Nhom | A/B/C group — editable inline |
| Manual? | True if this row was previously saved manually (read-only) |

Province and ward are not shown as columns because they are already chosen by the filter.

### Export HO Review Excel

A separate **Export HO Review Excel** button (below the table) exports all active segments matching the current province/ward filter to an Excel file. The export includes segment ID, province, ward, road, segment, nhom, VT1, and the manual flag. This file is for offline reference only; changes to it are not re-imported.

---

## Branch Mapping

### What it does

Branch Mapping defines which branch is responsible for collecting each segment. It operates on two levels:

- **Province level (`tinh_thanh`)**: assigns a branch to all segments in a province that do not have a ward-level override
- **Ward level (`xa_phuong`)**: assigns a branch to all segments in a specific ward, taking priority over the province rule

### Adding a branch

Type a name in the **New branch name** field and submit. A new branch is created immediately.

### Adding a mapping

1. Choose the **Key type** — `xa_phuong` (ward) or `tinh_thanh` (province).
2. Choose the **Key value** from the dropdown — the list shows all known wards or provinces from imported segments.
3. Choose the **Map to branch** from the branch dropdown.
4. Click **Save Mapping**.

### What happens on Save

Saving a mapping does two things:

1. Writes the mapping rule to the database.
2. Immediately applies the rule to all currently active matching segments whose `branch_id` is null or different — so existing imported data is updated without requiring a re-import. The confirmation message shows how many segments were affected.

Ward-level mappings always take priority over province-level mappings when both could apply to the same segment.

---

## T2 - Assignment Files

### What it does

Assignments define who is responsible for collecting a segment and by when. This workflow is used to distribute work to branches or field teams.

### Export

The assignment export produces an Excel file filtered by province and/or ward-zone. Each row represents one segment and includes:

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

The current code updates assignment fields in place instead of recreating assignments from scratch. The intended behavior today is that assignments survive master Excel re-imports.

If the assignment file contains a branch name that does not already exist in the branch list, the importer currently auto-creates that branch and uses it as the assignment override.

### Branch defaults vs branch overrides

There are two branch layers:

- `segments.branch_id`: the default branch from branch mapping rules
- `assignments.branch_id`: a per-assignment override from the assignment file

That means a segment can have a default office/team, while the assignment file can still override who owns that segment operationally.

## T3 - Sync From API

### What it is supposed to do

The sync process is designed to pull newly collected records from the external collection application into local PostgreSQL.

It is intentionally implemented as a standalone script in `sync.py`, not inside Flask/Gunicorn, so scheduled sync can run safely from cron or Task Scheduler without multi-worker duplication.

### Current implementation

The sync subsystem already has the main local model and workflow pieces:

- `sync.py` as the standalone entry point
- `source_record_id` as the dedup key
- `sync_log` for per-run audit counts
- `sync_cursor` for incremental state
- `collected_records` for mapped records
- `unmapped_records` for records that could not be matched

However, the external API client is still a stub. The current `StubCollectionClient` returns no records, so the real upstream integration is not live yet.

### Matching and storage model

When real records are available, the design stores:

- the upstream source ID
- the mapped `segment_id` if found
- the collected `vi_tri`
- the raw upstream payload in JSON
- `first_seen_at` for velocity and reporting
- `last_synced_at` for later resync updates

Unmatched records are written to `unmapped_records` so they can be reviewed manually instead of being discarded.

### Manual sync in Streamlit

The Streamlit "Sync Status" page currently lets a user:

- see the last sync cursor state
- see the last sync counts
- manually trigger the sync service

Because the real API client is still stubbed, this is currently more of an operational shell than a full production sync flow.

### Unmapped replay

The Streamlit "Unmapped Records" page supports manual replay:

- inspect unresolved records
- choose the correct segment from a dropdown
- resolve the record into `collected_records`
- mark the unmapped row as resolved
- recalculate the segment status

This is useful for operational cleanup once real sync traffic exists.

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

### Daily Excel report

The report generator creates a 3-sheet Excel file:

1. **Overview**
   - grouped by province, branch, and group
   - shows needed, collected, percent complete, and recent new counts
   - highlights branch rows with no recent new records
2. **White Zones**
   - focuses on active `A` and `B` segments that still need more records
   - includes shortage count and assignment ownership
3. **Unmapped Records**
   - lists unresolved unmatched records for manual action

### Current Streamlit dashboard status

The Streamlit "Progress Dashboard" page now includes:

- province and ward/zone filter dropdowns (the metrics and tables below all respond to the selected filter)
- the 4 top metrics
- a separate card for `Số đoạn đường chưa bắt đầu`
- a separate card for `Số đoạn đường đang thu thập`
- an overall progress bar
- an overview breakdown grouped by province, branch, and group
- a branch activity table with recent-activity alerts
- a white-zone table for incomplete A/B segments
- an export button for the current filtered dashboard view

### What each dashboard section means

**Top metrics**

These 4 cards answer the highest-level management questions:

- how many records are needed in the current filter
- how many have been collected
- what percent is complete
- when the current workload is likely to finish if recent collection speed continues

`Collected` here means the total number of active collected records attached to the filtered segments. It is not limited to segments in `Đủ vị trí` or `Hoàn thành`; even a segment that only has one synced record will increase this number.

**Segment status cards**

The dashboard also shows two extra cards for segment workload:

- `Số đoạn đường chưa bắt đầu`
- `Số đoạn đường đang thu thập`

These count segments, not records:

- `Số đoạn đường chưa bắt đầu` means active segments with required positions but zero collected records so far
- `Số đoạn đường đang thu thập` means active segments that already have some collected records, but still do not have enough records to satisfy all required positions

They are meant to make the current workload easier to read without interpreting raw status names.

**Progress bar**

This is a quick visual representation of `% Complete`. It does not add new math, but it makes it easier to scan overall progress without reading the numeric percentage first.

**Overview breakdown**

This table groups progress by:

- province
- branch
- A/B/C group

For each grouped row it shows:

- needed
- collected
- missing
- percent complete
- new records in the recent alert window

This is the main operational breakdown for understanding where progress is strong or weak.

**Branch activity**

This table rolls the data up one level higher to branch level. It shows:

- how many segments the branch currently owns in the filtered view
- needed / collected / missing totals
- percent complete
- how many new records appeared recently
- whether the branch is currently flagged for no recent activity

This is meant to surface stalled branches quickly.

**White zones**

This table focuses only on active group `A` and `B` segments that are still incomplete. It includes:

- location and road info
- branch
- responsible person
- deadline
- current status
- missing record count

This is the most action-oriented section of the dashboard because it highlights high-priority incomplete work.

**Export current filtered dashboard view**

The dashboard can export the currently filtered view to Excel. The export is based on the same filters the user selected on the page and includes:

- summary metrics and status counts
- grouped overview rows
- branch activity rows
- white-zone detail rows

This is useful when someone wants the dashboard view in a shareable file without switching to the separate report-generation page.

## Verification

### What it checks

The verifier currently supports structural checks such as:

- required quantity per position
- duplicate source record IDs
- wrong-position data, such as a record attached to a position that does not exist on that segment

Verification results are written to `verification_log`.

### Current trigger behavior

The verification page provides a manual "Run Auto-Checks" action in the Streamlit UI. This is the current operational entry point.

### Current limitation

The overall design expects segments to move from `Du vi tri` to `Hoan thanh` after verification passes, but that transition is not fully automatic from the sync flow yet. The current code still relies on the verification page trigger rather than a fully automatic post-sync completion path.

## Main Streamlit Pages

The current app defines 9 Streamlit pages:

1. **Import & Classify**
   - upload route Excel files and run the importer
2. **HO Review / Group Override**
   - filter by province and ward/zone
   - edit segment groups (A/B/C) in-page with checkbox row selection and bulk apply
   - save changes directly to the database; changed rows are flagged as manual overrides
   - export the current filtered view to Excel for offline reference
3. **Branch Mapping**
   - create branches and add mapping rules
4. **Assignment Export / Import**
   - export assignment files and re-import filled ownership data
5. **Sync Status**
   - view last sync information and trigger sync manually
6. **Progress Dashboard**
   - view summary metrics
7. **Unmapped Records**
   - inspect and resolve unmatched records
8. **Reports**
   - generate and download the 3-sheet Excel report
9. **Verification**
   - run checks and inspect recent verification logs

Several of these pages are already operational, but some are still basic admin/ops screens rather than polished end-user workflows.

## Supporting Infrastructure

### Normalized matching

The app stores normalized `_norm` fields for route-matching keys. Normalization includes:

- trimming
- lowercasing
- collapsing repeated spaces
- stripping diacritics

This makes matching more resilient across Excel data and future API payloads.

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

### Timestamps

Collected records store two time concepts:

- `first_seen_at`: when the record first arrived locally
- `last_synced_at`: the last time that source record was refreshed during sync

### Docker, PostgreSQL, and Alembic

At a high level:

- PostgreSQL stores all operational data
- Alembic manages schema changes
- Docker Compose is the recommended local path for PostgreSQL
- Flask and Streamlit are commonly run from the host with Poetry in local development

## Known Limitations And Partial Areas

- The real external collection API client is not implemented yet; sync currently uses a stub client.
- The Flask API surface is minimal and not a full backend API yet.
- The Streamlit dashboard page is lighter than the reporting service behind it.
- The Branch Mapping page supports adding branches and mapping rules with automatic segment assignment on save, but does not yet support editing or deleting existing mappings from the UI.
- Some planned verification/completion behavior is not yet fully wired end-to-end from sync through automatic completion.
- The sync cursor stores both timestamp and record ID, but the boundary-handling logic is still not fully robust for same-timestamp edge cases.

## How To Read This Guide

Use this document as the feature overview for the current codebase. Use `README.md` for setup, environment, and run commands. If the code and older task/planning notes disagree, prefer the code and this guide.
