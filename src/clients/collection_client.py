"""
Abstract interface for the external data collection API.

The real API is not built yet. StubCollectionClient is used in all phases
until the API team delivers their spec. To integrate the real API, subclass
AbstractCollectionClient and swap it in container.py.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone


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


class FileCollectionClient(AbstractCollectionClient):
    """
    Serves records from a local JSON file for local testing.

    The file must be a JSON array of record dicts in the fetch_records format
    (required fields: id, tinh_thanh, xa_phuong, ten_duong, doan, vi_tri,
    updated_at, is_deleted). Records are re-sorted at load time by effective
    timestamp then id to match the cursor ordering the syncer expects.

    Usage (Streamlit Page 5):
        Type the file path in the fixture input, then click Run Sync Now.

    Usage (sync.py / cron):
        $env:TEST_RECORDS_FILE = 'test_collected_records.json'
        poetry run python sync.py
    """

    def __init__(self, path: str):
        import json
        from pathlib import Path
        resolved = Path(path).resolve()
        with open(resolved, encoding="utf-8-sig") as f:
            raw: list[dict] = json.load(f)
        self._records = sorted(raw, key=lambda r: (self._ts(r), r.get("id", "")))

    @classmethod
    def from_bytes(cls, data: bytes) -> 'FileCollectionClient':
        """Load records from raw JSON bytes (e.g. from st.file_uploader)."""
        import json
        instance = cls.__new__(cls)
        raw: list[dict] = json.loads(data.decode('utf-8-sig'))
        instance._records = sorted(raw, key=lambda r: (cls._ts(r), r.get("id", "")))
        return instance

    @staticmethod
    def _ts(r: dict) -> datetime:
        ts_str = r.get("updated_at") or r.get("created_at") or ""
        if not ts_str:
            return datetime.min.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

    def fetch_records(
        self,
        since: datetime,
        page: int,
        page_size: int,
        last_record_id: str = None,
    ) -> dict:
        filtered = []
        for r in self._records:
            rec_ts = self._ts(r)
            if rec_ts < since:
                continue
            # Tie-break on page 1: skip same-timestamp records seen in previous sync
            if rec_ts == since and last_record_id is not None and r.get("id", "") <= last_record_id:
                continue
            filtered.append(r)

        start = (page - 1) * page_size
        end = start + page_size
        return {
            "records": filtered[start:end],
            "has_next": end < len(filtered),
        }
