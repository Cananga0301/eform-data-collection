"""Unit tests for assignment import helpers."""

from unittest.mock import MagicMock

from src.models.eform_models import Branch
from src.service.assigner_service import AssignerService


def test_get_or_create_branch_returns_existing_branch():
    service = AssignerService(repository=MagicMock())
    session = MagicMock()
    existing = Branch(name='CN HCM')
    existing.id = 7
    session.query.return_value.filter_by.return_value.first.return_value = existing

    branch = service._get_or_create_branch(session, 'CN HCM')

    assert branch is existing
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_get_or_create_branch_creates_missing_branch():
    service = AssignerService(repository=MagicMock())
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    branch = service._get_or_create_branch(session, 'CN Moi')

    assert isinstance(branch, Branch)
    assert branch.name == 'CN Moi'
    session.add.assert_called_once_with(branch)
    session.flush.assert_called_once()
