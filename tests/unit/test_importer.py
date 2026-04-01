"""Unit tests for Vietnamese VND price parsing."""

import pandas as pd
import pytest

from src.service.classifier_service import ClassifierService
from src.service.importer_service import ImportValidationError, ImporterService, _parse_vnd_price


@pytest.mark.parametrize(
    ('raw_value', 'expected'),
    [
        ('96249000', 96249000),
        ('96.249.000', 96249000),
        ('96,249,000', 96249000),
        ('96 249 000', 96249000),
        ('96\u00A0249\u00A0000', 96249000),
        ('96249000.0', 96249000),
        ('96249000,00', 96249000),
        ('96.249.000,00', 96249000),
        ('96,249,000.00', 96249000),
        ('96.249.000 \u0111', 96249000),
        ('96.249.000 vnd', 96249000),
        ('-', None),
        (' -- ', None),
        ('N/A', None),
        (None, None),
        ('   ', None),
    ],
)
def test_parse_vnd_price_accepts_supported_formats(raw_value, expected):
    assert _parse_vnd_price(raw_value) == expected


@pytest.mark.parametrize(
    'raw_value',
    ['96,5', '96.249,5', '96.5', 'abc', '12.34.567', '\u0111'],
)
def test_parse_vnd_price_rejects_invalid_or_ambiguous_formats(raw_value):
    with pytest.raises(ValueError):
        _parse_vnd_price(raw_value)


def test_validate_and_parse_prices_reports_row_column_and_raw_value():
    service = ImporterService(repository=None, classifier=ClassifierService())
    df = pd.DataFrame(
        [
            {'vt1': '96.249.000', 'vt2': None},
            {'vt1': 'abc', 'vt2': '48.000.000'},
        ]
    )

    with pytest.raises(ImportValidationError) as exc_info:
        service._validate_and_parse_prices(df, 'routes.xlsx')

    assert exc_info.value.filename == 'routes.xlsx'
    assert len(exc_info.value.errors) == 1
    assert exc_info.value.errors[0].row_number == 3
    assert exc_info.value.errors[0].column_name == 'vt1'
    assert exc_info.value.errors[0].raw_value == 'abc'


def test_validate_and_parse_prices_preserves_python_int_and_none_values():
    service = ImporterService(repository=None, classifier=ClassifierService())
    df = pd.DataFrame(
        [
            {'vt1': '96.249.000', 'vt2': '-'},
            {'vt1': '48.000.000', 'vt2': '12.500.000'},
        ]
    )

    service._validate_and_parse_prices(df, 'routes.xlsx')

    assert df['vt1'].dtype == 'object'
    assert df['vt2'].dtype == 'object'
    assert df.iloc[0]['vt1'] == 96249000
    assert df.iloc[0]['vt2'] is None
    assert df.iloc[1]['vt1'] == 48000000
    assert df.iloc[1]['vt2'] == 12500000
