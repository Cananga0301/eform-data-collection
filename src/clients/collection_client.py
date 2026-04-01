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
    def fetch_records(
        self,
        since: datetime,
        page: int,
        page_size: int,
        last_record_id: str = None,
    ) -> dict:
        """
        Fetch records from the collection app API.

        Args:
            since:          Only return records updated at or after this timestamp.
            page:           1-based page number.
            page_size:      Number of records per page.
            last_record_id: On page 1, the source record ID of the last record
                            processed in the previous sync. The API should skip
                            records at the boundary timestamp that were already
                            seen (tie-breaking for same-timestamp batches).
                            Ignored on page > 1. May be None on first-ever sync.

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

    def fetch_records(
        self,
        since: datetime,
        page: int,
        page_size: int,
        last_record_id: str = None,
    ) -> dict:
        return {'records': [], 'has_next': False}
