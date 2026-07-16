import os
import sys
from logging import Logger

import waitress
from flask import Flask, Response, jsonify, make_response, render_template, request

from icloudpd.status import Status, StatusExchange
from pyicloud_ipd.base import session_file_path


def build_app(logger: Logger, _status_exchange: StatusExchange) -> Flask:
    app = Flask(__name__)
    app.logger = logger
    # for running in pyinstaller
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir is not None:
        app.template_folder = os.path.join(bundle_dir, "templates")
        app.static_folder = os.path.join(bundle_dir, "static")

    @app.route("/")
    def index() -> Response | str:
        return render_template("index.html")

    @app.route("/status", methods=["GET"])
    def get_status() -> Response | str:
        _status = _status_exchange.get_status()
        _global_config = _status_exchange.get_global_config()
        _user_configs = _status_exchange.get_user_configs()
        _current_user = _status_exchange.get_current_user()
        _progress = _status_exchange.get_progress()
        _error = _status_exchange.get_error()

        if _status == Status.IDLE:
            return render_template(
                "no_input.html",
                status=_status,
                error=_error,
                progress=_progress,
                global_config=vars(_global_config) if _global_config else None,
                user_configs=[vars(uc) for uc in _user_configs] if _user_configs else [],
                current_user=_current_user,
            )
        if _status == Status.AWAITING_MFA_TRIGGER:
            return render_template("mfa_trigger.html", error=_error, current_user=_current_user)
        if _status == Status.AWAITING_MFA_CODE:
            return render_template("code.html", error=_error, current_user=_current_user)
        if _status == Status.AWAITING_PASSWORD:
            return render_template("password.html", error=_error, current_user=_current_user)
        return render_template("status.html", status=_status)

    @app.route("/status.json", methods=["GET"])
    def get_status_json() -> Response:
        return jsonify(
            {
                "status": str(_status_exchange.get_status()),
                "error": _status_exchange.get_error(),
                "current_user": _status_exchange.get_current_user(),
            }
        )

    @app.route("/code", methods=["POST"])
    def set_code() -> Response | str:
        _current_user = _status_exchange.get_current_user()
        code = request.form.get("code")
        if code is not None:
            if _status_exchange.set_payload(code):
                return render_template("code_submitted.html", current_user=_current_user)
        else:
            logger.error(f"cannot find code in request {request.form}")
        return make_response(
            render_template(
                "auth_error.html",
                type="Two-Factor Code",
                current_user=_current_user,
            ),
            400,
        )  # incorrect code

    @app.route("/password", methods=["POST"])
    def set_password() -> Response | str:
        _current_user = _status_exchange.get_current_user()
        password = request.form.get("password")
        if password is not None:
            if _status_exchange.set_payload(password):
                return render_template("password_submitted.html", current_user=_current_user)
        else:
            logger.error(f"cannot find password in request {request.form}")
        return make_response(
            render_template("auth_error.html", type="password", current_user=_current_user),
            400,
        )  # incorrect code

    @app.route("/trigger-push", methods=["POST"])
    def trigger_push() -> Response:
        if _status_exchange.trigger_mfa():
            return make_response("", 204)
        return make_response("Not awaiting an MFA trigger", 409)

    @app.route("/force-reauth", methods=["POST"])
    def force_reauth() -> Response:
        username = request.form.get("username")
        if not username:
            return make_response("Missing username", 400)

        matching = next(
            (uc for uc in _status_exchange.get_user_configs() if uc.username == username),
            None,
        )
        if matching is None:
            return make_response("Unknown username", 404)

        path = session_file_path(matching.cookie_directory, matching.username)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as ex:
            logger.warning("Could not remove session file %s: %s", path, ex)

        _status_exchange.get_progress().resume = True
        return make_response("", 204)

    @app.route("/resume", methods=["POST"])
    def resume() -> Response | str:
        _status_exchange.get_progress().resume = True
        return make_response("Ok", 200)

    @app.route("/cancel", methods=["POST"])
    def cancel() -> Response | str:
        _status_exchange.get_progress().cancel = True
        return make_response("Ok", 200)

    return app


def serve_app(logger: Logger, _status_exchange: StatusExchange) -> None:
    logger.debug("Starting web server...")
    return waitress.serve(build_app(logger, _status_exchange))
