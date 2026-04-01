"""Integration tests for importer price parsing and validation."""

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from src.models.eform_models import Segment
from src.repository.eform_repository import EformRepository
from src.service.classifier_service import ClassifierService
from src.service.importer_service import ImportValidationError, ImporterService


class DummyPostgreSQLClient:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_session(self):
        return self._session_factory()


def _build_importer(db_engine):
    session_factory = sessionmaker(bind=db_engine)
    repository = EformRepository(DummyPostgreSQLClient(session_factory))
    return ImporterService(repository, ClassifierService())


def _write_excel(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def test_import_excel_parses_vietnamese_grouped_prices(db_engine, tmp_path):
    importer = _build_importer(db_engine)
    excel_path = _write_excel(
        tmp_path / 'routes.xlsx',
        [
            {
                'stt': 1,
                'tinh_thanh': 'Ho Chi Minh',
                'xa_phuong': 'Quan 1',
                'ten_duong': 'Duong A',
                'doan': 'Doan 1',
                'vt1': '96.249.000',
                'vt2': '48.124.000',
                'vt3': None,
                'vt4': None,
            }
        ],
    )

    result = importer.import_excel(str(excel_path), source_name='routes.xlsx')

    assert result == {'upserted': 1, 'deactivated': 0}

    session = sessionmaker(bind=db_engine)()
    try:
        segment = session.query(Segment).one()
        assert segment.vt1 == 96249000
        assert segment.vt2 == 48124000
        assert segment.vt3 is None
        assert segment.so_can_vt1 == 3
        assert segment.so_can_vt2 == 3
        assert segment.so_can_vt3 is None
    finally:
        session.close()


def test_import_excel_fails_file_on_invalid_non_empty_price(db_engine, tmp_path):
    importer = _build_importer(db_engine)
    excel_path = _write_excel(
        tmp_path / 'bad-routes.xlsx',
        [
            {
                'stt': 1,
                'tinh_thanh': 'Ho Chi Minh',
                'xa_phuong': 'Quan 1',
                'ten_duong': 'Duong A',
                'doan': 'Doan 1',
                'vt1': 'abc',
            }
        ],
    )

    with pytest.raises(ImportValidationError) as exc_info:
        importer.import_excel(str(excel_path), source_name='bad-routes.xlsx')

    assert exc_info.value.filename == 'bad-routes.xlsx'
    assert len(exc_info.value.errors) == 1
    assert exc_info.value.errors[0].row_number == 2
    assert exc_info.value.errors[0].column_name == 'vt1'
    assert exc_info.value.errors[0].raw_value == 'abc'

    session = sessionmaker(bind=db_engine)()
    try:
        assert session.query(Segment).count() == 0
    finally:
        session.close()
