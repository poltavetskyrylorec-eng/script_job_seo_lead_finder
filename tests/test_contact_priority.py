from __future__ import annotations

from dabud_job_agent.agents.contact_selector import score_contact, select_top_contacts
from dabud_job_agent.models import CompanyType, Contact


def test_contact_priority_prefers_decision_maker_and_valid_email() -> None:
    c1 = Contact(
        run_id="1",
        company_domain="acme.com",
        company_name="Acme",
        contact_full_name="Alex CEO",
        contact_email="alex@acme.com",
        email_status="valid",
        contact_position="CEO",
        contact_country="Australia",
    )
    c2 = Contact(
        run_id="1",
        company_domain="acme.com",
        company_name="Acme",
        contact_full_name="Jamie SEO",
        contact_email="info@acme.com",
        email_status="unknown",
        contact_position="SEO Specialist",
        contact_country="Australia",
    )
    assert score_contact(c1, CompanyType.END_CLIENT) > score_contact(c2, CompanyType.END_CLIENT)


def test_select_top_contacts_applies_max_count() -> None:
    contacts = [
        Contact(
            run_id="1",
            company_domain="acme.com",
            company_name="Acme",
            contact_full_name=f"Contact {idx}",
            contact_email=f"user{idx}@acme.com",
            email_status="valid",
            contact_position="Head of Marketing",
            contact_country="Australia",
        )
        for idx in range(5)
    ]
    selected = select_top_contacts(contacts, CompanyType.END_CLIENT, max_count=2)
    assert len(selected) == 2
    assert all(item.selected_for_outreach for item in selected)
