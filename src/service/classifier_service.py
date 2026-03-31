"""
T1 — A/B/C classification.

Thresholds are configured in config.CLASSIFICATION_RULES.
Business fills these in before go-live; until then all segments default to 'C'.
"""
from config import CLASSIFICATION_RULES, CLASSIFICATION_DEFAULT


class ClassifierService:
    def classify(self, xa_phuong_norm: str, vt1: int) -> str:
        """
        Return 'A', 'B', or 'C' based on xa_phuong + vt1 price.

        Rules dict format:
            { "normalized_xa_phuong": {"A": min_vt1_for_A, "B": min_vt1_for_B} }

        If xa_phuong has no configured rule, returns CLASSIFICATION_DEFAULT ('C').
        """
        rules = CLASSIFICATION_RULES.get(xa_phuong_norm)
        if rules and vt1 is not None:
            if vt1 >= rules.get('A', float('inf')):
                return 'A'
            if vt1 >= rules.get('B', float('inf')):
                return 'B'
        return CLASSIFICATION_DEFAULT
