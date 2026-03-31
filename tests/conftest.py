"""
Shared test fixtures.

Integration tests use pytest-postgresql to spin up a temporary real PostgreSQL
instance. Unit tests can use it or mock the repository directly.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.eform_models import Base


@pytest.fixture(scope='session')
def pg_proc(postgresql_proc):
    """pytest-postgresql process fixture (session-scoped)."""
    return postgresql_proc


@pytest.fixture(scope='function')
def db_engine(postgresql):
    """
    Creates a fresh schema in a temp PostgreSQL DB for each test function.
    `postgresql` is the pytest-postgresql connection fixture.
    """
    connection_str = (
        f"postgresql://{postgresql.info.user}:@"
        f"{postgresql.info.host}:{postgresql.info.port}/{postgresql.info.dbname}"
    )
    engine = create_engine(connection_str)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope='function')
def db_session(db_engine):
    """Provides a SQLAlchemy session bound to the test database."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()
