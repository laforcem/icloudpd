import inspect
import os
import threading
from typing import List
from unittest import TestCase

import pytest
from vcr import VCR

from foundation.core import constant
from icloudpd.authentication import authenticator
from icloudpd.base import dummy_password_writter
from icloudpd.logger import setup_logger
from icloudpd.mfa_provider import MFAProvider
from icloudpd.server import build_app
from icloudpd.status import Status, StatusExchange
from tests.helpers import (
    calc_cookie_dir,
    calc_vcr_dir,
    path_from_project_root,
    recreate_path,
    wait_for_status,
)

vcr = VCR(decode_compressed_response=True, record_mode="none")

USERNAME = "jdoe@gmail.com"
CLIENT_ID = "EC5646DE-9423-11E8-BF21-14109FE0B321"


class WebuiAuthFlowIntegrationTestCase(TestCase):
    """Drives a real PyiCloudService (VCR-mocked) through authenticator()'s
    webui path and the real Flask WebUI app together, the way a human or the
    Telegram bot actually drives /trigger-push and /code - closing the gap
    between the auth-thread tests (test_authentication_webui.py, which fake
    icloud) and the HTTP-layer tests (test_server.py, which fake the auth
    thread). See https://github.com/laforcem/icloudpd/issues/12.
    """

    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")
        self.vcr_path = calc_vcr_dir(self.root_path)

    def test_full_auth_flow_via_webui_valid_code(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = calc_cookie_dir(base_dir)
        for dir in [base_dir, cookie_dir]:
            recreate_path(dir)

        status_exchange = StatusExchange()
        status_exchange.set_current_user(USERNAME)
        logger = setup_logger()
        accepted: List[None] = []
        rejected: List[str] = []
        errors: List[BaseException] = []

        def run_authenticator() -> None:
            try:
                with vcr.use_cassette(os.path.join(self.vcr_path, "2fa_flow_valid_code.yml")):
                    authenticator(
                        logger,
                        "com",
                        {"test": (constant("dummy"), dummy_password_writter)},
                        MFAProvider.WEBUI,
                        status_exchange,
                        USERNAME,
                        lambda: None,
                        lambda: accepted.append(None),
                        lambda error: rejected.append(error),
                        None,
                        cookie_dir,
                        CLIENT_ID,
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=run_authenticator, daemon=True)
        thread.start()

        wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)

        client = build_app(logger, status_exchange).test_client()

        trigger_response = client.post("/trigger-push")
        assert trigger_response.status_code == 200
        assert trigger_response.json == {"current_user": USERNAME}

        wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)

        code_response = client.post("/code", data={"code": "654321"})
        assert code_response.status_code == 200

        thread.join(timeout=2.0)

        assert not thread.is_alive(), "authenticator thread did not finish"
        assert errors == []
        assert status_exchange.get_status() == Status.IDLE
        assert accepted == [None]
        assert rejected == []

    def test_full_auth_flow_via_webui_invalid_code(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = calc_cookie_dir(base_dir)
        for dir in [base_dir, cookie_dir]:
            recreate_path(dir)

        status_exchange = StatusExchange()
        status_exchange.set_current_user(USERNAME)
        logger = setup_logger()
        accepted: List[None] = []
        rejected: List[str] = []
        errors: List[BaseException] = []

        def run_authenticator() -> None:
            try:
                with vcr.use_cassette(os.path.join(self.vcr_path, "2fa_flow_invalid_code.yml")):
                    authenticator(
                        logger,
                        "com",
                        {"test": (constant("dummy"), dummy_password_writter)},
                        MFAProvider.WEBUI,
                        status_exchange,
                        USERNAME,
                        lambda: None,
                        lambda: accepted.append(None),
                        lambda error: rejected.append(error),
                        None,
                        cookie_dir,
                        CLIENT_ID,
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=run_authenticator, daemon=True)
        thread.start()

        wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)

        client = build_app(logger, status_exchange).test_client()

        trigger_response = client.post("/trigger-push")
        assert trigger_response.status_code == 200

        wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)

        code_response = client.post("/code", data={"code": "901431"})
        assert code_response.status_code == 200

        # request_2fa_web() loops back to AWAITING_MFA_TRIGGER on a rejected
        # code rather than exiting (unlike the console provider), so the
        # authenticator thread is left blocked waiting for a fresh trigger -
        # it never returns. That's fine: it's a daemon thread and the cassette
        # only has one validation attempt recorded, so we don't join() it.
        wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)

        assert errors == []
        assert status_exchange.get_error() == "Failed to verify two-factor authentication code"
        assert accepted == []
        assert rejected == ["Failed to verify two-factor authentication code"]
