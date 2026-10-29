import pytest
import responses
from bot.control_client import ControlClient, StaleBatchError, SyncingError

BASE = "http://icloudpd:2012"


@responses.activate
def test_control_client_sends_bearer_and_maps_409_503() -> None:
    client = ControlClient(BASE, "sekret")
    responses.get(f"{BASE}/v1/entries", json={"entries": [{"key": "k"}]})
    assert client.entries() == [{"key": "k"}]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer sekret"

    responses.post(
        f"{BASE}/v1/entries/k/held/r1/keep",
        json={"batch_token": "new", "keep_token": "kk"},
        status=409,
    )
    with pytest.raises(StaleBatchError) as stale:
        client.set_keep("k", "r1", True, "old")
    assert (stale.value.batch_token, stale.value.keep_token) == ("new", "kk")

    responses.post(f"{BASE}/v1/entries/k/resolve", json={"reason": "syncing"}, status=503)
    with pytest.raises(SyncingError):
        client.resolve("k", "apply", "tok")


@responses.activate
def test_page_and_resolve_and_keep_bodies() -> None:
    client = ControlClient(BASE + "/", "t")
    responses.get(f"{BASE}/v1/entries/k/held?page=2", json={"page": 2})
    assert client.page("k", 2) == {"page": 2}
    responses.post(f"{BASE}/v1/entries/k/held/r%2F1/keep", json={"total": 1, "kept_count": 1})
    assert client.set_keep("k", "r/1", True, "tok")["kept_count"] == 1
    assert responses.calls[-1].request.body == b'{"keep": true, "batch_token": "tok"}'
    responses.post(f"{BASE}/v1/entries/k/resolve", json={"approved": 1, "rejected": 0})
    assert client.resolve("k", "keep_all", "tok") == {"approved": 1, "rejected": 0}


@responses.activate
def test_thumbnail_bytes_or_none() -> None:
    client = ControlClient(BASE, "t")
    responses.get(f"{BASE}/v1/entries/k/held/r1/thumbnail", body=b"jpg", status=200)
    assert client.thumbnail("k", "r1") == b"jpg"
    responses.get(
        f"{BASE}/v1/entries/k/held/r2/thumbnail",
        json={"reason": "thumbnail_unavailable"},
        status=503,
    )
    assert client.thumbnail("k", "r2") is None


@responses.activate
def test_resolve_apply_sends_keep_token_and_keep_all_does_not() -> None:
    client = ControlClient(BASE, "t")
    responses.post(f"{BASE}/v1/entries/k/resolve", json={"approved": 1, "rejected": 0})
    client.resolve("k", "apply", "tok", "kt")
    assert responses.calls[-1].request.body == (
        b'{"action": "apply", "batch_token": "tok", "keep_token": "kt"}'
    )
    client.resolve("k", "keep_all", "tok")
    assert responses.calls[-1].request.body == b'{"action": "keep_all", "batch_token": "tok"}'
