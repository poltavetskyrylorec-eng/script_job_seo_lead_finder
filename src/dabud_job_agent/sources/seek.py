from __future__ import annotations

import logging
from datetime import datetime

from dabud_job_agent.models import RawJobPosting

LOGGER = logging.getLogger(__name__)


class SeekAdapter:
    """
    Direct adapter is disabled by default.
    Reason: compliance-first mode requires official APIs or approved data providers.
    """

    source_name = "seek"
    enabled = False

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        LOGGER.warning(
            "Seek direct adapter is disabled by default. Use search_provider adapter for compliance."
        )
        return []
