from __future__ import annotations

from dabud_job_agent.models import Contact, EmailSequence, JobPosting


def _trim_subject(text: str) -> str:
    words = text.split()
    return " ".join(words[:6])[:72]


def build_fallback_sequence(job: JobPosting, contact: Contact) -> EmailSequence:
    first_name = contact.contact_first_name or contact.contact_full_name.split(" ")[0] or "there"
    signal = f"{job.company_name} is investing in SEO capability"
    track_line = (
        "partner angle for your client placements"
        if job.outreach_track.value == "partner"
        else "AI-search visibility opportunity"
    )

    e1_subject = _trim_subject(f"{job.company_name} SEO momentum")
    e1_body = (
        f"Hi {first_name}, noticed {job.company_name} is expanding its SEO focus. "
        "Teams doing this often find that AI-search visibility becomes the next gap after classic rankings. "
        "dabud.ai helps track where your brand appears in ChatGPT and AI Overviews, then prioritizes fixes. "
        "Worth a quick look?"
    )

    e2_subject = _trim_subject(f"Quick follow-up on {job.company_name}")
    e2_body = (
        f"Hi {first_name}, one practical data point: in many markets, AI answers route branded intent "
        "to competitors even when organic rankings are solid. "
        f"This is where {track_line} starts paying off fast. "
        "Should I send a short playbook your team can apply from day one?"
    )

    e3_subject = _trim_subject("15 min walkthrough")
    e3_body = (
        f"Hi {first_name}, quick idea for {job.company_name}. "
        "We can map where your brand appears in ChatGPT, AI Overviews, and Perplexity, then show what to fix first. "
        "Teams usually use this as a practical checklist for the SEO owner from day one. "
        "Would a 15-minute walkthrough be useful?"
    )

    e4_subject = _trim_subject("Closing the loop")
    e4_body = (
        f"Hi {first_name}, last note and I will close the thread. "
        f"We reached out because {signal}. "
        "If timing is off, I can send a short recorded walkthrough instead of a call, "
        "or share a one-page summary you can review later. "
        "Which option works better for you?"
    )

    return EmailSequence(
        run_id=job.run_id,
        company_domain=job.company_domain,
        company_name=job.company_name,
        contact_email=contact.contact_email,
        contact_full_name=contact.contact_full_name,
        outreach_track=job.outreach_track,
        email_1_subject=e1_subject,
        email_1_body=e1_body,
        email_2_subject=e2_subject,
        email_2_body=e2_body,
        email_3_subject=e3_subject,
        email_3_body=e3_body,
        email_4_subject=e4_subject,
        email_4_body=e4_body,
        personalization_notes=(
            f"Used hiring signal ({job.job_title}), company type ({job.company_type.value}), "
            f"track ({job.outreach_track.value})."
        ),
        business_case_summary=(
            f"{job.company_name} is actively hiring for SEO/organic growth; "
            "this indicates near-term budget and execution urgency."
        ),
        approval_status="pending",
        send_status="not_sent",
    )
