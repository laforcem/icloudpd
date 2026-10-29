import json
from typing import Any
from unittest.mock import MagicMock

import requests

from icloudpd import deletion_review
from icloudpd.session_registry import SessionRegistry
from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.exceptions import (
    PyiCloudAPIResponseException,
    PyiCloudConnectionErrorException,
)
from pyicloud_ipd.services.photos import PhotoLibrary


def _library(records: list[dict[str, Any]]) -> tuple[PhotoLibrary, MagicMock]:
    lib = PhotoLibrary.__new__(PhotoLibrary)
    lib.service_endpoint = "https://ck.example/db"
    lib.params = {"dsid": "1"}
    lib.zone_id = {"zoneName": "PrimarySync"}
    session = MagicMock()
    session.post.return_value.json.return_value = {"records": records}
    lib.session = session
    return lib, session


def test_lookup_masters_posts_record_names_and_zone() -> None:
    lib, session = _library([{"recordName": "A", "fields": {}}])
    assert set(lib.lookup_masters(["A", "B"])) == {"A"}
    url = session.post.call_args.args[0]
    assert url.startswith("https://ck.example/db/records/lookup?")
    body = json.loads(session.post.call_args.kwargs["data"])
    assert body == {
        "records": [{"recordName": "A"}, {"recordName": "B"}],
        "zoneID": {"zoneName": "PrimarySync"},
    }


def test_lookup_masters_skips_server_errors() -> None:
    lib, _ = _library(
        [
            {"recordName": "A", "fields": {}},
            {"recordName": "B", "serverErrorCode": "NOT_FOUND"},
        ]
    )
    assert list(lib.lookup_masters(["A", "B"])) == ["A"]


def _res(size: int) -> dict[str, Any]:
    return {"value": {"size": size, "downloadURL": f"u{size}"}}


def test_thumbnail_field_prefers_jpeg_thumb() -> None:
    master = {"fields": {"resJPEGThumbRes": _res(9), "resJPEGMedRes": _res(1)}}
    assert deletion_review.thumbnail_field(master) == "resJPEGThumbRes"


def test_thumbnail_field_falls_back_to_smallest_jpeg() -> None:
    master = {"fields": {"resJPEGFullRes": _res(9), "resJPEGMedRes": _res(3)}}
    assert deletion_review.thumbnail_field(master) == "resJPEGMedRes"


def test_thumbnail_field_none_for_video_only_record() -> None:
    master = {"fields": {"resVidSmallRes": _res(5), "resOriginalRes": _res(50)}}
    assert deletion_review.thumbnail_field(master) is None


MASTER = {"fields": {"resJPEGThumbRes": {"value": {"size": 1, "downloadURL": "https://dl/x"}}}}


def _service(lookups: list[Any]) -> MagicMock:
    service = MagicMock(spec=PyiCloudService)
    lib = MagicMock()
    lib.lookup_masters.side_effect = lookups
    service.photos = lib
    service.session = MagicMock()
    service.session.get.return_value.content = b"JPEG"
    service.revalidate_token.return_value = True
    return service


def _err(code: str) -> PyiCloudAPIResponseException:
    return PyiCloudAPIResponseException("bad", code)


def test_fetch_thumbnail_returns_bytes() -> None:
    r = SessionRegistry()
    service = _service([{"R": MASTER}])
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) == b"JPEG"
    service.session.get.assert_called_once_with("https://dl/x")


def test_fetch_thumbnail_named_library() -> None:
    r = SessionRegistry()
    service = _service([])
    shared = MagicMock()
    shared.lookup_masters.return_value = {"R": MASTER}
    service.photos.private_libraries = {}
    service.photos.shared_libraries = {"SharedSync-1": shared}
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "SharedSync-1", "R", 1000.0) == b"JPEG"


def test_fetch_thumbnail_empty_slot_returns_none_without_calling_apple() -> None:
    r = SessionRegistry()
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None


def test_fetch_thumbnail_missing_master_or_field_returns_none() -> None:
    r = SessionRegistry()
    r.publish("u", _service([{}]))
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None


def test_fetch_thumbnail_421_refreshes_and_retries() -> None:
    r = SessionRegistry()
    service = _service([_err("421"), {"R": MASTER}])
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) == b"JPEG"
    assert service.revalidate_token.call_count == 1


def test_fetch_thumbnail_second_421_gives_up() -> None:
    r = SessionRegistry()
    service = _service([_err("421"), _err("421")])
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None


def test_fetch_thumbnail_other_code_gives_up_without_refresh() -> None:
    r = SessionRegistry()
    service = _service([_err("500")])
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None
    service.revalidate_token.assert_not_called()


def test_fetch_thumbnail_failed_refresh_returns_none() -> None:
    r = SessionRegistry()
    service = _service([_err("421")])
    service.revalidate_token.return_value = False
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None
    assert r.get("u") is None


def test_fetch_thumbnail_refresh_connection_error_returns_none() -> None:
    r = SessionRegistry()
    service = _service([_err("421")])
    service.revalidate_token.side_effect = requests.ConnectionError("down")
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None


def test_fetch_thumbnail_download_error_returns_none() -> None:
    r = SessionRegistry()
    service = _service([{"R": MASTER}])
    service.session.get.side_effect = requests.Timeout("slow")
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None


def test_fetch_thumbnail_rate_limit_respected() -> None:
    r = SessionRegistry()
    service = _service([_err("421"), _err("421"), _err("421")])
    service.revalidate_token.return_value = True
    r.publish("u", service)
    deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0)
    deletion_review.fetch_thumbnail(r, "u", "", "R", 1100.0)
    assert service.revalidate_token.call_count == 1


def test_fetch_thumbnail_pyicloud_connection_error_returns_none() -> None:
    r = SessionRegistry()
    service = _service([PyiCloudConnectionErrorException("down")])
    r.publish("u", service)
    assert deletion_review.fetch_thumbnail(r, "u", "", "R", 1000.0) is None
