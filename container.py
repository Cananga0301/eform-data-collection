import logging

from dependency_injector import containers, providers

from src.config.static_config import StaticConfig
from src.config.postgresql.postgresql_client import PostgreSQLClient
from src.repository.eform_repository import EformRepository
from src.service.importer_service import ImporterService
from src.service.classifier_service import ClassifierService
from src.service.assigner_service import AssignerService
from src.service.syncer_service import SyncerService
from src.service.reporter_service import ReporterService
from src.service.verifier_service import VerifierService
from src.clients.collection_client import StubCollectionClient

logger = logging.getLogger(__name__)


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=[
        "src.config",
        "src.controller",
        "src.service",
    ])

    config = providers.Configuration()

    static_config = providers.Singleton(
        StaticConfig,
        app_args=config.app_args,
    )

    postgresql_client = providers.Singleton(
        PostgreSQLClient,
        static_config,
    )

    collection_client = providers.Singleton(
        StubCollectionClient,
    )

    eform_repository = providers.Singleton(
        EformRepository,
        postgresql_client,
    )

    classifier_service = providers.Singleton(ClassifierService)

    importer_service = providers.Singleton(
        ImporterService,
        eform_repository,
        classifier_service,
    )

    assigner_service = providers.Singleton(
        AssignerService,
        eform_repository,
    )

    syncer_service = providers.Singleton(
        SyncerService,
        eform_repository,
        collection_client,
    )

    reporter_service = providers.Singleton(
        ReporterService,
        eform_repository,
    )

    verifier_service = providers.Singleton(
        VerifierService,
        eform_repository,
    )
