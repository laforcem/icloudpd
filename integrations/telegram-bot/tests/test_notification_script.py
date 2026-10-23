import importlib.util
import io
from pathlib import Path
from types import ModuleType

import requests
import responses

_SCRIPT = Path(__file__).resolve().parents[1] / "notification_script.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("notification_script", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(monkeypatch: object, module: ModuleType) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO('{"event_type": "x"}'))  # type: ignore[attr-defined]
    return int(module.main())


@responses.activate
def test_returns_zero_when_bot_accepts_event(monkeypatch: object) -> None:
    module = _load()
    responses.add(responses.POST, module.NOTIFY_URL, status=204)

    assert _run(monkeypatch, module) == 0


@responses.activate
def test_returns_nonzero_when_bot_is_unreachable(monkeypatch: object) -> None:
    module = _load()
    responses.add(responses.POST, module.NOTIFY_URL, body=requests.ConnectionError("down"))

    assert _run(monkeypatch, module) != 0


@responses.activate
def test_returns_nonzero_when_bot_rejects_event(monkeypatch: object) -> None:
    module = _load()
    responses.add(responses.POST, module.NOTIFY_URL, status=500)

    assert _run(monkeypatch, module) != 0
