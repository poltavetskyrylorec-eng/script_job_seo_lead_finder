from __future__ import annotations

import logging
from datetime import datetime

from dabud_job_agent.models import RawJobPosting

LOGGER = logging.getLogger(__name__)


class IndeedAdapter:
    source_name = "indeed"
    enabled = False

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        LOGGER.warning("Indeed direct adapter is disabled. Use compliant search provider.")
        return []
