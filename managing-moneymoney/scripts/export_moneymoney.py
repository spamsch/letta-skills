#!/usr/bin/env python3
"""Export MoneyMoney data through its read-only AppleScript interface."""

from __future__ import annotations

import argparse
import base64
import datetime as datetime_module
import json
import plistlib
import subprocess
import sys
from pathlib import Path


APPLESCRIPT = r'''
on run argv
    set actionName to item 1 of argv
    tell application "MoneyMoney"
        if actionName is "accounts" then
            return export accounts
        else if actionName is "categories" then
            return export categories
        else if actionName is "transactions" then
            set startDate to item 2 of argv
            set endDate to item 3 of argv
            set accountFilter to item 4 of argv
            set categoryFilter to item 5 of argv
            if accountFilter is "" and categoryFilter is "" then
                return export transactions from date startDate to date endDate as "plist"
            else if categoryFilter is "" then
                return export transactions from account accountFilter from date startDate to date endDate as "plist"
            else if accountFilter is "" then
                return export transactions from category categoryFilter from date startDate to date endDate as "plist"
            else
                return export transactions from account accountFilter from category categoryFilter from date startDate to date endDate as "plist"
            end if
        end if
    end tell
end run
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("accounts", help="Export accounts as JSON")
    subcommands.add_parser("categories", help="Export categories as JSON")
    transactions = subcommands.add_parser("transactions", help="Export transactions as JSON")
    transactions.add_argument("--from", dest="from_date", required=True, metavar="YYYY-MM-DD")
    transactions.add_argument("--to", dest="to_date", required=True, metavar="YYYY-MM-DD")
    transactions.add_argument("--account", default="", help="Optional MoneyMoney account reference")
    transactions.add_argument("--category", default="", help="Optional MoneyMoney category reference")
    for command in subcommands.choices.values():
        command.add_argument("--output", type=Path, help="Write JSON to a local file instead of stdout")
    return parser.parse_args()


def export_plist(args: argparse.Namespace) -> bytes:
    command = ["/usr/bin/osascript", "-l", "AppleScript", "-", args.action]
    if args.action == "transactions":
        command.extend([args.from_date, args.to_date, args.account, args.category])
    try:
        result = subprocess.run(command, input=APPLESCRIPT, text=True, capture_output=True, check=True)
    except FileNotFoundError as error:
        raise RuntimeError("This script requires macOS and osascript.") from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or "MoneyMoney did not return an export."
        raise RuntimeError(message) from error
    return result.stdout.encode("utf-8")


def json_compatible(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_compatible(item) for item in value]
    if isinstance(value, (datetime_module.date, datetime_module.datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    return value


def plist_to_json(plist: bytes) -> bytes:
    try:
        parsed = plistlib.loads(plist)
    except plistlib.InvalidFileException as error:
        raise RuntimeError("MoneyMoney returned an invalid plist export.") from error
    return json.dumps(json_compatible(parsed), ensure_ascii=False).encode("utf-8")


def main() -> None:
    args = parse_args()
    data = plist_to_json(export_plist(args))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
    else:
        sys.stdout.buffer.write(data)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
