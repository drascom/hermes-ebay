"""Small, dependency-free, read-only eBay API client."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
)
API = "https://api.ebay.com"
AUTH = "https://auth.ebay.com/oauth2/authorize"
OAUTH_ENDPOINT = "https://api.ebay.com/identity/v1/oauth2/token"


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def data_dir() -> Path:
    path = hermes_home() / "plugin-data" / "ebay"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def token_path() -> Path:
    return data_dir() / "tokens.json"


def _credentials() -> tuple[str, str, str]:
    vals = tuple(os.environ.get(k, "").strip() for k in ("EBAY_APP_ID", "EBAY_CERT_ID", "EBAY_RUNAME"))
    if not all(vals):
        raise RuntimeError("Set EBAY_APP_ID, EBAY_CERT_ID, and EBAY_RUNAME in the active Hermes profile .env")
    return vals  # type: ignore[return-value]


def authorization_url(state: str) -> str:
    app_id, _, runame = _credentials()
    return AUTH + "?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": runame, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state,
    })


def _token_request(fields: dict[str, str]) -> dict[str, Any]:
    app_id, cert_id, _ = _credentials()
    basic = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
    req = urllib.request.Request(OAUTH_ENDPOINT, data=urllib.parse.urlencode(fields).encode(), headers={
        "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json", "User-Agent": "hermes-ebay/0.1.0",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"eBay OAuth failed (HTTP {exc.code}): {detail}") from None
    result["expires_at"] = int(time.time()) + int(result.get("expires_in", 7200))
    return result


def exchange_code(code: str) -> None:
    _, _, runame = _credentials()
    token = _token_request({"grant_type": "authorization_code", "code": urllib.parse.unquote(code.strip()), "redirect_uri": runame})
    _save_token(token)


def _save_token(token: dict[str, Any]) -> None:
    path = token_path()
    old = load_token(required=False)
    if old and not token.get("refresh_token"):
        token["refresh_token"] = old.get("refresh_token")
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(token, handle)
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_token(*, required: bool = True) -> dict[str, Any] | None:
    path = token_path()
    if not path.exists():
        if required:
            raise RuntimeError("eBay is disconnected; run `hermes ebay connect` in a terminal")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("eBay token store is unreadable; disconnect and reconnect") from exc


def access_token() -> str:
    token = load_token()
    if token is None:  # pragma: no cover - required=True raises before this point
        raise RuntimeError("eBay is disconnected")
    if int(token.get("expires_at", 0)) <= int(time.time()) + 120:
        refresh = token.get("refresh_token")
        if not refresh:
            raise RuntimeError("eBay refresh token is missing; reconnect")
        token = _token_request({"grant_type": "refresh_token", "refresh_token": str(refresh), "scope": " ".join(SCOPES)})
        _save_token(token)
    return str(token["access_token"])


def disconnect() -> bool:
    path = token_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token()}", "Accept": "application/json",
        "Content-Type": "application/json", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "User-Agent": "hermes-ebay/0.1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"eBay API failed (HTTP {exc.code}): {detail}") from None


def _limit(value: Any, default: int = 25, maximum: int = 200) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def account_status(_: dict[str, Any]) -> dict[str, Any]:
    data = request("/sell/account/v1/privilege")
    return {"sellingLimit": data.get("sellingLimit"), "sellerRegistrationCompleted": data.get("sellerRegistrationCompleted")}


def orders(args: dict[str, Any]) -> dict[str, Any]:
    days = max(1, min(int(args.get("days", 7)), 90))
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    data = request("/sell/fulfillment/v1/order", {"filter": f"creationdate:[{start}..{end}]", "limit": _limit(args.get("limit"))})
    safe = [{k: order.get(k) for k in ("orderId", "creationDate", "orderFulfillmentStatus", "orderPaymentStatus", "pricingSummary")} for order in data.get("orders", [])]
    return {"total": data.get("total", len(safe)), "orders": safe}


def offers(args: dict[str, Any]) -> dict[str, Any]:
    data = request("/sell/inventory/v1/offer", {"limit": _limit(args.get("limit"))})
    safe = [{k: offer.get(k) for k in ("offerId", "sku", "marketplaceId", "format", "status", "pricingSummary")} for offer in data.get("offers", [])]
    return {"total": data.get("total", len(safe)), "offers": safe}


def returns(args: dict[str, Any]) -> dict[str, Any]:
    data = request("/post-order/v2/return/search", {"limit": _limit(args.get("limit"), 25, 200)})
    items = data.get("members", data.get("returns", []))
    safe = [{k: item.get(k) for k in ("returnId", "returnStatus", "creationDate", "lastModifiedDate")} for item in items]
    return {"total": data.get("totalNumberOfReturns", len(safe)), "returns": safe}


def cancellations(args: dict[str, Any]) -> dict[str, Any]:
    data = request("/post-order/v2/cancellation/search", {"limit": _limit(args.get("limit"), 25, 200)})
    items = data.get("members", data.get("cancellations", []))
    safe = [{k: item.get(k) for k in ("cancelId", "cancelState", "requestDate", "lastModifiedDate")} for item in items]
    return {"total": data.get("totalNumberOfRequests", len(safe)), "cancellations": safe}


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(data_dir() / "monitor.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS seen (digest TEXT PRIMARY KEY, seen_at INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return db


def monitor_poll() -> list[str]:
    events: list[tuple[str, str]] = []
    for kind, result, key, status in (
        ("order", orders({"days": 2, "limit": 100}), "orders", "orderFulfillmentStatus"),
        ("return", returns({"limit": 100}), "returns", "returnStatus"),
        ("cancellation", cancellations({"limit": 100}), "cancellations", "cancelState"),
    ):
        for item in result.get(key, []):
            identifier = str(item.get("orderId") or item.get("returnId") or item.get("cancelId") or "")
            state = str(item.get(status) or "unknown")
            digest = hashlib.sha256(f"{kind}\0{identifier}\0{state}".encode()).hexdigest()
            events.append((digest, f"eBay {kind}: {identifier} — {state}"))
    new: list[str] = []
    with _db() as db:
        initialized = db.execute("SELECT value FROM settings WHERE key='initialized'").fetchone()
        for digest, message in events:
            exists = db.execute("SELECT 1 FROM seen WHERE digest=?", (digest,)).fetchone()
            db.execute("INSERT OR IGNORE INTO seen(digest,seen_at) VALUES(?,?)", (digest, int(time.time())))
            if initialized and not exists:
                new.append(message)
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('initialized',?)", (str(int(time.time())),))
        db.execute("DELETE FROM seen WHERE seen_at < ?", (int(time.time()) - 90 * 86400,))
    return new


def monitor_status(_: dict[str, Any]) -> dict[str, Any]:
    token = load_token(required=False)
    with _db() as db:
        initialized = db.execute("SELECT value FROM settings WHERE key='initialized'").fetchone()
        count = db.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
    return {"connected": bool(token), "token_expires_at": token.get("expires_at") if token else None, "monitor_initialized_at": initialized[0] if initialized else None, "dedupe_records": count, "pii_persisted": False}
