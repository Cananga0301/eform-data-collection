"""
T1 - A/B/C classification.

Classification is based on global vt1 price bands configured in config.py.
"""

from config import (
    CLASSIFICATION_A_MAX,
    CLASSIFICATION_B_MAX,
    CLASSIFICATION_DEFAULT,
)


class ClassifierService:
    def classify(self, xa_phuong_norm: str, vt1: int) -> str:
        """
        Return 'A', 'B', or 'C' based on the segment's vt1 price.

        xa_phuong_norm is currently unused but kept in the interface so the
        importer and any future ward-specific logic do not need a signature change.
        """
        _ = xa_phuong_norm

        if vt1 is None:
            return CLASSIFICATION_DEFAULT

        if vt1 <= CLASSIFICATION_A_MAX:
            return 'A'
        if vt1 <= CLASSIFICATION_B_MAX:
            return 'B'
        return 'C'
