"""MSME statutory due dates (MSMED Act, section 15). Pure functions.

Applies to Udyam-registered micro and small enterprises that are manufacturers or service
providers (traders are excluded). Due date = acceptance date (GR / SES) + the agreed term,
capped at 45 days; 15 days if there is no written agreement. Interest exposure (section 16)
and the tax-deduction rule come with the MSME guardian in Phase 3.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core.enums import EnterpriseType, MsmeCategory

MAX_TERM_DAYS = 45
NO_AGREEMENT_DAYS = 15


def msme_eligible(msme_category: str, enterprise_type: str) -> bool:
    return msme_category in (MsmeCategory.MICRO, MsmeCategory.SMALL) and enterprise_type != EnterpriseType.TRADER


def statutory_due_date(accepted: date, terms_days: int, written_agreement: bool,
                       max_term: int = MAX_TERM_DAYS, no_agreement: int = NO_AGREEMENT_DAYS) -> date:
    days = min(terms_days, max_term) if written_agreement else no_agreement
    return accepted + timedelta(days=days)
