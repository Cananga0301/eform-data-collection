"""Unit tests for text normalization."""
import pytest
from src.utils.text import normalize


def test_strips_whitespace():
    assert normalize("  Hà Nội  ") == "ha noi"


def test_lowercases():
    assert normalize("HCM") == "hcm"


def test_collapses_spaces():
    assert normalize("Quận  1") == "quan 1"


def test_strips_diacritics():
    assert normalize("Đường") == "duong"
    assert normalize("phường") == "phuong"
    assert normalize("Tây Hồ") == "tay ho"


def test_empty_string():
    assert normalize("") == ""


def test_none():
    assert normalize(None) == ""


def test_already_normalized():
    assert normalize("quan 1") == "quan 1"


def test_mixed():
    assert normalize("  Khu vực 1 (các phường Tây Hồ)  ") == "khu vuc 1 (cac phuong tay ho)"
