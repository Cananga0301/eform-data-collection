import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


class PostgreSQLClient:
    def __init__(self, static_config):
        cfg = static_config.asset_config['POSTGRESQL']
        host = cfg.get('host', os.environ.get('POSTGRESQL_HOST', 'localhost'))
        port = cfg.get('port', os.environ.get('POSTGRESQL_PORT', '5432'))
        database = cfg.get('database', os.environ.get('POSTGRESQL_DATABASE', 'eform_data'))
        username = cfg.get('username', os.environ.get('POSTGRESQL_USER', 'eform_user'))
        password = cfg.get('password', os.environ.get('POSTGRESQL_PASS', ''))

        url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
        self.engine = create_engine(url, pool_size=10, max_overflow=20)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def get_session(self) -> Session:
        return self.SessionLocal()
