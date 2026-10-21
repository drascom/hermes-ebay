from __future__ import annotations

import json
import stat
import urllib.error
from argparse import Namespace
from pathlib import Path

import pytest

from hermes_ebay import ebay_cli
from hermes_ebay import ebay_client as api


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("EBAY_APP_ID", "fake-app")
    monkeypatch.setenv("EBAY_CERT_ID", "fake-cert")
    monkeypatch.setenv("EBAY_RUNAME", "fake-runame")
    return tmp_path


def test_authorization_url_has_ru_name_and_read_scopes(home: Path) -> None:
    url = api.authorization_url("state-value")
    assert "client_id=fake-app" in url
    assert "redirect_uri=fake-runame" in url
    assert "sell.fulfillment.readonly" in url
    assert "fake-cert" not in url


def test_token_store_is_private_and_status_does_not_expose_token(home: Path) -> None:
    api._save_token({"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_at": 123})
    assert stat.S_IMODE(api.token_path().stat().st_mode) == 0o600
    output = json.dumps(api.monitor_status({}))
    assert "access-secret" not in output
    assert "refresh-secret" not in output


def test_refreshes_expiring_token(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api._save_token({"access_token": "old", "refresh_token": "refresh", "expires_at": 0})
    monkeypatch.setattr(api, "_token_request", lambda fields: {"access_token": "new", "expires_at": 9999999999})
    assert api.access_token() == "new"
    assert api.load_token()["refresh_token"] == "refresh"


def test_orders_allowlist_omits_buyer_and_titles(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "request", lambda *_args, **_kwargs: {"orders": [{
        "orderId": "FAKE-1", "orderFulfillmentStatus": "NOT_STARTED", "buyer": {"username": "private"},
        "lineItems": [{"title": "private title"}],
    }]})
    output = json.dumps(api.orders({}))
    assert "FAKE-1" in output
    assert "private" not in output
    assert "title" not in output


def test_monitor_first_poll_baselines_then_dedupes(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"status": "NOT_STARTED"}
    monkeypatch.setattr(api, "orders", lambda _args: {"orders": [{"orderId": "FAKE-1", "orderFulfillmentStatus": state["status"]}]})
    monkeypatch.setattr(api, "returns", lambda _args: {"returns": []})
    monkeypatch.setattr(api, "cancellations", lambda _args: {"cancellations": []})
    assert api.monitor_poll() == []
    assert api.monitor_poll() == []
    state["status"] = "FULFILLED"
    assert api.monitor_poll() == ["eBay order: FAKE-1 — FULFILLED"]
    assert api.monitor_poll() == []
    raw = (api.data_dir() / "monitor.sqlite3").read_bytes()
    assert b"FAKE-1" not in raw


def test_disconnect_removes_token(home: Path) -> None:
    api._save_token({"access_token": "x", "expires_at": 1})
    assert api.disconnect() is True
    assert api.disconnect() is False


def test_setup_writes_profile_env_mode_600(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "fake-cert")
    ebay_cli._setup(Namespace(app_id="fake-app", runame="fake-runame", cert_id=None))
    env = home / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "EBAY_CERT_ID=fake-cert" in env.read_text()


def test_connect_rejects_redirect_with_wrong_state(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("secrets.token_urlsafe", lambda _n: "expected-state")
    monkeypatch.setattr("webbrowser.open", lambda _url: True)
    args = Namespace(no_browser=True, code="https://example.test/callback?code=fake&state=wrong")
    with pytest.raises(SystemExit, match="state mismatch"):
        ebay_cli._connect(args)


def test_monitor_enable_is_idempotent(home: Path) -> None:
    (api.data_dir() / "cron-job-id").write_text("fake-job")
    with pytest.raises(SystemExit, match="already enabled"):
        ebay_cli._install_monitor("local")


def test_api_http_error_does_not_include_auth_header(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "access_token", lambda: "never-print-me")
    error = urllib.error.HTTPError("https://api.ebay.com/x", 401, "no", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(RuntimeError) as exc:
        api.request("/x")
    assert "never-print-me" not in str(exc.value)
