import datetime
from types import SimpleNamespace

from icloudpd.session_expiry import earliest_relevant_expiry


def _cookie(name: str, expires: float | None) -> SimpleNamespace:
    return SimpleNamespace(name=name, expires=expires)


def test_earliest_relevant_expiry_picks_soonest_of_two_cookies() -> None:
    later = datetime.datetime(2024, 2, 11, tzinfo=datetime.timezone.utc).timestamp()
    sooner = datetime.datetime(2024, 1, 12, tzinfo=datetime.timezone.utc).timestamp()
    cookies = [
        _cookie("X_APPLE_WEB_KB-ONHCNAXFAIPPFDMR5UZVNO6NIMY", later),
        _cookie("X-APPLE-WEBAUTH-USER", sooner),
        _cookie("X-APPLE-WEBAUTH-LOGIN", None),
    ]

    result = earliest_relevant_expiry(cookies)

    assert result == datetime.datetime.fromtimestamp(sooner, tz=datetime.timezone.utc)


def test_earliest_relevant_expiry_ignores_unrelated_cookies() -> None:
    cookies = [_cookie("dslang", 9999999999.0), _cookie("site", 9999999999.0)]

    assert earliest_relevant_expiry(cookies) is None


def test_earliest_relevant_expiry_returns_none_when_no_expires_present() -> None:
    cookies = [_cookie("X-APPLE-WEBAUTH-USER", None)]

    assert earliest_relevant_expiry(cookies) is None
