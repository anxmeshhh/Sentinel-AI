"""Microsoft account capability detection.

The product rule these protect: a service this account type does not include is
a CAPABILITY statement, never an error. Users must be able to see what exists,
what it needs and how to unlock it - and the answer must come from Microsoft,
not from guessing at an email domain.
"""

import pytest

from app.services import microsoft_capabilities as mc
from app.services.microsoft_capabilities import (
    ORG_ONLY,
    AccountType,
    MicrosoftAccount,
    capabilities_for,
    detect_account,
)


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    mc._cache.clear()
    yield
    mc._cache.clear()


# ------------------------------------------------------------- detection

def test_personal_account_detected_from_microsofts_own_answer(monkeypatch):
    """Graph replies 400 "not supported for MSA accounts" for a personal
    account - that is Microsoft stating the type, and what we key off."""
    def fake_get(url, **kw):
        assert "/organization" in url
        return _Resp(400, {"error": {"code": "BadRequest",
                                     "message": "This API is not supported for MSA accounts"}})

    monkeypatch.setattr(mc.httpx, "get", fake_get)
    acct = detect_account("tok")
    assert acct.account_type is AccountType.PERSONAL
    assert acct.is_organizational is False
    assert acct.detected is True  # detection SUCCEEDED - it is genuinely personal


@pytest.mark.parametrize(
    "sku,expected",
    [
        ("ENTERPRISEPACK", AccountType.ENTERPRISE),
        ("SPE_E5", AccountType.ENTERPRISE),
        ("O365_BUSINESS_PREMIUM", AccountType.BUSINESS),
        ("SPB", AccountType.BUSINESS),
        ("M365EDU_A3", AccountType.EDUCATION),
        ("STANDARDWOFFPACK_IW_STUDENT", AccountType.EDUCATION),
    ],
)
def test_work_school_flavours_come_from_real_skus(monkeypatch, sku, expected):
    def fake_get(url, **kw):
        if "/organization" in url:
            return _Resp(200, {"value": [{"displayName": "Contoso Ltd"}]})
        return _Resp(200, {"value": [{"skuPartNumber": sku}]})

    monkeypatch.setattr(mc.httpx, "get", fake_get)
    acct = detect_account("tok")
    assert acct.account_type is expected
    assert acct.is_organizational is True
    assert acct.tenant_name == "Contoso Ltd"


def test_org_tenant_with_unknown_sku_is_still_organizational(monkeypatch):
    def fake_get(url, **kw):
        if "/organization" in url:
            return _Resp(200, {"value": [{"displayName": "Contoso"}]})
        return _Resp(200, {"value": [{"skuPartNumber": "SOMETHING_NEW_2027"}]})

    monkeypatch.setattr(mc.httpx, "get", fake_get)
    acct = detect_account("tok")
    assert acct.account_type is AccountType.WORK_SCHOOL
    assert acct.is_organizational is True  # Teams should still be offered


def test_unreachable_graph_degrades_to_unknown_not_an_error(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(mc.httpx, "get", boom)
    acct = detect_account("tok")
    assert acct.account_type is AccountType.UNKNOWN and acct.detected is False


def test_detection_is_cached_per_account_and_reruns_when_it_changes(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        return _Resp(400, {"error": {"message": "not supported for MSA accounts"}})

    monkeypatch.setattr(mc.httpx, "get", fake_get)
    detect_account("tok", cache_key=("c1", "a@x.com"))
    detect_account("tok", cache_key=("c1", "a@x.com"))
    assert calls["n"] == 1  # second call served from cache

    # A DIFFERENT account connected -> different key -> detected afresh.
    detect_account("tok", cache_key=("c1", "b@contoso.com"))
    assert calls["n"] == 2


# ---------------------------------------------------------- capabilities

def test_personal_account_shows_every_service_with_honest_states():
    caps = capabilities_for(MicrosoftAccount(AccountType.PERSONAL, "Personal Microsoft account"))
    # ALL services are listed - nothing is hidden.
    assert len(caps) == 8
    available = {c.key for c in caps if c.available}
    locked = {c.key for c in caps if not c.available}
    assert locked == set(ORG_ONLY)
    assert available == {"outlook_mail", "outlook_calendar", "onedrive", "onenote", "todo"}

    teams = next(c for c in caps if c.key == "teams")
    assert teams.status == "Requires Microsoft 365 Business or Work/School"
    # It teaches: what, why, and how to unlock - and never says "error".
    assert "organizational Microsoft 365 tenants" in teams.reason
    assert "a Personal Microsoft account" in teams.reason
    assert "work/school" in teams.unlock.lower()
    assert "error" not in (teams.status + teams.reason).lower()


def test_business_account_unlocks_everything():
    caps = capabilities_for(MicrosoftAccount(AccountType.BUSINESS, "Microsoft 365 Business", tenant_name="Contoso"))
    assert all(c.available for c in caps)
    assert {c.status for c in caps} == {"Available"}


def test_education_account_unlocks_everything():
    caps = capabilities_for(MicrosoftAccount(AccountType.EDUCATION, "Microsoft 365 Education"))
    assert all(c.available for c in caps)


def test_undetected_account_says_checking_not_unavailable():
    """If Graph was unreachable we must not claim a service is unavailable -
    that would be a guess presented as a fact."""
    caps = capabilities_for(MicrosoftAccount(AccountType.UNKNOWN, "Microsoft account", detected=False))
    assert all(c.status == "Checking availability…" for c in caps)
    assert all("couldn't reach Microsoft" in (c.reason or "") for c in caps)


def test_reason_reads_naturally_for_every_account_type():
    """Guards the article/casing bug: "a personal microsoft account" is wrong."""
    for kind, label in (
        (AccountType.PERSONAL, "Personal Microsoft account"),
        (AccountType.UNKNOWN, "Microsoft account"),
    ):
        acct = MicrosoftAccount(kind, label)
        if kind is AccountType.UNKNOWN:
            continue
        teams = next(c for c in capabilities_for(acct) if c.key == "teams")
        assert "a Personal Microsoft account" in teams.reason
        assert "microsoft account" not in teams.reason  # never lowercased brand
