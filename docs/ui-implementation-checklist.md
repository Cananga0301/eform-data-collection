# UI Implementation Checklist

## Purpose

This document translates the UI update plan into a concrete implementation checklist against `src/streamlit_app.py`.

It is scoped to the agreed phase 1 changes only:

1. split `Import & Review` into tabs
2. merge `Sync Status` and `Unmapped Records`
3. move `Reports` into `Progress Dashboard`

This document is intentionally code-facing. It identifies the existing blocks to edit, the behavior to preserve, and the acceptance checks for each change.

## Target File

- `src/streamlit_app.py`

## Constraints

- Do not change business logic in services unless strictly required by a UI move.
- Preserve current session-state behavior for stateful workflows.
- Keep phase 1 focused on structure and workflow clarity, not broad visual redesign.
- Do not resolve the dashboard-versus-verification ownership question in this phase.

## Checklist

### 1. Update sidebar navigation

Target:

- `PAGES` in `src/streamlit_app.py`

Current reference:

- page definitions near the top of the file

Tasks:

- Remove `Reports` from the page list.
- Replace separate `Sync Status` and `Unmapped Records` entries with one combined page label.
- Use a stable combined label, for example:
  - `Sync & Unmapped`
- Keep other page labels unchanged unless required for consistency.

Acceptance checks:

- sidebar shows the reduced page list
- selecting each page still reaches a valid page branch
- no orphan page branch remains reachable only by stale label

### 2. Split `Import & Review` into tabs

Target:

- `if page == 'Import & Review':`

Current blocks:

- import section at the start of the branch
- HO review section beginning at `st.subheader('HO Review / Group Override')`

Tasks:

- Keep the top-level page branch as `Import & Review`.
- Introduce two tabs inside the page:
  - `Import & Classify`
  - `HO Review`
- Move the import uploader, run button, result messaging, and result table into the first tab.
- Move the HO review filters, table/editor, bulk actions, save flow, and export flow into the second tab.
- Remove the old stacked layout and divider once both tab contents are in place.

Behavior to preserve:

- import runs file-by-file and shows per-file results
- existing import error/success messaging remains intact
- HO review still requires province and ward selection before load
- HO review still preserves:
  - `ho_segments_df`
  - `ho_segments_original`
  - `ho_editor_version`
  - `ho_segments_edited`
  - related `ho_*` state keys
- HO review save still updates only changed `nhom` values
- HO review export still produces downloadable Excel bytes

Acceptance checks:

- import works with one or more files
- failed import still shows warnings and row-level errors
- HO review load/edit/save/export still works
- switching tabs does not unexpectedly wipe loaded HO review state
- no duplicate widget key errors occur

### 3. Leave `Branch Mapping & Assignments` unchanged in phase 1

Target:

- `elif page == 'Branch Mapping & Assignments':`

Tasks:

- Do not restructure this page during phase 1.
- Only make edits here if needed for navigation consistency or page-label cleanup elsewhere.

Acceptance checks:

- branch creation still works
- mapping save still works
- assignment export/import still works

### 4. Merge `Sync Status` and `Unmapped Records`

Targets:

- existing `elif page == 'Sync Status':`
- existing `elif page == 'Unmapped Records':`

Tasks:

- Replace the `Sync Status` page branch with a combined page branch label matching the updated sidebar.
- Keep the sync summary and run controls at the top of the combined page.
- Move the unresolved unmapped queue directly below the sync area.
- Preserve current resolve behavior and success flash messaging.
- After the combined page works, remove the old standalone `Unmapped Records` page branch.

Recommended layout:

- page header
- sync status summary
- sync action area
- optional test/debug controls
- unresolved unmapped queue

Optional cleanup:

- move the fixture uploader into a collapsed expander such as `Test / Debug`
- keep it accessible, but de-emphasized for normal operators

Behavior to preserve:

- sync still supports fixture-file execution
- sync still runs verifier auto-checks for affected segments
- unmapped records still show:
  - reason
  - raw JSON
  - province / ward narrowing
  - segment assignment
  - resolve action
- resolve still reruns and removes the resolved record from the unresolved list

Acceptance checks:

- user can run sync and then resolve an unmapped record from the same page
- success flash still appears after resolve
- no behavior regression in sync summary or resolve flow

### 5. Move `Reports` into `Progress Dashboard`

Targets:

- `elif page == 'Progress Dashboard':`
- `elif page == 'Reports':`

Tasks:

- Add an export section inside `Progress Dashboard`.
- Keep the existing dashboard export flow in place or move it into the new export section.
- Move the daily report controls from the standalone `Reports` page into the dashboard export section.
- After the dashboard version works, remove the standalone `Reports` page branch.

Recommended layout:

- dashboard metrics and tables
- segment record detail
- exports section
  - dashboard export
  - daily report export

Behavior to preserve:

- dashboard export still uses the current dashboard filters
- daily report export still uses a selected report date
- each export keeps its own download state

Implementation note:

- use separate session-state keys for:
  - dashboard export bytes
  - daily report export bytes
- do not reuse one export key for both download buttons

Acceptance checks:

- dashboard export still downloads correctly
- daily report export still downloads correctly
- no button/download collisions occur

### 6. Leave `Verification` unchanged in phase 1

Target:

- `elif page == 'Verification':`

Tasks:

- Do not restructure or simplify verification yet.
- Only update this branch if needed for navigation consistency elsewhere.

Reason:

- the overlap with dashboard detail is a later product decision
- phase 1 should not change verification ownership or workflow shape

Acceptance checks:

- auto-checks still run
- manual review still saves
- verification log still loads correctly

### 7. Remove obsolete page branches after replacement is verified

Targets:

- old standalone `Reports` branch
- old standalone `Unmapped Records` branch

Tasks:

- remove old branches only after replacement UI is working
- confirm that sidebar labels and page branch conditions stay in sync

Acceptance checks:

- no dead code path remains for removed pages
- sidebar and page condition labels match exactly

### 8. Run manual regression across the full app

Run through these workflows after all phase 1 edits:

- import route Excel files
- HO review load/edit/save/export
- branch creation
- branch mapping save
- assignment export
- assignment import
- sync run
- unmapped resolution
- progress dashboard filters
- segment record detail
- dashboard export
- daily report export
- verification auto-checks
- verification manual review
- verification log display

Watch for:

- widget key collisions
- session-state resets
- broken rerun flows
- missing download buttons
- stale flash messages
- page label mismatches

## Definition of Done

Phase 1 is done when:

- `Import & Review` is tabbed instead of stacked
- sync and unmapped resolution live on one page
- `Reports` no longer exists as a standalone page
- dashboard contains the reporting/export actions
- verification remains unchanged
- all existing workflows still function after manual regression
