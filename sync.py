"""
Standalone sync script — called by OS cron, NOT by the Flask/Gunicorn process.

Linux cron example:
    0 6 * * * /path/to/venv/bin/python /path/to/eform-data-collection/sync.py >> /path/to/logs/sync.log 2>&1

Windows Task Scheduler:
    Action: python sync.py  (with working directory set to project root)
"""
import logging
import os
import sys

# Allow importing from project root when run directly.
sys.path.insert(0, os.path.dirname(__file__))

from src.config.static_config import StaticConfig
from src.config.postgresql.postgresql_client import PostgreSQLClient
from src.repository.eform_repository import EformRepository
from src.clients.collection_client import StubCollectionClient, FileCollectionClient
from src.service.syncer_service import SyncerService
from src.service.verifier_service import VerifierService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    args_env = os.environ.get('FLASK_ENV', 'dev')
    logger.info(f"sync.py starting — env={args_env}")

    static_config = StaticConfig(app_args={'env': args_env})
    pg_client = PostgreSQLClient(static_config)
    repository = EformRepository(pg_client)

    # Swap StubCollectionClient for the real client when the API is built.
    # For local testing, set TEST_RECORDS_FILE to a JSON fixture path.
    _file = os.environ.get("TEST_RECORDS_FILE")
    collection_client = FileCollectionClient(_file) if _file else StubCollectionClient()

    syncer = SyncerService(repository, collection_client)
    verifier = VerifierService(repository)

    affected_ids = syncer.run()
    if affected_ids:
        verifier.run_auto_checks(nguoi_kiem_tra='system', segment_ids=affected_ids)

    logger.info("sync.py finished.")


if __name__ == '__main__':
    main()
