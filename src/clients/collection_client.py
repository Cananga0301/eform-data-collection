"""
Abstract interface for the external data collection API.

The real API is not built yet. StubCollectionClient is used in all phases
until the API team delivers their spec. To integrate the real API, subclass
AbstractCollectionClient and swap it in container.py.
"""
from abc import ABC, abstractmethod
from datetime import datetime


class AbstractCollectionClient(ABC):
    @abstractmethod
    def fetch_records(self, since: datetime, page: int, page_size: int) -> dict:
        """
        Fetch records from the collection app API.

        Args:
            since:     Only return records updated at or after this timestamp.
            page:      1-based page number.
            page_size: Number of records per page.

        Returns:
            {
                'records': [
                    {
                        'id': str,           # stable source record ID
                        'tinh_thanh': str,
                        'xa_phuong': str,
                        'ten_duong': str,
                        'doan': str | None,
                        'vi_tri': int,       # 1–4
                        'updated_at': str,   # ISO 8601
                        'is_deleted': bool,  # true if soft-deleted in source
                        ...                  # other raw fields stored in raw_data
                    },
                    ...
                ],
                'has_next': bool
            }
        """


class StubCollectionClient(AbstractCollectionClient):
    """Returns empty results — used until the real API is built."""

    def fetch_records(self, since: datetime, page: int, page_size: int) -> dict:
        return {'records': [], 'has_next': False}
