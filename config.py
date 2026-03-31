# ──────────────────────────────────────────────────────────────────────────────
# Business-configurable settings
# ──────────────────────────────────────────────────────────────────────────────

# A/B/C classification thresholds.
# Key: normalized xa_phuong string.
# Value: {"A": vt1_min_for_A, "B": vt1_min_for_B}
# Segments below the B threshold are classified as C.
# Business fills this in before go-live.
CLASSIFICATION_RULES: dict[str, dict[str, int]] = {
    # Example (replace with real values from business):
    # "quan 1": {"A": 200_000_000, "B": 100_000_000},
}

# Default group when xa_phuong has no rule configured.
CLASSIFICATION_DEFAULT = "C"

# Number of days used for velocity calculation in ETA.
ETA_WINDOW_DAYS = 7

# Number of records required per position.
RECORDS_PER_POSITION = 3

# Number of days with zero new records before a branch is highlighted.
BRANCH_ALERT_DAYS = 2
