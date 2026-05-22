from __future__ import annotations

from dabud_job_agent.models import CompanyType, Contact

PRIORITIES: dict[CompanyType, dict[int, list[str]]] = {
    CompanyType.SEO_OR_MARKETING_AGENCY: {
        1: ["founder", "co-founder", "ceo", "managing director", "agency owner"],
        2: [
            "head of seo",
            "seo director",
            "seo lead",
            "head of strategy",
            "strategy director",
            "client services director",
            "head of client services",
        ],
        3: ["partnerships manager", "business development manager", "growth manager"],
    },
    CompanyType.RECRUITING_OR_HR_AGENCY: {
        1: ["founder", "co-founder", "ceo", "managing director", "director"],
        2: [
            "recruitment director",
            "talent director",
            "head of recruitment",
            "principal consultant",
            "senior recruitment consultant",
            "practice lead",
            "digital marketing recruitment consultant",
            "marketing recruitment consultant",
        ],
        3: ["partnerships manager", "business development manager", "client director"],
    },
}

DEFAULT_PRIORITIES = {
    1: [
        "practice manager",
        "clinic manager",
        "practice owner",
        "clinic director",
        "medical director",
        "owner",
        "business owner",
        "founder",
        "founder & ceo",
        "managing director",
        "coo",
    ],
    2: [
        "director",
        "marketing director",
        "chief marketing officer",
        "head of marketing",
        "digital marketing manager",
        "head of growth",
        "general manager",
        "principal dentist",
        "principal psychologist",
    ],
    3: [
        "head of seo",
        "growth manager",
        "patient experience manager",
    ],
    4: ["ceo", "chief executive officer", "vp marketing", "hr", "talent manager", "recruitment manager"],
}


def score_contact(contact: Contact, company_type: CompanyType) -> int:
    score = 0
    position = contact.contact_position.lower()
    priority_map = PRIORITIES.get(company_type, DEFAULT_PRIORITIES)
    for priority, titles in priority_map.items():
        if any(title in position for title in titles):
            score += max(0, 120 - priority * 30)
            break
    if contact.email_status == "valid":
        score += 25
    elif contact.email_status in {"unknown", "unverifiable"}:
        score += 10
    if contact.contact_country.lower() in {"australia", "au"}:
        score += 10
    if contact.contact_email and not contact.contact_email.startswith(("info@", "hello@", "support@")):
        score += 10
    return score


def select_top_contacts(
    contacts: list[Contact], company_type: CompanyType, max_count: int = 2
) -> list[Contact]:
    for contact in contacts:
        contact.contact_priority_score = score_contact(contact, company_type)
    sorted_contacts = sorted(contacts, key=lambda c: c.contact_priority_score, reverse=True)
    selected = sorted_contacts[:max_count]
    for contact in selected:
        contact.selected_for_outreach = True
    return selected
