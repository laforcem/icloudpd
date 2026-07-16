import responses

from bot.icloudpd_client import IcloudpdClient


@responses.activate
def test_trigger_push_success() -> None:
    responses.add(
        responses.POST,
        "http://icloudpd:8080/trigger-push",
        json={"current_user": "jdoe@icloud.com"},
        status=200,
    )
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.trigger_push() == "jdoe@icloud.com"


@responses.activate
def test_trigger_push_conflict() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/trigger-push", status=409)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.trigger_push() is None


@responses.activate
def test_submit_code_success() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/code", status=200)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.submit_code("123456") is True


@responses.activate
def test_submit_code_rejected() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/code", status=400)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.submit_code("000000") is False


@responses.activate
def test_get_status_parses_json() -> None:
    responses.add(
        responses.GET,
        "http://icloudpd:8080/status.json",
        json={"status": "AWAITING_MFA_TRIGGER", "error": None, "current_user": "jdoe@icloud.com"},
        status=200,
    )
    client = IcloudpdClient("http://icloudpd:8080")

    status = client.get_status()

    assert status.status == "AWAITING_MFA_TRIGGER"
    assert status.error is None
    assert status.current_user == "jdoe@icloud.com"


@responses.activate
def test_force_reauth_success() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/force-reauth", status=204)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.force_reauth("jdoe@icloud.com") is True


@responses.activate
def test_force_reauth_unknown_username() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/force-reauth", status=404)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.force_reauth("unknown@icloud.com") is False
