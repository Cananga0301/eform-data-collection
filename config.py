# Business-configurable settings

# A/B/C classification thresholds based on vt1 price (VND).
# Range semantics:
# - A: vt1 <= CLASSIFICATION_A_MAX
# - B: CLASSIFICATION_A_MAX < vt1 <= CLASSIFICATION_B_MAX
# - C: vt1 > CLASSIFICATION_B_MAX
#
# Boundary behavior:
# - 100,000,000 is classified as A
# - 200,000,000 is classified as B
CLASSIFICATION_A_MAX = 100_000_000
CLASSIFICATION_B_MAX = 200_000_000

# Default group when vt1 is missing.
CLASSIFICATION_DEFAULT = "C"

# Number of days used for velocity calculation in ETA.
ETA_WINDOW_DAYS = 7

# Number of records required per position.
RECORDS_PER_POSITION = 3

# Number of days with zero new records before a branch is highlighted.
BRANCH_ALERT_DAYS = 2
