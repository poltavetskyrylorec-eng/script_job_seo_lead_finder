from __future__ import annotations

import logging
from datetime import datetime

from dabud_job_agent.models import RawJobPosting

LOGGER = logging.getLogger(__name__)


class GlassdoorAdapter:
    source_name = "glassdoor"
    enabled = False

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        LOGGER.warning("Glassdoor direct adapter is disabled. Use compliant search provider.")
        return []
