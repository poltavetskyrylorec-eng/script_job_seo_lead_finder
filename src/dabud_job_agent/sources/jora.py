from __future__ import annotations

import logging
from datetime import datetime

from dabud_job_agent.models import RawJobPosting

LOGGER = logging.getLogger(__name__)


class JoraAdapter:
    source_name = "jora"
    enabled = False

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        LOGGER.warning("Jora direct adapter is disabled. Use compliant search provider.")
        return []
