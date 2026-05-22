from __future__ import annotations

import logging
from datetime import datetime

from dabud_job_agent.models import RawJobPosting

LOGGER = logging.getLogger(__name__)


class LinkedInAdapter:
    """
    Disabled by default because direct scraping/login-wall bypass is out of compliance scope.
    """

    source_name = "linkedin"
    enabled = False

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        LOGGER.warning(
            "LinkedIn adapter disabled by default. Enable only with compliant official data source."
        )
        return []
