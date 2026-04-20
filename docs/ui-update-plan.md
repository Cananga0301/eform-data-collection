# UI Update Plan

## Purpose

This document captures the agreed near-term UI restructuring plan for the Streamlit app in `src/streamlit_app.py`.

The goal is to improve task clarity and reduce navigation friction without taking on a high-risk information architecture rewrite in the first pass.

This plan is intentionally conservative. It focuses on changes that are strongly supported by the current code, current workflow docs, and current operator model.

## Current Context

- The Streamlit UI is the primary interface for Head Office staff.
- The current app groups several distinct workflows into single long pages.
- Some pages are logically downstream of others but are split apart in navigation.
- Some screens duplicate similar drilldown/detail patterns.

Relevant references:

- `src/streamlit_app.py`
- `docs/features.md`
- `docs/workflow.md`
- `CLAUDE.md`

## Working Assessment

The current UI structure is broadly aligned with the operational workflow, but several parts create avoidable friction:

- `Import & Review` combines a one-shot import action with a stateful editing workspace.
- `Branch Mapping & Assignments` combines related ownership configuration tasks, but presents them as one long stacked page instead of separate modes.
- `Sync Status` and `Unmapped Records` are operationally part of the same loop, but are split into separate pages.
- `Reports` is currently too small to justify a standalone page.
- `Progress Dashboard` and `Verification` both contain segment-level detail workflows, which creates overlap that should be reduced later.

## Decisions Accepted For Implementation

These are ready to implement without additional product decisions.

### 1. Split `Import & Review` into tabs

Current issue:

- The page mixes two different modes:
  - import/classify
  - HO review / group override
- The user has to scroll through unrelated actions.
- The code paths are also materially different: import is transactional, while HO review is stateful and editor-driven.

Planned change:

- Keep one top-level page for now.
- Replace the stacked layout with tabs or an equivalent in-page mode switch.
- Proposed tab structure:
  - `Import & Classify`
  - `HO Review`

Expected effect:

- clearer mental model
- less scroll
- easier future refactor if these become separate pages later

### 2. Merge `Sync Status` and `Unmapped Records`

Current issue:

- Unmapped records are the failure output of sync.
- After running sync, the next operator action is often resolving unmapped records.
- Splitting them into separate pages breaks the operational loop.

Planned change:

- Merge both workflows into a single page.
- Proposed page structure:
  - sync summary
  - manual sync action
  - unresolved unmapped queue

Expected effect:

- shorter path from sync to exception handling
- better visibility into sync outcomes
- fewer navigation hops

### 3. Fold `Reports` into `Progress Dashboard`

Current issue:

- `Reports` currently contains a date input and one export action.
- It does not justify a standalone destination.

Planned change:

- Remove `Reports` as a separate page.
- Move the daily report export into `Progress Dashboard`.
- Place the export controls near the already filtered reporting context, not as an isolated header action.

Expected effect:

- fewer thin pages
- more coherent reporting/export experience
- less navigation overhead

## Decisions Explicitly Deferred

These should not be treated as settled in phase 1.

### 1. Full navigation restructure into 4 workspaces

Candidate future model:

- `Setup`
- `Collection Ops`
- `Monitoring`
- `Quality`

Reason deferred:

- This is a broader product and navigation decision.
- It likely requires restructuring how navigation is built, not just page content.
- The current conservative changes should be tested first before committing to a larger IA rewrite.

### 2. Final ownership split between `Progress Dashboard` and `Verification`

Current issue:

- `Segment Record Detail` in the dashboard overlaps with manual review detail in verification.

Reason deferred:

- The correct split depends on who performs monitoring versus review in real operations.
- The repo context suggests Head Office staff are the main users, which may justify keeping richer detail in the dashboard.

Current leaning:

- keep rich read-only segment detail in `Progress Dashboard`
- simplify `Verification` so it focuses more on review actions and verification-specific controls

This should be finalized after phase 1 changes, not before.

## Recommended Implementation Order

### Phase 1: Low-risk structural cleanup

1. Split `Import & Review` into tabs.
2. Merge `Sync Status` and `Unmapped Records`.
3. Move `Reports` functionality into `Progress Dashboard`.

### Phase 2: Reduce overlap

4. Reassess the boundary between dashboard drilldown and verification detail.
5. Remove duplicated detail patterns where possible.

### Phase 3: Optional IA redesign

6. Evaluate whether the app should move to a larger workspace-based navigation model.

## Implementation Notes

- Prioritize layout and information architecture first; avoid mixing structural change with visual polish in the same pass.
- Keep existing business logic intact during phase 1.
- Prefer moving existing sections into tabs/containers over rewriting service interactions.
- Preserve current session-state behavior for HO review and other stateful interactions.
- Keep exports attached to the filtered context that generates them.
- Treat test-only or debug-oriented controls carefully so they do not dominate the operator workflow.

## Success Criteria

Phase 1 is successful if:

- operators can identify where to import, review, sync, resolve exceptions, and export without scanning long stacked pages
- sync outcomes and unmapped resolution feel like one continuous workflow
- the app has fewer thin or redundant destinations
- no core workflow is removed or made harder to access

## Immediate Next Step

Implement phase 1 only:

1. tabbed `Import & Review`
2. combined sync/unmapped page
3. report export moved into dashboard

Leave the dashboard-versus-verification ownership question open until the new structure is in place.
