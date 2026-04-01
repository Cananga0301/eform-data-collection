"""Unit tests for A/B/C classifier."""

from unittest.mock import patch

from src.service.classifier_service import ClassifierService


def test_classifies_a_at_or_below_100m():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_A_MAX', 100_000_000), \
         patch('src.service.classifier_service.CLASSIFICATION_B_MAX', 200_000_000):
        assert svc.classify("any ward", 50_000_000) == "A"
        assert svc.classify("any ward", 100_000_000) == "A"


def test_classifies_b_between_100m_and_200m_inclusive():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_A_MAX', 100_000_000), \
         patch('src.service.classifier_service.CLASSIFICATION_B_MAX', 200_000_000):
        assert svc.classify("any ward", 150_000_000) == "B"
        assert svc.classify("any ward", 200_000_000) == "B"


def test_classifies_c_above_200m():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_A_MAX', 100_000_000), \
         patch('src.service.classifier_service.CLASSIFICATION_B_MAX', 200_000_000):
        assert svc.classify("any ward", 200_000_001) == "C"
        assert svc.classify("any ward", 999_999_999) == "C"


def test_none_vt1_defaults_to_c():
    svc = ClassifierService()
    assert svc.classify("any ward", None) == "C"
