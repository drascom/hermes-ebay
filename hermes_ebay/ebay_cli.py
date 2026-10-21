"""CLI for credential setup, OAuth, monitoring, and disconnect."""
from __future__ import annotations

import getpass
import json
import os
import secrets
import subprocess
import urllib.parse
import webbrowser

from . import ebay_client as api


def setup_cli(parser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)
    setup = sub.add_parser("setup", help="Save Production App ID, Cert ID, and RuName to the profile .env")
    setup.add_argument("--app-id")
    setup.add_argument("--runame")
    setup.add_argument("--cert-id", help="Discouraged: prompts securely when omitted")
    connect = sub.add_parser("connect", help="Authorize in a browser and exchange the returned code")
    connect.add_argument("--no-browser", action="store_true")
    connect.add_argument("--code", help="Discouraged: prompts securely when omitted")
    sub.add_parser("status", help="Show connection and monitor status (never tokens)")
    sub.add_parser("disconnect", help="Delete OAuth tokens and monitor state")
    monitor = sub.add_parser("monitor", help="Manage opt-in 30-minute cron alerts")
    monitor.add_argument("operation", choices=["enable", "disable", "poll", "status"])
    monitor.add_argument("--deliver", default="local", help="Cron delivery target, e.g. telegram or discord")


def _set_env(values: dict[str, str]) -> None:
    home = api.hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keys = set(values)
    lines = [line for line in lines if not ("=" in line and line.split("=", 1)[0].strip() in keys)]
    lines.extend(f"{key}={value}" for key, value in values.items())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    os.environ.update(values)


def _setup(args) -> None:
    app_id = (args.app_id or input("Production App ID: ")).strip()
    runame = (args.runame or input("RuName: ")).strip()
    cert_id = (args.cert_id or getpass.getpass("Production Cert ID (hidden): ")).strip()
    if not all((app_id, cert_id, runame)) or any("\n" in x for x in (app_id, cert_id, runame)):
        raise SystemExit("All three values are required and must be one line.")
    _set_env({"EBAY_APP_ID": app_id, "EBAY_CERT_ID": cert_id, "EBAY_RUNAME": runame})
    print(f"Saved credentials to {api.hermes_home() / '.env'} with mode 0600. Run `hermes ebay connect` next.")


def _connect(args) -> None:
    state = secrets.token_urlsafe(24)
    url = api.authorization_url(state)
    print("Open this eBay consent URL (the Cert ID is not included):")
    print(url)
    if not args.no_browser:
        webbrowser.open(url)
    returned = (args.code or getpass.getpass("Paste the full redirect URL (or authorization code) (hidden): ")).strip()
    if not returned:
        raise SystemExit("No authorization code supplied.")
    code = returned
    if returned.startswith(("https://", "http://")):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(returned).query)
        if query.get("state", [""])[0] != state:
            raise SystemExit("OAuth state mismatch; start the connection again.")
        code = query.get("code", [""])[0]
        if not code:
            raise SystemExit("The redirect URL contains no authorization code.")
    api.exchange_code(code)
    print("Connected. OAuth tokens were stored locally with mode 0600.")


def _install_monitor(deliver: str) -> None:
    if (api.data_dir() / "cron-job-id").exists():
        raise SystemExit("An eBay monitor job is already enabled; disable it before creating another.")
    scripts = api.hermes_home() / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    script = scripts / "hermes-ebay-monitor.py"
    content = """import subprocess\nimport sys\np=subprocess.run(['hermes','ebay','monitor','poll'],text=True,capture_output=True)\nif p.returncode:\n print('eBay monitor failed: '+(p.stderr.strip() or p.stdout.strip()))\n sys.exit(p.returncode)\nprint(p.stdout,end='')\n"""
    script.write_text(content, encoding="utf-8")
    result = subprocess.run(  # noqa: S603,S607 - fixed Hermes executable and argv, never a shell
        ["hermes", "cron", "create", "30m", "--name", "eBay seller alerts", "--deliver", deliver, "--script", script.name, "--no-agent"],  # noqa: S607
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    first = result.stdout.splitlines()[0] if result.stdout else ""
    if first.startswith("Created job: "):
        (api.data_dir() / "cron-job-id").write_text(first.removeprefix("Created job: ").strip(), encoding="utf-8")
    print(result.stdout.strip())


def _disable_monitor() -> None:
    record = api.data_dir() / "cron-job-id"
    if not record.exists():
        print("No plugin-managed eBay monitor job was recorded.")
        return
    job_id = record.read_text(encoding="utf-8").strip()
    result = subprocess.run(  # noqa: S603,S607 - fixed Hermes executable and validated persisted id
        ["hermes", "cron", "remove", job_id],  # noqa: S607
        text=True,
        capture_output=True,
    )
    if result.returncode and "not found" not in (result.stderr + result.stdout).lower():
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    record.unlink(missing_ok=True)
    print("Removed the eBay monitor job.")


def handle_cli(args) -> None:
    if args.action == "setup":
        _setup(args)
    elif args.action == "connect":
        _connect(args)
    elif args.action == "status":
        print(json.dumps(api.monitor_status({}), indent=2))
    elif args.action == "disconnect":
        _disable_monitor()
        removed = api.disconnect()
        db = api.data_dir() / "monitor.sqlite3"
        if db.exists():
            db.unlink()
        print("Disconnected from eBay." if removed else "eBay was already disconnected.")
    elif args.action == "monitor":
        if args.operation == "enable":
            _install_monitor(args.deliver)
        elif args.operation == "disable":
            _disable_monitor()
        elif args.operation == "poll":
            messages = api.monitor_poll()
            if messages:
                print("\n".join(messages))
        else:
            print(json.dumps(api.monitor_status({}), indent=2))
