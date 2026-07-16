from flask.testing import FlaskClient

from icloudpd.logger import setup_logger
from icloudpd.server import build_app
from icloudpd.status import Status, StatusExchange


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
