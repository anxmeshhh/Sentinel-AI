"""What this Microsoft account can actually do - asked of Microsoft, not guessed.

Sentinel supports eight Microsoft 365 services, but three of them (Teams,
SharePoint, Planner) exist only in an *organizational* tenant. A personal
Microsoft account simply does not have them - which is a fact about the
account, not a failure of the integration. Reporting that as an error trains
people to distrust the product; reporting it as a capability teaches them
something true.

Detection is real. Microsoft answers the question itself:

    GET /organization        -> 200 for work/school; for a personal account it
                                returns 400 "not supported for MSA accounts",
                                which is Microsoft stating the account type
                                outright (verified directly against Graph).
    GET /me/licenseDetails   -> the assigned SKUs, which distinguish Business
                                from Enterprise from Education.

Nothing here keys off an email domain or a hardcoded list of users - a
@gmail.com address can be either kind, so the domain proves nothing.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger("sentinel.microsoft_capabilities")

GRAPH = "https://graph.microsoft.com/v1.0"
# Detection costs two Graph calls, and the answer only changes when a different
# account is connected - so it is cached against the account identity, which
# means connecting a new account invalidates it automatically.
_CACHE_TTL_SECONDS = 900
_cache: dict[tuple, tuple[float, "MicrosoftAccount"]] = {}


class AccountType(str, enum.Enum):
    PERSONAL = "personal"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"
    EDUCATION = "education"
    WORK_SCHOOL = "work_school"  # an org tenant whose SKU we do not recognise
    UNKNOWN = "unknown"  # detection could not run (offline, token expired)


_TYPE_LABEL = {
    AccountType.PERSONAL: "Personal Microsoft account",
    AccountType.BUSINESS: "Microsoft 365 Business",
    AccountType.ENTERPRISE: "Microsoft 365 Enterprise",
    AccountType.EDUCATION: "Microsoft 365 Education",
    AccountType.WORK_SCHOOL: "Microsoft 365 work or school account",
    AccountType.UNKNOWN: "Microsoft account",
}

# SKU fragments, most specific first. Education and Enterprise both contain
# tokens that would otherwise match Business, so order matters.
_SKU_RULES: tuple[tuple[AccountType, tuple[str, ...]], ...] = (
    (AccountType.EDUCATION, ("EDU", "_STUDENT", "_FACULTY", "M365EDU", "STANDARDWOFFPACK_IW")),
    (AccountType.ENTERPRISE, ("ENTERPRISEPACK", "ENTERPRISEPREMIUM", "SPE_E3", "SPE_E5", "DEVELOPERPACK", "ENTERPRISEPACKPLUS")),
    (AccountType.BUSINESS, ("BUSINESS", "SMB", "SPB", "O365_BUSINESS")),
)

# The three services that exist only inside an organizational tenant. Everything
# else works on any Microsoft account.
ORG_ONLY = ("teams", "sharepoint", "planner")

_SERVICES: tuple[tuple[str, str, str], ...] = (
    # (key, label, what Sentinel reads from it)
    ("outlook_mail", "Outlook Mail", "Subject, participants and flags — never message bodies"),
    ("outlook_calendar", "Outlook Calendar", "Meetings, attendees and conflicts"),
    ("teams", "Microsoft Teams", "Blockers, mentions and incidents forming in channels"),
    ("onedrive", "OneDrive", "File name, type and modified time — never file content"),
    ("sharepoint", "SharePoint", "Site and document activity across your organization"),
    ("onenote", "OneNote", "Notebook and page activity"),
    ("planner", "Microsoft Planner", "Plans and task progress across your organization"),
    ("todo", "Microsoft To Do", "Your personal tasks and due dates"),
)


@dataclass
class MicrosoftAccount:
    account_type: AccountType
    type_label: str
    tenant_name: str | None = None
    skus: list[str] = field(default_factory=list)
    detected: bool = True  # False when Graph could not be reached

    @property
    def is_organizational(self) -> bool:
        return self.account_type in (
            AccountType.BUSINESS, AccountType.ENTERPRISE,
            AccountType.EDUCATION, AccountType.WORK_SCHOOL,
        )


@dataclass
class ServiceCapability:
    key: str
    label: str
    description: str
    available: bool
    # A capability statement, never an error. "Available", or what it needs.
    status: str
    reason: str | None = None
    unlock: str | None = None


def _classify(skus: list[str]) -> AccountType:
    joined = " ".join(s.upper() for s in skus)
    for account_type, fragments in _SKU_RULES:
        if any(f in joined for f in fragments):
            return account_type
    # An org tenant that answered /organization but whose SKUs we don't know
    # (or a tenant where licenseDetails is not readable) is still organizational.
    return AccountType.WORK_SCHOOL


def detect_account(access_token: str, *, cache_key=None) -> MicrosoftAccount:
    """Ask Microsoft what kind of account this is. Never raises - a detection
    failure degrades to UNKNOWN, which the UI renders as "checking", not as an
    error."""
    if cache_key is not None:
        hit = _cache.get(cache_key)
        if hit and time.time() - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        org = httpx.get(f"{GRAPH}/organization", headers=headers, timeout=15.0)
    except Exception as exc:  # noqa: BLE001 - detection must never break a page
        logger.warning("microsoft_capability_detection_failed", error=str(exc)[:160])
        return MicrosoftAccount(AccountType.UNKNOWN, _TYPE_LABEL[AccountType.UNKNOWN], detected=False)

    if org.status_code != 200 or not (org.json().get("value") or []):
        # Microsoft's own answer: /organization is not supported for personal
        # (MSA) accounts. That is the authoritative signal, not the domain.
        account = MicrosoftAccount(AccountType.PERSONAL, _TYPE_LABEL[AccountType.PERSONAL])
    else:
        tenant = (org.json()["value"][0] or {}).get("displayName")
        skus: list[str] = []
        try:
            lic = httpx.get(f"{GRAPH}/me/licenseDetails", headers=headers, timeout=15.0)
            if lic.status_code == 200:
                skus = [s.get("skuPartNumber", "") for s in lic.json().get("value", [])]
        except Exception:  # noqa: BLE001 - SKUs only refine the label
            skus = []
        kind = _classify(skus)
        account = MicrosoftAccount(kind, _TYPE_LABEL[kind], tenant_name=tenant, skus=[s for s in skus if s])

    if cache_key is not None:
        _cache[cache_key] = (time.time(), account)
    return account


def capabilities_for(account: MicrosoftAccount) -> list[ServiceCapability]:
    """Every Microsoft service Sentinel supports, with an honest availability
    statement. Unavailable services are still listed - the point is to show what
    exists, what it needs, and how to get it."""
    out: list[ServiceCapability] = []
    for key, label, description in _SERVICES:
        org_only = key in ORG_ONLY

        if not account.detected:
            out.append(ServiceCapability(
                key, label, description, available=False,
                status="Checking availability…",
                reason="Sentinel couldn't reach Microsoft just now to confirm what this account includes.",
            ))
            continue

        if not org_only or account.is_organizational:
            out.append(ServiceCapability(key, label, description, available=True, status="Available"))
            continue

        # "a personal Microsoft account" reads naturally; lowercasing the whole
        # label would mangle the brand ("personal microsoft account").
        article = "an" if account.type_label[0].upper() in "AEIOU" else "a"
        out.append(ServiceCapability(
            key, label, description, available=False,
            status="Requires Microsoft 365 Business or Work/School",
            reason=(
                f"{label} is only available on organizational Microsoft 365 tenants. "
                f"You're connected with {article} {account.type_label}, which Microsoft "
                f"does not include {label} with."
            ),
            unlock="Connect a Microsoft 365 Business, Enterprise or Education (work/school) account to enable it.",
        ))
    return out
