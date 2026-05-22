from __future__ import annotations

from datetime import datetime
from typing import Protocol

from dabud_job_agent.models import RawJobPosting


class JobSourceAdapter(Protocol):
    source_name: str
    enabled: bool

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        ...
