import os

from flask.testing import FlaskClient

from icloudpd.config import UserConfig
from icloudpd.logger import setup_logger
from icloudpd.server import build_app
from icloudpd.status import Status, StatusExchange
from pyicloud_ipd.file_match import FileMatchPolicy
from pyicloud_ipd.live_photo_mov_filename_policy import LivePhotoMovFilenamePolicy
from pyicloud_ipd.raw_policy import RawTreatmentPolicy
from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize


def make_client(status_exchange: StatusExchange) -> FlaskClient:
    app = build_app(setup_logger(), status_exchange)
    return app.test_client()


def test_status_idle_renders_no_input() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.get("/status")

    assert response.status_code == 200
    assert b"No input is needed" in response.data


def test_status_awaiting_mfa_trigger_renders_trigger_prompt() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    client = make_client(status_exchange)

    response = client.get("/status")

    assert response.status_code == 200
    assert b"Two-factor authentication is required" in response.data
    assert b"/trigger-push" in response.data


def test_status_awaiting_mfa_code_renders_code_form() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    client = make_client(status_exchange)

    response = client.get("/status")

    assert response.status_code == 200
    assert b"Two-Factor code" in response.data


def test_status_json_reports_current_state() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.set_current_user("jdoe@icloud.com")
    client = make_client(status_exchange)

    response = client.get("/status.json")

    assert response.status_code == 200
    assert response.json == {
        "status": "AWAITING_MFA_TRIGGER",
        "error": None,
        "current_user": "jdoe@icloud.com",
    }


def test_trigger_push_moves_awaiting_trigger_to_awaiting_code() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    client = make_client(status_exchange)

    response = client.post("/trigger-push")

    assert response.status_code == 204
    assert status_exchange.get_status() == Status.AWAITING_MFA_CODE


def test_trigger_push_rejects_when_nothing_pending() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.post("/trigger-push")

    assert response.status_code == 409
    assert status_exchange.get_status() == Status.IDLE


def test_code_endpoint_accepts_code_when_awaiting() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    client = make_client(status_exchange)

    response = client.post("/code", data={"code": "123456"})

    assert response.status_code == 200
    assert status_exchange.get_status() == Status.SUBMITTED_MFA_CODE


def _user_config(username: str, cookie_directory: str) -> UserConfig:
    return UserConfig(
        username=username,
        password=None,
        directory="/tmp/does-not-matter",
        auth_only=True,
        cookie_directory=cookie_directory,
        sizes=[AssetVersionSize.ORIGINAL],
        live_photo_size=LivePhotoVersionSize.ORIGINAL,
        recent=None,
        until_found=None,
        albums=[],
        list_albums=False,
        library="PrimarySync",
        list_libraries=False,
        skip_videos=False,
        skip_live_photos=False,
        xmp_sidecar=False,
        force_size=False,
        auto_delete=False,
        folder_structure="{:%Y/%m/%d}",
        set_exif_datetime=False,
        notification_script=None,
        delete_after_download=False,
        keep_icloud_recent_days=None,
        dry_run=False,
        keep_unicode_in_filenames=False,
        live_photo_mov_filename_policy=LivePhotoMovFilenamePolicy.SUFFIX,
        align_raw=RawTreatmentPolicy.AS_IS,
        file_match_policy=FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX,
        skip_created_before=None,
        skip_created_after=None,
        skip_photos=False,
    )


def test_force_reauth_deletes_session_file_and_wakes_watch_loop(tmp_path: object) -> None:
    cookie_dir = str(tmp_path)
    session_path = os.path.join(cookie_dir, "jdoegmailcom.session")
    with open(session_path, "w", encoding="utf-8") as f:
        f.write("{}")

    status_exchange = StatusExchange()
    status_exchange.set_user_configs([_user_config("jdoe@gmail.com", cookie_dir)])
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={"username": "jdoe@gmail.com"})

    assert response.status_code == 204
    assert not os.path.exists(session_path)
    assert status_exchange.get_progress().resume is True


def test_force_reauth_is_a_no_op_when_session_file_absent(tmp_path: object) -> None:
    cookie_dir = str(tmp_path)
    status_exchange = StatusExchange()
    status_exchange.set_user_configs([_user_config("jdoe@gmail.com", cookie_dir)])
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={"username": "jdoe@gmail.com"})

    assert response.status_code == 204
    assert status_exchange.get_progress().resume is True


def test_force_reauth_rejects_unknown_username() -> None:
    status_exchange = StatusExchange()
    status_exchange.set_user_configs([_user_config("jdoe@gmail.com", "/tmp/wherever")])
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={"username": "unknown@gmail.com"})

    assert response.status_code == 404
    assert status_exchange.get_progress().resume is False


def test_force_reauth_rejects_missing_username() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={})

    assert response.status_code == 400
