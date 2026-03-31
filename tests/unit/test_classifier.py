"""Unit tests for A/B/C classifier."""
import pytest
from unittest.mock import patch

from src.service.classifier_service import ClassifierService


RULES = {
    "quan 1": {"A": 200_000_000, "B": 100_000_000},
}


def test_classifies_a():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_RULES', RULES):
        assert svc.classify("quan 1", 250_000_000) == "A"


def test_classifies_b():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_RULES', RULES):
        assert svc.classify("quan 1", 150_000_000) == "B"


def test_classifies_c_below_b():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_RULES', RULES):
        assert svc.classify("quan 1", 50_000_000) == "C"


def test_no_rule_defaults_to_c():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_RULES', {}):
        assert svc.classify("unknown ward", 999_999_999) == "C"


def test_none_vt1_defaults_to_c():
    svc = ClassifierService()
    with patch('src.service.classifier_service.CLASSIFICATION_RULES', RULES):
        assert svc.classify("quan 1", None) == "C"
