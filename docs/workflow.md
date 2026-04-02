# E-Form Data Collection Workflow Guide

This document is the practical operator guide for the current Streamlit app. It explains what each page is for, what a user can do there, how to do it, and what happens after each action.

Use this together with [features.md](features.md):

- `features.md` explains system behavior and feature rules.
- `workflow.md` explains how a user works through the app page by page.

This guide covers the 9 Streamlit pages only. The Flask API is not a user workflow surface, except for the support-only health check at `/api/health-check`. Automatic or background workflows are mentioned only where they affect what a user sees on a page.

## Quick Navigation

1. Import & Classify
2. HO Review / Group Override
3. Branch Mapping
4. Assignment Export / Import
5. Sync Status
6. Progress Dashboard
7. Unmapped Records
8. Reports
9. Verification

## Import & Classify

### What this page is for

This page imports the master route Excel files and creates or updates the `segments` data used by the rest of the app.

### What you can do here

- Upload 1 to 3 Excel files.
- Run the import for all uploaded files in one batch.
- Review per-file success or failure results.

### Main workflows

1. Click **Upload Excel files** and choose one or more `.xlsx` files.
2. Click **Run Import**.
3. Wait for the importer to process each file.
4. Review the results table and any error messages shown below it.

### What happens after each action

- After you upload files, nothing is written yet. The files are only staged in the browser session.
- After you click **Run Import**, the app saves each uploaded file to a temporary file, imports it, then deletes the temporary file.
- If a file imports successfully, its row in the results table shows `status = success` and includes the number of rows upserted and deactivated.
- If a file fails validation, its row shows `status = error` and the page displays the error details. Other files in the same batch can still succeed.
- If at least one file fails, the page shows a warning that the import finished with errors. If all files succeed, the page shows **Import complete.**

### Important notes / limits

- This page expects the route master files, not gathered-record JSON.
- Import validation is strict for `vt1` to `vt4`. A non-empty invalid price causes that file to fail.
- Re-import updates existing matching segments in place and can deactivate segments missing from the new master file.
- Manual HO group overrides are preserved during re-import.

## HO Review / Group Override

### What this page is for

This page lets Head Office review and manually override the `nhom` (`A` / `B` / `C`) of imported segments.

### What you can do here

- Filter active segments by province and ward / zone.
- Load the matching segments into an editable table.
- Edit `nhom` row by row.
- Select rows in bulk and apply a single `nhom` value to all selected rows.
- Save the changes back to the database.
- Export the current filtered HO view to Excel.

### Main workflows

1. Select a **Province**.
2. Select a **Ward / Zone**.
3. Click **Load Segments**.
4. Review the editable table.
5. Either:
   - edit the **Nhom** column directly, or
   - use **Select all** / **Deselect all**, choose a value in **Set all selected rows to:**, then click **Apply to selected**.
6. Click **Save Changes**.
7. If needed, click **Export HO Review Excel**, then click **Download**.

### What happens after each action

- After you select province and ward, nothing loads automatically. The table is only refreshed when you click **Load Segments**.
- After **Load Segments**, the page stores a stable base table in session state and shows only active segments for that province / ward pair.
- After **Select all**, **Deselect all**, or **Apply to selected**, the table rerenders with the updated selection or `nhom` values, but nothing is saved yet.
- After **Save Changes**, only rows whose `nhom` value actually changed are written to the database. Those rows are marked `nhom_manual = true`.
- After **Export HO Review Excel**, the workbook bytes are stored in session state. The **Download** button then appears and stays available until replaced by a later export.

### Important notes / limits

- You must choose both province and ward / zone before **Load Segments** is enabled.
- The table shows only the selected province / ward pair, so province and ward are not repeated as columns.
- Saving only updates `nhom` and the manual flag. It does not edit route text or prices.
- The export is for offline reference. Uploading that export back into the app is not part of this workflow.

## Branch Mapping

### What this page is for

This page manages branch ownership rules for segments.

### What you can do here

- View the current branch names.
- Add a new branch.
- Create or update a branch mapping by province (`tinh_thanh`) or ward (`xa_phuong`).

### Main workflows

1. To add a branch:
   1. Type a name into **New branch name**.
   2. Click **Add Branch**.
2. To add or update a mapping:
   1. Choose **Key type**: `xa_phuong` or `tinh_thanh`.
   2. Choose **Key value** from the dropdown.
   3. Choose **Map to branch**.
   4. Click **Save Mapping**.

### What happens after each action

- After **Add Branch**, the branch is created immediately, the page reruns, and the new branch becomes available in the mapping dropdown.
- After **Save Mapping**, the mapping rule is written or updated in the database.
- After saving the rule, the app immediately reapplies that single mapping to active segments that match it.
- On the next render, a flash message shows which mapping was saved and how many segments were updated.

### Important notes / limits

- Ward mappings override province mappings when both could apply.
- This page does not currently provide a delete UI for branches or mappings.
- Saving a mapping affects existing active segments immediately. You do not need to re-import the master files to see the branch update.

## Assignment Export / Import

### What this page is for

This page distributes collection work and re-imports filled assignment ownership data.

### What you can do here

- Export an assignment Excel file filtered by province and ward / zone.
- Re-import a filled assignment Excel file to update ownership, branch override, and deadline fields.

### Main workflows

1. In the **Export** column:
   1. Select **Province**.
   2. Select **Ward / Zone**.
   3. Click **Export Assignment Excel**.
   4. Click **Download** when the button appears.
2. In the **Re-import** column:
   1. Upload a filled `.xlsx` assignment file.
   2. Click **Import Assignments**.
   3. Read the `Updated` / `Skipped` summary.

### What happens after each action

- After **Export Assignment Excel**, the app generates an Excel workbook in memory and stores it in session state. The **Download** button then appears.
- After **Import Assignments**, the app updates matching assignments in place and shows how many rows were updated or skipped.
- If an assignment row includes a branch name that does not yet exist, the import can auto-create that branch and use it for the assignment override.

### Important notes / limits

- Export filters are optional. `All provinces` and `All wards` export the widest current scope.
- Re-import matches by `segment_id` first, then falls back to the normalized text key if needed.
- Assignment data survives master route re-imports.
- This page updates assignments, not the default mapping rules on segments.

## Sync Status

### What this page is for

This page shows the current sync state and lets a user trigger the sync manually.

### What you can do here

- View the last sync cursor timestamp.
- View the latest sync run counters.
- Choose whether to use the local JSON test fixture.
- Run sync manually.

### Main workflows

1. Review **Last synced at** and the most recent `received / mapped / unmapped` counts.
2. Optionally tick **Use test fixture (test_collected_records.json)**.
3. Click **Run Sync Now**.
4. Wait for the page to rerun with refreshed sync information.

### What happens after each action

- If fixture mode is off, the page uses the app's default sync client.
- If fixture mode is on, the page builds a `FileCollectionClient` from `test_collected_records.json` for that run only.
- After **Run Sync Now**, the sync service pulls records, updates mapped and unmapped data, and returns the set of affected segments.
- If any segments were affected, the verifier automatically runs scoped auto-checks for those segment IDs using inspector name `system`.
- The page then reruns, so the cursor and last-run counters refresh.

### Important notes / limits

- The default sync client is still a stub unless you use fixture mode here or set `TEST_RECORDS_FILE` for `sync.py`.
- Automatic post-sync verification only checks segments in `Đủ vị trí` or `Hoàn thành`.
- Segments already in `Dữ liệu sai hoặc lỗi` are not auto-cleared here.

## Progress Dashboard

### What this page is for

This page is the main read-only monitoring dashboard for collection progress.

### What you can do here

- Filter the dashboard by province and ward / zone.
- Read summary metrics, status cards, grouped tables, and white-zone rows.
- Drill into one segment's collected records.
- Export the current dashboard view to Excel.

### Main workflows

1. Select a **Province** and **Ward / Zone** in the main dashboard filters.
2. Read the top metrics and status cards.
3. Review:
   - **Overview Breakdown**
   - **Branch Activity**
   - **White Zones**
4. Use **Segment Record Detail** to inspect one segment:
   1. Select a province in the detail section.
   2. Select a ward / zone in the detail section.
   3. Select a segment.
   4. Review the metrics, per-position counts, record table, and raw JSON.
5. Click **Prepare Dashboard Export**, then click **Download Dashboard Excel**.

### What happens after each action

- After you change the main dashboard filters, the metrics and tables refresh immediately on rerun.
- The top metrics show `Total Needed`, `Collected`, `% Complete`, and `ETA`.
- The 5 status cards count segments in:
  - `Chưa bắt đầu`
  - `Đang thu thập`
  - `Đủ vị trí`
  - `Dữ liệu sai hoặc lỗi`
  - `Hoàn thành`
- In **Segment Record Detail**, the province / ward filters are independent from the main dashboard filters. Changing them only changes the drill-down section.
- After you choose a segment in the detail section, the page loads all collected records linked to that segment, including soft-deleted records.
- After **Prepare Dashboard Export**, the export bytes are stored in session state and the **Download Dashboard Excel** button appears.

### Important notes / limits

- The main dashboard filters and the segment-detail filters are separate on purpose.
- The segment-detail view shows soft-deleted records for audit, but only active records count toward `Đã thu thập`.
- The dashboard export uses the main dashboard filters, not the independent segment-detail filters.
- This page is read-only. You cannot edit records or statuses here.

## Unmapped Records

### What this page is for

This page handles gathered records that could not be matched to a segment during sync.

### What you can do here

- Review unresolved unmapped records.
- Inspect the raw payload and the reason it was not matched.
- Narrow the segment list by province and ward / zone.
- Resolve the record into the correct segment.

### Main workflows

1. Open one unresolved record in its expander.
2. Read the **Reason** and inspect the raw JSON payload.
3. Choose **Province** for that record.
4. Choose **Ward / Zone** for that record.
5. Choose **Assign to segment**.
6. Click **Resolve**.

### What happens after each action

- After you change the province or ward / zone for a specific unmapped record, only that record's segment dropdown is narrowed. Other unmapped records keep their own independent filter state.
- After **Resolve**, the app replays the unmapped record into `collected_records` for the chosen segment and marks the unmapped row as resolved.
- After resolve, the chosen segment's status is recalculated.
- If that resolve affected a segment, the verifier automatically runs scoped auto-checks on that segment using inspector name `system`.
- The page reruns and shows a success flash message. The resolved record disappears from the unresolved list.

### Important notes / limits

- If the selected province / ward combination has no matching active segments, the page shows a warning and you cannot resolve that record until you change the filters.
- This page resolves one unmapped record at a time.
- Resolving a record does not edit the raw payload itself; it only links the record to a chosen segment.

## Reports

### What this page is for

This page generates the daily Excel report package.

### What you can do here

- Choose a report date.
- Generate the Excel report.
- Download the workbook.

### Main workflows

1. Choose a **Report date**.
2. Click **Generate Report**.
3. Click **Download Excel**.

### What happens after each action

- After **Generate Report**, the app builds the workbook in memory for the selected date and shows the **Download Excel** button in the same run.
- After **Download Excel**, the workbook is downloaded to the browser.

### Important notes / limits

- This page does not persist a report export in session state the way some other pages do. If the page reruns, you may need to generate the report again before downloading.
- The report is generated from current database data plus the selected report date. It does not require a separate saved report configuration.

## Verification

### What this page is for

This page supports both automatic structural checks and manual inspector review.

### What you can do here

- Identify yourself as the current inspector.
- Manually trigger auto-checks for all eligible segments.
- Filter the manual-review queue by province and ward / zone.
- Inspect one segment's linked records and raw payloads.
- Save a manual review outcome that can change the segment's status.
- Filter and read the verification log.

### Main workflows

1. Enter **Inspector name**.
2. If you want to run checks across all eligible segments, click **Run Auto-Checks**.
3. For manual review:
   1. Select **Province**.
   2. Select **Ward / Zone**.
   3. Select a **Segment**.
   4. Review the linked records, per-position counts, and raw JSON.
   5. Choose **Review outcome**.
   6. Enter **Notes** if you are failing the segment.
   7. Click **Save Review**.
4. In **Verification Log**, choose `All`, `auto only`, or `manual only` to filter the recent log entries.

### What happens after each action

- After you enter inspector name, the manual controls become usable.
- After **Run Auto-Checks**, the verifier scans all eligible segments in `Đủ vị trí` or `Hoàn thành`, writes `auto` log rows, and updates each checked segment to either `Hoàn thành` or `Dữ liệu sai hoặc lỗi`.
- In manual review, after you choose a segment, the page loads all linked collected records for that segment, including soft-deleted rows for audit.
- After **Save Review**, the app writes a `manual` verification log row with your name and updates the segment status:
  - `pass` -> `Hoàn thành`
  - `fail` -> `Dữ liệu sai hoặc lỗi`
- After a successful manual review save, the page reruns and shows a success flash message at the top.
- After changing the log filter, the log table refreshes to show the latest 200 matching entries.

### Important notes / limits

- Manual review is only allowed for segments currently in `Đủ vị trí`, `Hoàn thành`, or `Dữ liệu sai hoặc lỗi`.
- Failing a segment requires non-empty notes.
- Auto-checks intentionally skip segments already in `Dữ liệu sai hoặc lỗi`. Only manual review can clear that state.
- Required-field verification is still not configured. The current checks are structural only.
- The log table shows recent entries only. It is not a full history browser.

## Background / Non-page Workflows

### Standalone sync script

`sync.py` is the standalone operational sync entrypoint. It is intended for cron or Task Scheduler use rather than interactive page use.

When it runs:

1. It creates the repository and sync service.
2. It chooses the default stub client or a `FileCollectionClient` if `TEST_RECORDS_FILE` is set.
3. It runs sync.
4. If any segments were affected, it runs scoped auto-verification for those segment IDs.

This means Page 9 can show new `auto` verification log rows even if no one manually visited the Verification page.

### Flask health check

The Flask API is support-only in the current project. The main user workflows live in Streamlit.

The only user-visible Flask endpoint documented here is:

- `/api/health-check`

This endpoint confirms the service shell is up, but it is not part of the collection-management workflow.
