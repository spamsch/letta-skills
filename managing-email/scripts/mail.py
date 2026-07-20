#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27.0",
#   "msal>=1.28.0",
# ]
# ///
"""CLI for the managing-email Letta skill."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Any, Callable

from mail_engine import (
    PROVIDERS,
    MailClient,
    NotLoggedInError,
    account_overview,
    basic_login,
    detect_provider,
    list_configured_accounts,
    login_account,
    probe_account,
    resolve_account,
)


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def env_file_value(key: str) -> str:
    path = Path.home() / ".macbot" / ".env"
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def client(email: str | None) -> tuple[str, MailClient]:
    resolved = resolve_account(email)
    configured = list_configured_accounts()
    match = next((item for item in configured if item.casefold() == resolved.casefold()), None)
    if match is None:
        raise ValueError(f"Unknown mail account: {resolved}")
    return match, MailClient(match)


def safe_text(name: str, value: str | None, *, imap_query: bool = False) -> str | None:
    if value is None:
        return None
    if any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError(f"{name} contains control characters.")
    if imap_query and any(char in value for char in ('"', "\\")):
        raise ValueError(f"{name} contains unsupported quote or escape characters.")
    return value


def accounts(_args: argparse.Namespace) -> dict[str, Any]:
    items = account_overview()
    return {
        "success": True,
        "accounts": items,
        "logged_in": [item["email"] for item in items if item["logged_in"]],
        "count": len(items),
    }


def probe(args: argparse.Namespace) -> dict[str, Any]:
    email, _c = client(args.email)
    return {"success": True, "email": email, **probe_account(email)}


def search(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    mailbox = safe_text("mailbox", args.mailbox) or "INBOX"
    sender = safe_text("sender", args.sender, imap_query=True)
    subject = safe_text("subject", args.subject, imap_query=True)
    limit = max(1, min(args.limit, 100))
    since_days = None if args.since_days is None else max(0, min(args.since_days, 3650))
    messages = c.search(mailbox, args.unread, since_days, sender, subject, limit)
    return {"success": True, "email": email, "mailbox": args.mailbox,
            "count": len(messages), "messages": messages}


def read(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    mailbox = safe_text("mailbox", args.mailbox) or "INBOX"
    max_chars = max(1, min(args.max_chars, 100000))
    return {"success": True, "email": email,
            **c.fetch_content(args.uid, mailbox, max_chars)}


def attachments(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    mailbox = safe_text("mailbox", args.mailbox) or "INBOX"
    return {"success": True, "email": email,
            **c.download_attachments(args.uid, mailbox, args.save_dir)}


def mark(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    mailbox = safe_text("mailbox", args.mailbox) or "INBOX"
    result = c.set_read(args.uid, args.read, mailbox)
    return {"success": bool(result.get("ok")), "email": email, **result}


def archive(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    mailbox = safe_text("mailbox", args.mailbox) or "INBOX"
    result = c.move_to_archive(args.uid, mailbox)
    return {"success": bool(result.get("ok")), "email": email, **result}


def trash(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    mailbox = safe_text("mailbox", args.mailbox) or "INBOX"
    result = c.move_to_trash(args.uid, mailbox)
    return {"success": bool(result.get("ok")), "email": email, **result}


def draft(args: argparse.Namespace) -> dict[str, Any]:
    email, c = client(args.email)
    if args.body is not None and args.body_file is not None:
        raise ValueError("Use either --body or --body-file, not both.")
    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
    result = c.create_draft(
        args.to, args.subject, body, args.cc, args.bcc, args.attachment, args.html
    )
    return {"success": bool(result.get("ok")), "email": email, **result}


def login(args: argparse.Namespace) -> dict[str, Any]:
    if "@" not in args.email or any(char in args.email for char in ("/", "\\", "\x00", "\r", "\n")):
        raise ValueError("Enter a valid email address.")
    provider = detect_provider(args.email)
    details = PROVIDERS.get(provider)
    if details is None:
        raise ValueError(f"Unsupported provider for {args.email}: {provider}")
    if details.oauth == "app_password":
        password = getpass.getpass(f"App password for {args.email}: ")
        if not password:
            raise ValueError("No app password entered.")
        transport = basic_login(args.email, provider, password)
    else:
        client_id = args.client_id or os.getenv("MACBOT_MS_OAUTH_CLIENT_ID") or env_file_value("MACBOT_MS_OAUTH_CLIENT_ID")
        if not client_id:
            raise ValueError("Set MACBOT_MS_OAUTH_CLIENT_ID in the environment or ~/.macbot/.env.")

        def prompt(message: str) -> None:
            print("\n" + message + f"\nSign in as: {args.email}\n", flush=True)

        transport = login_account(args.email, client_id, args.transport, prompt)
    return {"success": True, "email": args.email, "provider": provider,
            "transport": transport, "message": "Login verified."}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Headless email over IMAP or Microsoft Graph")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("accounts")

    p = sub.add_parser("probe"); p.add_argument("--email", required=True)
    p = sub.add_parser("search"); p.add_argument("--email"); p.add_argument("--mailbox", default="INBOX")
    p.add_argument("--unread", action="store_true"); p.add_argument("--since-days", type=int)
    p.add_argument("--sender"); p.add_argument("--subject"); p.add_argument("--limit", type=int, default=25)

    for name in ("read", "attachments", "mark", "archive", "trash"):
        p = sub.add_parser(name); p.add_argument("uid"); p.add_argument("--email"); p.add_argument("--mailbox", default="INBOX")
        if name == "read": p.add_argument("--max-chars", type=int, default=20000)
        if name == "attachments": p.add_argument("--save-dir")
        if name == "mark":
            state = p.add_mutually_exclusive_group(required=True)
            state.add_argument("--read", dest="read", action="store_true")
            state.add_argument("--unread", dest="read", action="store_false")
        if name in ("attachments", "archive", "trash"):
            p.add_argument("--confirmed", action="store_true", required=True)

    p = sub.add_parser("draft"); p.add_argument("--email"); p.add_argument("--to", required=True)
    p.add_argument("--subject", default=""); p.add_argument("--body"); p.add_argument("--body-file")
    p.add_argument("--cc"); p.add_argument("--bcc"); p.add_argument("--attachment", action="append")
    p.add_argument("--html", action="store_true")
    p.add_argument("--confirmed", action="store_true", required=True)

    p = sub.add_parser("login"); p.add_argument("email"); p.add_argument("--client-id")
    p.add_argument("--transport", choices=("auto", "imap", "graph"), default="auto")
    return root


COMMANDS: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
    "accounts": accounts, "probe": probe, "search": search, "read": read,
    "attachments": attachments, "mark": mark, "archive": archive,
    "trash": trash, "draft": draft, "login": login,
}


def main() -> int:
    args = parser().parse_args()
    try:
        emit(COMMANDS[args.command](args))
        return 0
    except NotLoggedInError as exc:
        emit({"success": False, "error": str(exc), "needs_login": True})
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        emit({"success": False, "error": str(exc)})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
