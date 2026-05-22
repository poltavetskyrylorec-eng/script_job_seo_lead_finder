from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import urlparse

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from dabud_job_agent.config import Settings
from dabud_job_agent.models import Contact, EmailSequence, JobPosting

LOGGER = logging.getLogger(__name__)

EMAIL_SEQUENCE_JSON_KEYS = (
    "email_1_subject",
    "email_1_body",
    "email_2_subject",
    "email_2_body",
    "email_3_subject",
    "email_3_body",
    "email_4_subject",
    "email_4_body",
    "personalization_notes",
    "business_case_summary",
)


class ClaudeEmailGenerationError(RuntimeError):
    """Raised when Claude cannot produce a valid email sequence."""


class ClaudeClient:
    MODEL_PRICING_PER_1M_TOKENS = {
        "claude-sonnet-4-6": (3.0, 15.0),
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cost_usd = 0.0

    @property
    def estimated_cost_usd(self) -> float:
        return self._cost_usd

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Rough approximation used for run-level cost tracking.
        return max(1, len(text) // 4)

    def _pricing_for_model(self) -> tuple[float, float]:
        model = self.settings.claude_model.strip().lower()
        return self.MODEL_PRICING_PER_1M_TOKENS.get(model, (3.0, 15.0))

    def _record_estimated_cost(self, prompt: str, response: str) -> None:
        input_tokens = self._estimate_tokens(prompt)
        output_tokens = self._estimate_tokens(response)
        input_price, output_price = self._pricing_for_model()
        self._cost_usd += (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price

    @staticmethod
    def _apply_real_name(text: str, contact: Contact) -> str:
        first_name = (contact.contact_first_name or contact.contact_full_name.split(" ")[0] or "").strip()
        if not first_name:
            return text
        output = text
        for marker in ("[First Name]", "{{first_name}}", "{first_name}", "<FIRST_NAME>", "<first_name>"):
            output = output.replace(marker, first_name)
        output = output.replace("Hi there,", f"Hi {first_name},").replace("Hi There,", f"Hi {first_name},")
        output = re.sub(r"^Hi\s+\[?first name\]?,", f"Hi {first_name},", output, flags=re.IGNORECASE | re.MULTILINE)
        return output

    @staticmethod
    def _extract_json_object(text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in Claude response")
        return json.loads(match.group(0))

    async def _prompt(self, prompt: str, *, use_configured_model: bool = True) -> str:
        cmd = ["claude", "-p", prompt]
        if use_configured_model and self.settings.claude_model.strip():
            cmd.extend(["--model", self.settings.claude_model.strip()])
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            err_text = (stderr or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Claude CLI failed with code={process.returncode}: {err_text}")
        return stdout.decode("utf-8", errors="ignore").strip()

    @retry(
        retry=retry_if_exception_type(RuntimeError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _prompt_email_sequence(self, prompt: str) -> str:
        return await self._prompt(prompt, use_configured_model=True)

    @staticmethod
    def _build_email_sequence(job: JobPosting, contact: Contact, payload: dict) -> EmailSequence:
        missing = [key for key in EMAIL_SEQUENCE_JSON_KEYS if not str(payload.get(key, "")).strip()]
        if missing:
            raise ClaudeEmailGenerationError(f"Claude response missing required fields: {', '.join(missing)}")

        return EmailSequence(
            run_id=job.run_id,
            company_domain=job.company_domain,
            company_name=job.company_name,
            contact_email=contact.contact_email,
            contact_full_name=contact.contact_full_name,
            outreach_track=job.outreach_track,
            email_1_subject=str(payload["email_1_subject"]).strip(),
            email_1_body=ClaudeClient._apply_real_name(str(payload["email_1_body"]), contact),
            email_2_subject=str(payload["email_2_subject"]).strip(),
            email_2_body=ClaudeClient._apply_real_name(str(payload["email_2_body"]), contact),
            email_3_subject=str(payload["email_3_subject"]).strip(),
            email_3_body=ClaudeClient._apply_real_name(str(payload["email_3_body"]), contact),
            email_4_subject=str(payload["email_4_subject"]).strip(),
            email_4_body=ClaudeClient._apply_real_name(str(payload["email_4_body"]), contact),
            personalization_notes=str(payload["personalization_notes"]).strip(),
            business_case_summary=str(payload["business_case_summary"]).strip(),
        )

    def detect_auth_mode(self) -> str:
        if self.settings.claude_code_oauth_token:
            return "claude_code_oauth_token"
        return "missing"

    async def find_company_domain(self, company_name: str, country_hint: str = "Australia") -> tuple[str, str]:
        clean_name = company_name.strip()
        if not clean_name or clean_name.lower() in {"unknown", "n/a", "none", "-"}:
            return "", ""
        if not self.settings.claude_code_oauth_token:
            return "", ""

        prompt = (
            "Use web search to find the official company website for the company below. "
            "Return ONLY strict JSON with keys: domain, website. "
            "Rules: prefer official corporate website; exclude job boards, social networks, wikipedia; "
            "domain must be apex domain only (like example.com). "
            f"Company name: {clean_name}. Country hint: {country_hint}."
        )
        try:
            raw = await self._prompt(prompt)
            self._record_estimated_cost(prompt, raw)
            payload = self._extract_json_object(raw)
            domain = str(payload.get("domain", "")).strip().lower()
            website = str(payload.get("website", "")).strip()
            if website and not domain:
                parsed = urlparse(website if "://" in website else f"https://{website}")
                domain = parsed.netloc.lower().replace("www.", "").strip()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain, website
        except Exception as exc:
            # Fallback: extract first domain-like token from raw text if JSON parse failed.
            try:
                raw = locals().get("raw", "")
                domain_match = re.search(r"\b([a-z0-9-]+\.)+[a-z]{2,}\b", raw.lower())
                url_match = re.search(r"https?://[^\s)]+", raw)
                if domain_match:
                    domain = domain_match.group(0).strip().lower().replace("www.", "")
                    website = url_match.group(0).strip() if url_match else f"https://{domain}"
                    return domain, website
            except Exception:
                pass
            LOGGER.warning("Claude domain lookup failed", extra={"company_name": clean_name, "error": str(exc)})
            return "", ""

    async def generate_email_sequence(self, job: JobPosting, contact: Contact) -> EmailSequence:
        if not self.settings.claude_code_oauth_token:
            raise ClaudeEmailGenerationError(
                "CLAUDE_CODE_OAUTH_TOKEN is required for email generation (no fallback allowed)."
            )

        first_name = (contact.contact_first_name or contact.contact_full_name.split(" ")[0] or "").strip()
        prompt = (
            "Write a 4-step outbound sequence in English for intent-based cold outreach and return ONLY JSON. "
            "JSON keys required: email_1_subject,email_1_body,email_2_subject,email_2_body,"
            "email_3_subject,email_3_body,email_4_subject,email_4_body,personalization_notes,business_case_summary. "
            "Constraints: subject <= 6 words, plain text, one CTA question each, "
            "do not mention seeing a specific job vacancy directly, avoid creepy language, "
            "and avoid replacing the SEO hire. "
            "Use the recipient first name in every email greeting (Hi <FirstName>,), never placeholders. "
            f"Recipient first name={first_name or 'there'}, "
            f"Company={job.company_name}, role={contact.contact_position}, hiring signal={job.job_title}, "
            f"track={job.outreach_track.value}, summary={job.job_description_summary}."
        )
        try:
            raw = await self._prompt_email_sequence(prompt)
            self._record_estimated_cost(prompt, raw)
            payload = self._extract_json_object(raw)
            return self._build_email_sequence(job, contact, payload)
        except Exception as exc:
            LOGGER.error(
                "Claude email generation failed",
                extra={
                    "error": str(exc),
                    "company": job.company_name,
                    "contact_email": contact.contact_email,
                    "model": self.settings.claude_model,
                },
            )
            raise ClaudeEmailGenerationError(str(exc)) from exc
