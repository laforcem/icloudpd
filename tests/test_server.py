import logging
import os
from unittest import mock

from flask.testing import FlaskClient

from icloudpd.config import GlobalConfig, UserConfig
from icloudpd.log_level import LogLevel
from icloudpd.logger import setup_logger
from icloudpd.mfa_provider import MFAProvider
from icloudpd.password_provider import PasswordProvider
from icloudpd.server import build_app, serve_app
from icloudpd.status import Status, StatusExchange
from pyicloud_ipd.file_match import FileMatchPolicy
from pyicloud_ipd.live_photo_mov_filename_policy import LivePhotoMovFilenamePolicy
from pyicloud_ipd.raw_policy import RawTreatmentPolicy
from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize


def make_client(status_exchange: StatusExchange) -> FlaskClient:
    app = build_app(setup_logger(), status_exchange)
    return app.test_client()


def make_global_config(password_providers: list[PasswordProvider]) -> GlobalConfig:
    return GlobalConfig(
        help=False,
        version=False,
        use_os_locale=False,
        only_print_filenames=False,
        log_level=LogLevel.DEBUG,
        no_progress_bar=False,
        threads_num=1,
        domain="com",
        watch_with_interval=None,
        password_providers=password_providers,
        mfa_provider=MFAProvider.WEBUI,
        webui_port=2011,
    )


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
    status_exchange.set_global_config(make_global_config([PasswordProvider.PARAMETER]))
    client = make_client(status_exchange)

    response = client.get("/status.json")

    assert response.status_code == 200
    assert response.json == {
        "status": "AWAITING_MFA_TRIGGER",
        "error": None,
        "current_user": "jdoe@icloud.com",
        "password_requires_manual_entry": False,
    }


def test_status_json_flags_manual_entry_when_webui_is_a_password_provider() -> None:
    status_exchange = StatusExchange()
    status_exchange.set_global_config(make_global_config([PasswordProvider.WEBUI]))
    client = make_client(status_exchange)

    response = client.get("/status.json")

    assert response.json is not None
    assert response.json["password_requires_manual_entry"] is True


def test_status_json_flags_manual_entry_when_webui_is_a_fallback_provider() -> None:
    status_exchange = StatusExchange()
    status_exchange.set_global_config(
        make_global_config([PasswordProvider.PARAMETER, PasswordProvider.WEBUI])
    )
    client = make_client(status_exchange)

    response = client.get("/status.json")

    assert response.json is not None
    assert response.json["password_requires_manual_entry"] is True


def test_status_json_defaults_to_manual_entry_when_global_config_unset() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.get("/status.json")

    assert response.json is not None
    assert response.json["password_requires_manual_entry"] is True


def test_trigger_push_moves_awaiting_trigger_to_awaiting_code() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.set_current_user("jdoe@icloud.com")
    client = make_client(status_exchange)

    response = client.post("/trigger-push")

    assert response.status_code == 200
    assert response.json == {"current_user": "jdoe@icloud.com"}
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
        password_file=None,
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


def test_serve_app_logs_url_even_if_logger_was_left_disabled(caplog: object) -> None:
    # The "icloudpd" logger is a process-wide singleton shared across the
    # whole test suite (see the comment in base.py's create_logger()): a
    # test exercising --only-print-filenames sets logger.disabled = True
    # and only resets it the next time create_logger() runs. Under
    # pytest-xdist, such a test can land in the same worker just before
    # this one, without the reset in between - serve_app()'s startup URL
    # log must not silently disappear because of that.
    status_exchange = StatusExchange()
    logger = setup_logger()
    logger.disabled = True

    with (
        mock.patch("icloudpd.server.waitress.serve") as mock_serve,
        caplog.at_level(logging.INFO, logger=logger.name),  # type: ignore[attr-defined]
    ):
        serve_app(logger, status_exchange, host="0.0.0.0", port=9091)

    assert "http://localhost:9091/" in caplog.text  # type: ignore[attr-defined]
    mock_serve.assert_called_once()


def test_serve_app_logs_url_before_blocking_on_waitress(caplog: object) -> None:
    status_exchange = StatusExchange()
    logger = setup_logger()

    with (
        mock.patch("icloudpd.server.waitress.serve") as mock_serve,
        caplog.at_level(logging.INFO, logger=logger.name),  # type: ignore[attr-defined]
    ):
        serve_app(logger, status_exchange, host="0.0.0.0", port=9090)

    assert "http://localhost:9090/" in caplog.text  # type: ignore[attr-defined]
    mock_serve.assert_called_once()
    _, kwargs = mock_serve.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9090
