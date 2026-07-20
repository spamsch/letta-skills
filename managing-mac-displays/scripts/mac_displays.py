#!/usr/bin/env python3
"""Safety-bound displayplacer wrapper for physical Mac display workflows."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ACKNOWLEDGMENT = "I-ACCEPT-HARDWARE-RECOVERY"
PROFILE_KEYS = {"schema_version", "created_at", "host", "displays", "displayplacer_arguments"}


class DisplayError(RuntimeError):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def displayplacer() -> str:
    binary = shutil.which("displayplacer")
    if not binary:
        raise DisplayError("displayplacer is not installed or not in PATH.")
    return binary


def run_displayplacer(*arguments: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [displayplacer(), *arguments],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DisplayError("displayplacer timed out.", 3) from exc


def betterdisplay_running() -> bool:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,command="],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise DisplayError("Could not inspect running processes; refusing display mutation.", 3)
    return any(
        "/BetterDisplay.app/Contents/" in line or re.search(r"\bBetterDisplay(?:$|\s)", line)
        for line in result.stdout.splitlines()
    )


def require_betterdisplay_stopped() -> None:
    if betterdisplay_running():
        raise DisplayError(
            "BetterDisplay is running. Quit it normally before disconnecting or restoring; "
            "this helper will not launch, query, or control BetterDisplay.",
            3,
        )


def parse_list(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    displays: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_modes = False
    for line in text.splitlines():
        if line.startswith("Persistent screen id: "):
            if current:
                displays.append(current)
            current = {"persistent_id": line.split(": ", 1)[1]}
            in_modes = False
            continue
        if current is None:
            continue
        if line.startswith("Resolutions for rotation"):
            in_modes = True
            continue
        if in_modes:
            continue
        field_map = {
            "Contextual screen id: ": "contextual_id",
            "Serial screen id: ": "serial_id",
            "Type: ": "type",
            "Resolution: ": "resolution",
            "Hertz: ": "hertz",
            "Color Depth: ": "color_depth",
            "Scaling: ": "scaling",
            "Origin: ": "origin",
            "Rotation: ": "rotation",
            "Enabled: ": "enabled",
        }
        for prefix, key in field_map.items():
            if line.startswith(prefix):
                value: Any = line[len(prefix):]
                if key == "enabled":
                    value = value.strip().casefold() == "true"
                elif key == "origin":
                    value = value.replace(" - main display", "")
                    current["main"] = " - main display" in line
                elif key == "rotation":
                    value = value.split(" - ", 1)[0]
                current[key] = value
                break
    if current:
        displays.append(current)

    profile_arguments: list[str] = []
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("displayplacer ") or "/displayplacer " in stripped:
            tokens = shlex.split(stripped)
            if tokens and Path(tokens[0]).name == "displayplacer":
                profile_arguments = tokens[1:]
                break
    return displays, profile_arguments


def status() -> dict[str, Any]:
    result = run_displayplacer("list")
    if result.returncode != 0:
        raise DisplayError(f"displayplacer list failed: {result.stderr.strip() or result.stdout.strip()}", 3)
    displays, arguments = parse_list(result.stdout)
    if not displays:
        raise DisplayError("No displays could be parsed from displayplacer output.", 3)
    return {
        "success": True,
        "display_count": len(displays),
        "displays": displays,
        "profile_available": bool(arguments),
        "betterdisplay_running": betterdisplay_running(),
    }


def current_snapshot() -> dict[str, Any]:
    result = run_displayplacer("list")
    if result.returncode != 0:
        raise DisplayError(f"displayplacer list failed: {result.stderr.strip() or result.stdout.strip()}", 3)
    displays, arguments = parse_list(result.stdout)
    if not displays or not arguments:
        raise DisplayError("Could not capture a complete displayplacer profile.", 3)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": os.uname().nodename,
        "displays": displays,
        "displayplacer_arguments": arguments_to_serial_ids(arguments, displays),
    }


def argument_id(argument: str) -> str:
    match = re.search(r"(?:^|\s)id:([^\s]+)", argument)
    if not match:
        raise DisplayError(f"Profile argument has no display ID: {argument!r}", 3)
    return match.group(1)


def replace_argument_id(argument: str, replacement: str) -> str:
    match = re.search(r"(?:^|\s)id:([^\s]+)", argument)
    if not match:
        raise DisplayError(f"Profile argument has no display ID: {argument!r}", 3)
    return argument[:match.start(1)] + replacement + argument[match.end(1):]


def arguments_to_serial_ids(arguments: list[str], displays: list[dict[str, Any]]) -> list[str]:
    persistent_to_serial = {
        str(item["persistent_id"]): str(item["serial_id"])
        for item in displays if item.get("persistent_id") and item.get("serial_id")
    }
    converted = []
    for argument in arguments:
        ids = argument_id(argument).split("+")
        try:
            serials = [persistent_to_serial[item] for item in ids]
        except KeyError as exc:
            raise DisplayError(f"No serial ID available for profile display: {exc.args[0]}", 3) from exc
        converted.append(replace_argument_id(argument, "+".join(serials)))
    return converted


def write_snapshot(path: Path) -> dict[str, Any]:
    profile = current_snapshot()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(profile, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise DisplayError(f"Refusing to overwrite existing profile: {path}") from exc
    return {"success": True, "profile": str(path), **profile}


def load_profile(path: Path) -> dict[str, Any]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DisplayError(f"Could not read profile: {exc}") from exc
    if not isinstance(profile, dict) or set(profile) != PROFILE_KEYS or profile.get("schema_version") != SCHEMA_VERSION:
        raise DisplayError("Unsupported or malformed display profile.", 3)
    if not isinstance(profile["host"], str) or not isinstance(profile["displays"], list) or not all(isinstance(item, dict) for item in profile["displays"]) or not isinstance(profile["displayplacer_arguments"], list) or not all(isinstance(item, str) for item in profile["displayplacer_arguments"]):
        raise DisplayError("Malformed display profile collections.", 3)
    return profile


def normalized_type(item: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(item.get("type", "")).casefold()).strip()


def is_builtin_physical(item: dict[str, Any]) -> bool:
    label = normalized_type(item)
    return item.get("enabled") is True and ("macbook" in label or "built in" in label)


def is_external_physical(item: dict[str, Any]) -> bool:
    label = normalized_type(item)
    return item.get("enabled") is True and "external screen" in label and "virtual" not in label and "sidecar" not in label


def display_map(displays: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    persistent_values = [str(item.get("persistent_id")) for item in displays if item.get("persistent_id")]
    serial_values = [str(item.get("serial_id")) for item in displays if item.get("serial_id")]
    if len(set(persistent_values)) != len(persistent_values) or len(set(serial_values)) != len(serial_values):
        raise DisplayError("Display identifiers are ambiguous; refusing to remap.", 3)
    by_persistent = {str(item["persistent_id"]): item for item in displays if item.get("persistent_id")}
    by_serial = {str(item["serial_id"]): item for item in displays if item.get("serial_id")}
    return by_persistent, by_serial


def remap_arguments(profile: dict[str, Any], current: list[dict[str, Any]]) -> list[str]:
    current_by_persistent, current_by_serial = display_map(current)
    saved_by_persistent, saved_by_serial = display_map(profile["displays"])
    old_to_new: dict[str, str] = {}
    used_current: set[str] = set()
    missing: list[str] = []
    for saved in profile["displays"]:
        old_id = str(saved.get("persistent_id", ""))
        serial = str(saved.get("serial_id", ""))
        if serial and serial in current_by_serial:
            current_item = current_by_serial[serial]
        elif not serial and old_id in current_by_persistent:
            current_item = current_by_persistent[old_id]
        else:
            missing.append(f"{saved.get('type', 'display')} ({old_id})")
            continue
        current_id = str(current_item["persistent_id"])
        if current_id in used_current:
            raise DisplayError("Profile remapping is not one-to-one.", 3)
        used_current.add(current_id)
        old_to_new[old_id] = current_id
        if serial:
            old_to_new[serial] = str(current_item.get("serial_id") or current_id)
    if missing:
        raise DisplayError(
            "Profile displays are still absent: " + ", ".join(missing) + ". "
            "Reconnect through a different physical port; if still absent, log out or reboot.",
            3,
        )

    remapped: list[str] = []
    for argument in profile["displayplacer_arguments"]:
        old_group = argument_id(argument)
        new_ids = []
        for old_id in old_group.split("+"):
            if old_id not in old_to_new:
                raise DisplayError(f"Profile references an unknown display ID: {old_id}", 3)
            new_ids.append(old_to_new[old_id])
        new_group = "+".join(new_ids)
        remapped.append(replace_argument_id(argument, new_group))
    referenced = {item for argument in profile["displayplacer_arguments"] for item in argument_id(argument).split("+")}
    covered: set[str] = set()
    for identifier in referenced:
        if identifier in saved_by_serial:
            saved = saved_by_serial[identifier]
        elif identifier in saved_by_persistent:
            saved = saved_by_persistent[identifier]
        else:
            raise DisplayError(f"Profile arguments reference an unknown saved display: {identifier}", 3)
        covered.add(str(saved.get("serial_id") or saved.get("persistent_id")))
    expected = {str(saved.get("serial_id") or saved.get("persistent_id")) for saved in profile["displays"]}
    if not referenced or covered != expected:
        raise DisplayError("Profile arguments do not cover every saved display exactly.", 3)
    return remapped


def argument_fields(argument: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in shlex.split(argument):
        if ":" not in token:
            raise DisplayError(f"Malformed profile token: {token!r}", 3)
        key, value = token.split(":", 1)
        if key not in {"id", "res", "hz", "color_depth", "enabled", "scaling", "origin", "degree"}:
            raise DisplayError(f"Unsupported profile setting: {key}", 3)
        fields[key] = value
    if "id" not in fields:
        raise DisplayError("Profile argument is missing an ID.", 3)
    return fields


def topology_mismatches(arguments: list[str], current: list[dict[str, Any]]) -> list[str]:
    by_persistent, by_serial = display_map(current)
    mismatches: list[str] = []
    field_map = {
        "res": "resolution", "hz": "hertz", "color_depth": "color_depth",
        "scaling": "scaling", "origin": "origin", "degree": "rotation",
    }
    for argument in arguments:
        expected = argument_fields(argument)
        for identifier in expected["id"].split("+"):
            item = by_persistent.get(identifier) or by_serial.get(identifier)
            if item is None:
                mismatches.append(f"missing display {identifier}")
                continue
            for spec_key, status_key in field_map.items():
                if spec_key in expected and str(item.get(status_key)) != expected[spec_key]:
                    mismatches.append(f"{identifier} {status_key}: expected {expected[spec_key]}, got {item.get(status_key)}")
            if "enabled" in expected and item.get("enabled") is not (expected["enabled"].casefold() == "true"):
                mismatches.append(f"{identifier} enabled state differs")
    return mismatches


def require_exact_profile_topology(profile: dict[str, Any], current: list[dict[str, Any]]) -> None:
    saved_serials = [str(item.get("serial_id", "")) for item in profile["displays"]]
    current_serials = [str(item.get("serial_id", "")) for item in current]
    if not saved_serials or any(not value for value in saved_serials + current_serials):
        raise DisplayError("Every display needs a serial ID for exact topology validation.", 3)
    if len(set(saved_serials)) != len(saved_serials) or len(set(current_serials)) != len(current_serials):
        raise DisplayError("Display serial IDs are ambiguous.", 3)
    if set(saved_serials) != set(current_serials):
        raise DisplayError("Current topology does not exactly match the saved profile.", 3)


def disconnect(target_id: str, profile_path: Path, confirmation: str | None) -> tuple[dict[str, Any], int]:
    if confirmation != ACKNOWLEDGMENT:
        raise DisplayError(f"Exact confirmation required: {ACKNOWLEDGMENT}", 3)
    require_betterdisplay_stopped()
    profile = load_profile(profile_path)
    if profile["host"] != os.uname().nodename:
        raise DisplayError("Profile belongs to another Mac.", 3)
    view = status()
    by_persistent, _ = display_map(view["displays"])
    target = by_persistent.get(target_id)
    if target is None:
        raise DisplayError(f"Target display is not currently visible: {target_id}", 3)
    if not is_external_physical(target):
        raise DisplayError("Target must be an explicitly enabled physical external screen.", 3)
    remaining = [item for item in view["displays"] if item.get("persistent_id") != target_id]
    if not any(is_builtin_physical(item) for item in remaining):
        raise DisplayError("Refusing to disconnect unless an explicitly enabled built-in display remains.", 3)
    saved_ids = {str(item.get("persistent_id")) for item in profile["displays"]}
    if target_id not in saved_ids:
        raise DisplayError("The supplied profile does not contain the target display.", 3)
    require_exact_profile_topology(profile, view["displays"])
    remapped = remap_arguments(profile, view["displays"])
    mismatches = topology_mismatches(remapped, view["displays"])
    if mismatches:
        raise DisplayError("Current layout differs from the saved profile: " + "; ".join(mismatches), 3)

    require_betterdisplay_stopped()
    result = run_displayplacer(f"id:{target_id} enabled:false")
    time.sleep(3)
    after = status()
    after_ids = {str(item.get("persistent_id")) for item in after["displays"]}
    disconnected = target_id not in after_ids
    if disconnected:
        return {
            "success": True,
            "disconnected": target,
            "profile": str(profile_path),
            "displayplacer_return_code": result.returncode,
            "warning": "Software restore may be impossible until macOS redetects the display through another port, logout, or reboot.",
            "current_displays": after["displays"],
        }, 0
    return {
        "success": False,
        "error": result.stderr.strip() or result.stdout.strip() or "Display remained connected.",
        "current_displays": after["displays"],
    }, 4


def restore(profile_path: Path) -> tuple[dict[str, Any], int]:
    require_betterdisplay_stopped()
    profile = load_profile(profile_path)
    if profile["host"] != os.uname().nodename:
        raise DisplayError("Profile belongs to another Mac.", 3)
    before = status()
    require_exact_profile_topology(profile, before["displays"])
    arguments = remap_arguments(profile, before["displays"])
    require_betterdisplay_stopped()
    result = run_displayplacer(*arguments)
    time.sleep(3)
    after = status()
    if result.returncode != 0:
        return {
            "success": False,
            "error": result.stderr.strip() or result.stdout.strip(),
            "profile": str(profile_path),
            "current_displays": after["displays"],
        }, 4
    try:
        require_exact_profile_topology(profile, after["displays"])
        mismatches = topology_mismatches(arguments, after["displays"])
    except DisplayError as exc:
        mismatches = [str(exc)]
    if mismatches:
        return {
            "success": False,
            "error": "displayplacer returned success but the restored topology differs: " + "; ".join(mismatches),
            "profile": str(profile_path),
            "current_displays": after["displays"],
        }, 4
    return {"success": True, "profile": str(profile_path), "current_displays": after["displays"]}, 0


def wait_restore(profile_path: Path, timeout: int, poll: int) -> tuple[dict[str, Any], int]:
    profile = load_profile(profile_path)
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            view = status()
            remap_arguments(profile, view["displays"])
            return restore(profile_path)
        except DisplayError as exc:
            last_error = str(exc)
        time.sleep(poll)
    return {
        "success": False,
        "error": f"Timed out waiting for hardware redetection. {last_error}",
        "recovery": [
            "Reconnect through a different USB-C, Thunderbolt, or HDMI port.",
            "If still absent, log out and back in or reboot.",
        ],
    }, 3


def park(target_id: str, profile_path: Path) -> tuple[dict[str, Any], int]:
    require_betterdisplay_stopped()
    profile = load_profile(profile_path)
    if profile["host"] != os.uname().nodename:
        raise DisplayError("Profile belongs to another Mac.", 3)
    view = status()
    require_exact_profile_topology(profile, view["displays"])
    remap_arguments(profile, view["displays"])
    saved_ids = {str(item.get("persistent_id")) for item in profile["displays"]}
    if target_id not in saved_ids:
        raise DisplayError("The supplied profile does not contain the target display.", 3)

    by_persistent, _ = display_map(view["displays"])
    target = by_persistent.get(target_id)
    if target is None:
        raise DisplayError(f"Target display is not currently visible: {target_id}", 3)
    if not is_external_physical(target):
        raise DisplayError("Target must be an explicitly enabled physical external screen.", 3)
    anchor = next((item for item in view["displays"] if is_builtin_physical(item)), None)
    if anchor is None:
        raise DisplayError("Refusing to park unless an enabled built-in display remains to mirror onto.", 3)
    anchor_id = str(anchor["persistent_id"])
    if anchor_id == target_id:
        raise DisplayError("Target is the built-in display; refusing to park it.", 3)

    result = run_displayplacer("list")
    if result.returncode != 0:
        raise DisplayError(f"displayplacer list failed: {result.stderr.strip() or result.stdout.strip()}", 3)
    _, live_arguments = parse_list(result.stdout)
    if not live_arguments:
        raise DisplayError("Could not read the current displayplacer layout.", 3)

    parked_arguments: list[str] = []
    dropped_target = False
    anchor_index = -1
    for argument in live_arguments:
        group = argument_id(argument).split("+")
        if target_id in group:
            if len(group) > 1:
                raise DisplayError("Target already belongs to a mirror set; it appears parked.", 3)
            dropped_target = True
            continue
        if anchor_id in group:
            anchor_index = len(parked_arguments)
            parked_arguments.append(replace_argument_id(argument, "+".join(group + [target_id])))
        else:
            parked_arguments.append(argument)
    if not dropped_target:
        raise DisplayError(f"Target display has no standalone layout entry: {target_id}", 3)
    if anchor_index < 0:
        raise DisplayError(f"Built-in display has no layout entry to mirror onto: {anchor_id}", 3)
    # displayplacer needs exactly one screen at origin (0,0). If the target was the
    # primary, folding it away leaves none—make the built-in mirror group primary.
    if not any(re.search(r"origin:\(0,0\)", argument) for argument in parked_arguments):
        parked_arguments[anchor_index] = re.sub(
            r"origin:\([^)]*\)", "origin:(0,0)", parked_arguments[anchor_index]
        )

    require_betterdisplay_stopped()
    applied = run_displayplacer(*parked_arguments)
    time.sleep(3)
    after = status()
    after_ids = {str(item.get("persistent_id")) for item in after["displays"]}
    if applied.returncode != 0:
        return {
            "success": False,
            "error": applied.stderr.strip() or applied.stdout.strip() or "displayplacer refused the mirror layout.",
            "profile": str(profile_path),
            "current_displays": after["displays"],
        }, 4
    if target_id not in after_ids:
        return {
            "success": False,
            "error": "Target left the device tree after parking; mirroring should never remove it. Treat as a disconnect and recover physically.",
            "profile": str(profile_path),
            "current_displays": after["displays"],
        }, 4
    return {
        "success": True,
        "parked": target,
        "mirrored_onto": anchor_id,
        "profile": str(profile_path),
        "note": "Display is mirrored onto the built-in, not disconnected. It stays in the device tree, so 'unpark' can restore it in software.",
        "current_displays": after["displays"],
    }, 0


def unpark(profile_path: Path) -> tuple[dict[str, Any], int]:
    result, code = restore(profile_path)
    if code == 0 and result.get("success"):
        result["note"] = "Un-mirrored: restored the independent layout saved in the profile."
    return result, code


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Safely manage physical Mac displays with displayplacer")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--output", required=True)
    disconnect_cmd = sub.add_parser("disconnect")
    disconnect_cmd.add_argument("--id", required=True)
    disconnect_cmd.add_argument("--profile", required=True)
    disconnect_cmd.add_argument("--confirm", required=True)
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("--profile", required=True)
    park_cmd = sub.add_parser("park")
    park_cmd.add_argument("--id", required=True)
    park_cmd.add_argument("--profile", required=True)
    unpark_cmd = sub.add_parser("unpark")
    unpark_cmd.add_argument("--profile", required=True)
    wait_cmd = sub.add_parser("wait-restore")
    wait_cmd.add_argument("--profile", required=True)
    wait_cmd.add_argument("--timeout", type=int, default=180)
    wait_cmd.add_argument("--poll", type=int, default=3)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "status":
            emit(status())
            return 0
        if args.command == "snapshot":
            emit(write_snapshot(Path(args.output).expanduser().absolute()))
            return 0
        if args.command == "disconnect":
            result, code = disconnect(args.id, Path(args.profile).expanduser().absolute(), args.confirm)
        elif args.command == "restore":
            result, code = restore(Path(args.profile).expanduser().absolute())
        elif args.command == "park":
            result, code = park(args.id, Path(args.profile).expanduser().absolute())
        elif args.command == "unpark":
            result, code = unpark(Path(args.profile).expanduser().absolute())
        else:
            if not 10 <= args.timeout <= 3600 or not 1 <= args.poll <= 30:
                raise DisplayError("timeout must be 10..3600 seconds and poll must be 1..30 seconds.")
            result, code = wait_restore(Path(args.profile).expanduser().absolute(), args.timeout, args.poll)
        emit(result)
        return code
    except DisplayError as exc:
        emit({"success": False, "error": str(exc), "code": exc.code})
        return exc.code
    except (OSError, ValueError) as exc:
        emit({"success": False, "error": str(exc), "code": 2})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
