#!/usr/bin/env python3
"""Plan-bound, no-overwrite organizer for loose top-level download files."""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PLANNER_VERSION = "1.0.0"
RULE_VERSION = "categories-v1"
DEFAULT_MIN_AGE = 300
DEFAULT_TTL = 3600

CATEGORIES: dict[str, tuple[str, ...]] = {
    "Images": ("png", "jpg", "jpeg", "heic", "gif", "svg", "webp", "ico", "tiff", "tif", "bmp", "raw", "cr2", "nef"),
    "Documents": ("pdf", "doc", "docx", "txt", "rtf", "pages", "odt", "md", "epub"),
    "Presentations": ("ppt", "pptx", "key", "odp"),
    "Spreadsheets": ("xls", "xlsx", "numbers", "ods", "csv", "tsv"),
    "Archives": ("zip", "gz", "tar", "rar", "7z", "bz2", "xz", "tgz", "tbz", "tbz2", "txz"),
    "Installers": ("dmg", "pkg", "mpkg", "iso"),
    "Videos": ("mp4", "mov", "avi", "mkv", "webm", "m4v", "wmv", "flv"),
    "Audio": ("mp3", "wav", "aac", "m4a", "flac", "ogg", "wma", "aiff"),
    "Code": ("py", "js", "jsx", "ts", "tsx", "html", "css", "json", "xml", "yaml", "yml", "toml", "sh", "rb", "go", "rs", "c", "cpp", "h", "java", "swift", "kt", "sql"),
}
PARTIAL_SUFFIXES = (".download", ".crdownload", ".part", ".partial", ".tmp")
COMPOUND_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz")
PACKAGE_SUFFIXES = (".app", ".pkg", ".pages", ".numbers", ".key")
UF_HIDDEN = getattr(stat, "UF_HIDDEN", 0x00008000)
RENAME_EXCL = 0x00000004
RENAME_NOFOLLOW_ANY = 0x00000010
OPEN_DIRECTORY = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
TOP_LEVEL_KEYS = {
    "schema_version", "planner_version", "rule_version", "plan_id",
    "confirmation_token", "created_at_ns", "expires_at_ns", "root", "policy",
    "create_directories", "operations", "summary", "skipped",
}


class OrganizerError(RuntimeError):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def root_info(raw: str) -> tuple[Path, os.stat_result]:
    requested = Path(raw).expanduser().absolute()
    try:
        initial = requested.lstat()
    except FileNotFoundError as exc:
        raise OrganizerError(f"Root does not exist: {requested}") from exc
    if stat.S_ISLNK(initial.st_mode):
        raise OrganizerError(f"Root may not be a symlink: {requested}", 3)
    if not stat.S_ISDIR(initial.st_mode):
        raise OrganizerError(f"Root is not a directory: {requested}")
    root = Path(os.path.realpath(requested))
    current = root.lstat()
    if (initial.st_dev, initial.st_ino) != (current.st_dev, current.st_ino):
        raise OrganizerError("Root changed while it was being resolved.", 3)
    return root, current


def normalized_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def is_hidden(name: str, info: os.stat_result) -> bool:
    return name.startswith(".") or bool(getattr(info, "st_flags", 0) & UF_HIDDEN)


def matched_suffix(name: str) -> str:
    lower = name.casefold()
    for suffix in COMPOUND_SUFFIXES:
        if lower.endswith(suffix):
            return suffix
    suffix = Path(name).suffix.casefold()
    return suffix


def classify(name: str) -> tuple[str, str]:
    suffix = matched_suffix(name)
    extension = suffix[1:].split(".")[-1] if suffix else ""
    for category, extensions in CATEGORIES.items():
        if extension in extensions:
            return category, suffix
    return "Other", suffix


def fingerprint(info: os.stat_result) -> dict[str, int]:
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": info.st_mode,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def inventory(root: Path, min_age_seconds: int) -> dict[str, Any]:
    now_ns = time.time_ns()
    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    category_counts: Counter[str] = Counter()
    try:
        entries = list(os.scandir(root))
    except OSError as exc:
        raise OrganizerError(f"Could not enumerate {root}: {exc}", 3) from exc

    for entry in sorted(entries, key=lambda item: (normalized_key(item.name), os.fsencode(item.name))):
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise OrganizerError(f"Could not inspect {entry.name!r}: {exc}", 3) from exc
        name = entry.name
        reason: str | None = None
        if stat.S_ISLNK(info.st_mode):
            reason = "symlink"
        elif is_hidden(name, info):
            reason = "hidden"
        elif stat.S_ISDIR(info.st_mode):
            reason = "package" if name.casefold().endswith(PACKAGE_SUFFIXES) else "directory"
        elif not stat.S_ISREG(info.st_mode):
            reason = "special-file"
        elif name.casefold().endswith(PARTIAL_SUFFIXES):
            reason = "partial-download"
        elif now_ns - info.st_mtime_ns < min_age_seconds * 1_000_000_000:
            reason = "recently-modified"
        if reason:
            skipped.append({"name": name, "reason": reason})
            continue
        category, suffix = classify(name)
        category_counts[category] += 1
        eligible.append({
            "name": name,
            "category": category,
            "matched_suffix": suffix,
            "size": info.st_size,
            "modified_ns": info.st_mtime_ns,
            "fingerprint": fingerprint(info),
        })
    return {
        "complete": True,
        "root": str(root),
        "eligible": eligible,
        "category_counts": dict(sorted(category_counts.items())),
        "skipped": skipped,
        "skipped_counts": dict(sorted(Counter(item["reason"] for item in skipped).items())),
    }


def split_name(name: str) -> tuple[str, str]:
    lower = name.casefold()
    for suffix in COMPOUND_SUFFIXES:
        if lower.endswith(suffix):
            return name[:-len(suffix)], name[-len(suffix):]
    path = Path(name)
    if path.suffix and path.stem:
        return name[:-len(path.suffix)], path.suffix
    return name, ""


def destination_name(name: str, occupied: set[str]) -> str:
    if normalized_key(name) not in occupied:
        occupied.add(normalized_key(name))
        return name
    stem, suffix = split_name(name)
    number = 2
    while True:
        candidate = f"{stem} ({number}){suffix}"
        if normalized_key(candidate) not in occupied:
            occupied.add(normalized_key(candidate))
            return candidate
        number += 1


def critical_plan(plan: dict[str, Any]) -> dict[str, Any]:
    # Bind every approval-visible field except the digest and token derived from it.
    return {key: value for key, value in plan.items() if key not in ("plan_id", "confirmation_token")}


def plan_digest(plan: dict[str, Any]) -> str:
    encoded = json.dumps(critical_plan(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_plan(root: Path, info: os.stat_result, min_age: int, ttl: int) -> dict[str, Any]:
    view = inventory(root, min_age)
    occupied: dict[str, set[str]] = {}
    create: set[str] = set()
    operations: list[dict[str, Any]] = []

    for item in view["eligible"]:
        category = item["category"]
        category_path = root / category
        if category not in occupied:
            if os.path.lexists(category_path):
                category_info = category_path.lstat()
                if stat.S_ISLNK(category_info.st_mode) or not stat.S_ISDIR(category_info.st_mode):
                    raise OrganizerError(f"Unsafe category destination: {category_path}", 3)
                occupied[category] = {normalized_key(entry.name) for entry in os.scandir(category_path)}
            else:
                occupied[category] = set()
                create.add(category)
        chosen = destination_name(item["name"], occupied[category])
        operation_id = len(operations) + 1
        operations.append({
            "operation_id": operation_id,
            "action": "move",
            "category": category,
            "classification": {"rule": "extension", "matched_suffix": item["matched_suffix"]},
            "source": {"relative_path": item["name"], **item["fingerprint"]},
            "destination": {"relative_path": f"{category}/{chosen}"},
        })

    created = time.time_ns()
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "planner_version": PLANNER_VERSION,
        "rule_version": RULE_VERSION,
        "plan_id": "",
        "confirmation_token": "",
        "created_at_ns": created,
        "expires_at_ns": created + ttl * 1_000_000_000,
        "root": {"path": str(root), "device": info.st_dev, "inode": info.st_ino},
        "policy": {
            "top_level_only": True,
            "regular_files_only": True,
            "include_hidden": False,
            "minimum_age_seconds": min_age,
            "collision_policy": "numbered-suffix",
        },
        "create_directories": sorted(create),
        "operations": operations,
        "summary": {
            "move_count": len(operations),
            "create_directory_count": len(create),
            "skipped_count": len(view["skipped"]),
            "category_counts": view["category_counts"],
            "skipped_counts": view["skipped_counts"],
        },
        "skipped": view["skipped"],
    }
    digest = plan_digest(plan)
    plan["plan_id"] = f"sha256:{digest}"
    plan["confirmation_token"] = f"MOVE-{digest[:16].upper()}"
    return plan


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise OrganizerError(f"Refusing to overwrite existing file: {path}") from exc


def load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrganizerError(f"Could not read plan: {exc}") from exc
    return validate_loaded_plan(plan)


def validate_loaded_plan(plan: Any) -> dict[str, Any]:
    try:
        if not isinstance(plan, dict) or set(plan) != TOP_LEVEL_KEYS:
            raise OrganizerError("Plan has missing or unknown top-level fields.", 3)
        if plan["schema_version"] != SCHEMA_VERSION or plan["planner_version"] != PLANNER_VERSION or plan["rule_version"] != RULE_VERSION:
            raise OrganizerError("Unsupported plan or rule version.", 3)
        if not all(isinstance(plan[key], int) for key in ("created_at_ns", "expires_at_ns")):
            raise OrganizerError("Plan timestamps are malformed.", 3)
        if plan["expires_at_ns"] <= plan["created_at_ns"]:
            raise OrganizerError("Plan expiration is malformed.", 3)
        root = plan["root"]
        if not isinstance(root, dict) or set(root) != {"path", "device", "inode"} or not isinstance(root["path"], str) or not isinstance(root["device"], int) or not isinstance(root["inode"], int):
            raise OrganizerError("Plan root is malformed.", 3)
        if not isinstance(plan["policy"], dict) or not isinstance(plan["create_directories"], list) or not isinstance(plan["operations"], list) or not isinstance(plan["summary"], dict) or not isinstance(plan["skipped"], list):
            raise OrganizerError("Plan collections are malformed.", 3)
        digest = plan_digest(plan)
        if plan["plan_id"] != f"sha256:{digest}" or plan["confirmation_token"] != f"MOVE-{digest[:16].upper()}":
            raise OrganizerError("Plan digest or confirmation token is invalid.", 3)
        return plan
    except OrganizerError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise OrganizerError(f"Malformed plan: {exc}", 3) from exc


def safe_relative_file(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and len(path.parts) == 1 and path.name == value and value not in (".", "..") and "\x00" not in value


def preflight(plan: dict[str, Any]) -> tuple[Path, dict[str, tuple[int, int]]]:
    if time.time_ns() > int(plan["expires_at_ns"]):
        raise OrganizerError("Plan has expired; create a fresh plan.", 3)
    root, root_stat = root_info(str(plan["root"]["path"]))
    if (root_stat.st_dev, root_stat.st_ino) != (plan["root"]["device"], plan["root"]["inode"]):
        raise OrganizerError("Root identity changed after planning.", 3)

    operations = plan.get("operations")
    if not isinstance(operations, list):
        raise OrganizerError("Operations must be a list.", 3)
    sources: set[str] = set()
    destinations: set[str] = set()
    parent_ids: dict[str, tuple[int, int]] = {}
    allowed_categories = set(CATEGORIES) | {"Other"}
    create = set(plan.get("create_directories", []))
    if not create <= allowed_categories:
        raise OrganizerError("Plan contains an unknown category directory.", 3)

    for expected_id, operation in enumerate(operations, 1):
        if not isinstance(operation, dict) or operation.get("operation_id") != expected_id or operation.get("action") != "move":
            raise OrganizerError("Operations are malformed or out of order.", 3)
        source_data = operation.get("source", {})
        dest_data = operation.get("destination", {})
        source_rel = source_data.get("relative_path")
        dest_rel = dest_data.get("relative_path")
        category = operation.get("category")
        if category not in allowed_categories or not isinstance(source_rel, str) or not safe_relative_file(source_rel):
            raise OrganizerError("Plan contains an unsafe source or category.", 3)
        dest_parts = Path(str(dest_rel)).parts
        if len(dest_parts) != 2 or dest_parts[0] != category or not safe_relative_file(dest_parts[1]):
            raise OrganizerError("Plan contains an unsafe destination.", 3)
        if source_rel in sources or str(dest_rel) in destinations:
            raise OrganizerError("Plan contains duplicate sources or destinations.", 3)
        sources.add(source_rel)
        destinations.add(str(dest_rel))

        source = root / source_rel
        try:
            actual = source.lstat()
        except FileNotFoundError as exc:
            raise OrganizerError(f"Source disappeared: {source_rel!r}", 3) from exc
        if not stat.S_ISREG(actual.st_mode) or stat.S_ISLNK(actual.st_mode):
            raise OrganizerError(f"Source is no longer a regular file: {source_rel!r}", 3)
        for key in ("device", "inode", "mode", "size", "mtime_ns", "ctime_ns"):
            actual_value = {
                "device": actual.st_dev, "inode": actual.st_ino, "mode": actual.st_mode,
                "size": actual.st_size, "mtime_ns": actual.st_mtime_ns, "ctime_ns": actual.st_ctime_ns,
            }[key]
            if source_data.get(key) != actual_value:
                raise OrganizerError(f"Source changed after planning: {source_rel!r}", 3)

        parent = root / category
        if os.path.lexists(parent):
            parent_stat = parent.lstat()
            if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
                raise OrganizerError(f"Unsafe category destination: {category}", 3)
            if parent_stat.st_dev != root_stat.st_dev:
                raise OrganizerError(f"Category is on another filesystem: {category}", 3)
            parent_ids[category] = (parent_stat.st_dev, parent_stat.st_ino)
        elif category not in create:
            raise OrganizerError(f"Missing unplanned category directory: {category}", 3)
        destination = root / str(dest_rel)
        if os.path.lexists(destination):
            raise OrganizerError(f"Destination appeared after planning: {dest_rel!r}", 3)
    return root, parent_ids


def atomic_move_no_replace(source_fd: int, source_name: str, destination_fd: int, destination_name: str) -> None:
    """Atomically rename one basename between pinned directories without following links."""
    if sys.platform != "darwin":
        raise OrganizerError("Atomic organization currently requires macOS renameatx_np.", 3)
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameatx_np
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    flags = RENAME_EXCL | RENAME_NOFOLLOW_ANY
    if rename(source_fd, os.fsencode(source_name), destination_fd, os.fsencode(destination_name), flags) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), destination_name)


def stat_at(directory_fd: int, name: str) -> os.stat_result:
    return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)


def matches_source(info: os.stat_result, source_data: dict[str, Any]) -> bool:
    values = {
        "device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and all(source_data.get(key) == value for key, value in values.items())


def matches_moved_source(info: os.stat_result, source_data: dict[str, Any]) -> bool:
    # Rename legitimately changes ctime; identity, mode, size, and mtime must remain.
    values = {
        "device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
        "size": info.st_size, "mtime_ns": info.st_mtime_ns,
    }
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and all(source_data.get(key) == value for key, value in values.items())


def append_journal(handle: Any, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def check_root_fd(root_fd: int, plan: dict[str, Any]) -> None:
    current = os.fstat(root_fd)
    if (current.st_dev, current.st_ino) != (plan["root"]["device"], plan["root"]["inode"]):
        raise OrganizerError("Pinned root identity does not match the plan.", 3)


def apply_plan(plan_path: Path, confirmation: str | None, dry_run: bool) -> tuple[dict[str, Any], int]:
    plan = load_plan(plan_path)
    if not dry_run and confirmation != plan["confirmation_token"]:
        raise OrganizerError("Exact plan confirmation token required.", 3)
    root, parent_ids = preflight(plan)
    root_fd = os.open(root, OPEN_DIRECTORY)
    try:
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OrganizerError("Another organizer apply is active for this root.", 3) from exc
        root, parent_ids = preflight(plan)
        check_root_fd(root_fd, plan)
        if dry_run:
            return {"success": True, "dry_run": True, "plan_id": plan["plan_id"], "move_count": len(plan["operations"]), "preflight": "passed"}, 0

        journal_path = Path(str(plan_path) + ".journal.jsonl")
        try:
            journal = journal_path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise OrganizerError(f"Journal already exists; refusing to reapply: {journal_path}", 3) from exc
        completed: list[dict[str, Any]] = []
        created_dirs: list[str] = []
        uncertain: list[dict[str, Any]] = []
        category_fds: dict[str, int] = {}
        with journal:
            append_journal(journal, {"event": "header", "plan": plan, "at_ns": time.time_ns()})
            try:
                for category in plan["create_directories"]:
                    os.mkdir(category, mode=0o755, dir_fd=root_fd)
                    category_fd = os.open(category, OPEN_DIRECTORY, dir_fd=root_fd)
                    category_fds[category] = category_fd
                    info = os.fstat(category_fd)
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                        raise OrganizerError(f"Unsafe created category: {category}", 3)
                    parent_ids[category] = (info.st_dev, info.st_ino)
                    created_dirs.append(category)
                    append_journal(journal, {"event": "directory-created", "category": category, "at_ns": time.time_ns()})
                for operation in plan["operations"]:
                    category = operation["category"]
                    if category not in category_fds:
                        descriptor = os.open(category, OPEN_DIRECTORY, dir_fd=root_fd)
                        info = os.fstat(descriptor)
                        if (info.st_dev, info.st_ino) != parent_ids[category]:
                            os.close(descriptor)
                            raise OrganizerError(f"Category changed before apply: {category}", 3)
                        category_fds[category] = descriptor
                for operation in plan["operations"]:
                    check_root_fd(root_fd, plan)
                    category = operation["category"]
                    category_fd = category_fds[category]
                    category_info = os.fstat(category_fd)
                    if stat.S_ISLNK(category_info.st_mode) or (category_info.st_dev, category_info.st_ino) != parent_ids[category]:
                        raise OrganizerError(f"Category changed during apply: {category}", 3)
                    category_path_info = stat_at(root_fd, category)
                    if (category_path_info.st_dev, category_path_info.st_ino) != parent_ids[category]:
                        raise OrganizerError(f"Category path no longer names the approved directory: {category}", 3)
                    source_rel = operation["source"]["relative_path"]
                    destination_rel = operation["destination"]["relative_path"]
                    destination_name = Path(destination_rel).name
                    source_info = stat_at(root_fd, source_rel)
                    if not matches_source(source_info, operation["source"]):
                        raise OrganizerError(f"Source changed immediately before move: {source_rel!r}", 3)
                    try:
                        stat_at(category_fd, destination_name)
                    except FileNotFoundError:
                        pass
                    else:
                        raise OrganizerError(f"Destination appeared during apply: {destination_rel!r}", 3)
                    append_journal(journal, {"event": "move-intent", "operation_id": operation["operation_id"], "source": source_rel, "destination": destination_rel, "at_ns": time.time_ns()})
                    atomic_move_no_replace(root_fd, source_rel, category_fd, destination_name)
                    uncertain.append({
                        "operation_id": operation["operation_id"],
                        "source": source_rel,
                        "destination": destination_rel,
                        "error": "Atomic rename succeeded but final identity and path binding are not yet verified.",
                    })
                    moved = stat_at(category_fd, destination_name)
                    category_path_after = stat_at(root_fd, category)
                    if (category_path_after.st_dev, category_path_after.st_ino) != parent_ids[category]:
                        uncertain[-1]["error"] = "Category path changed during the move; the actual destination path is uncertain."
                        append_journal(journal, {"event": "move-uncertain", **uncertain[-1], "at_ns": time.time_ns()})
                        raise OrganizerError(f"Category path changed during move: {category}", 4)
                    if not matches_moved_source(moved, operation["source"]):
                        uncertain[-1]["error"] = "Destination identity does not match the approved source; no reverse move was attempted."
                        append_journal(journal, {"event": "move-uncertain", **uncertain[-1], "at_ns": time.time_ns()})
                        raise OrganizerError(f"Source identity changed during move: {source_rel!r}", 4)
                    uncertain.pop()
                    record = {
                        "event": "move-complete", "operation_id": operation["operation_id"],
                        "source": source_rel, "destination": destination_rel,
                        "device": moved.st_dev, "inode": moved.st_ino, "at_ns": time.time_ns(),
                    }
                    completed.append(record)
                    append_journal(journal, record)
            except Exception as exc:
                append_journal(journal, {"event": "apply-failed", "error": str(exc), "at_ns": time.time_ns()})
                return {
                    "success": False, "error": str(exc), "journal": str(journal_path),
                    "completed_before_failure": [
                        {"operation_id": item["operation_id"], "source": item["source"], "destination": item["destination"]}
                        for item in completed
                    ],
                    "uncertain_operations": uncertain,
                    "created_directories": created_dirs,
                    "next_step": "Keep completed safe moves in place and generate a fresh plan for remaining loose files.",
                }, 4
            finally:
                for descriptor in category_fds.values():
                    os.close(descriptor)
            append_journal(journal, {"event": "apply-complete", "move_count": len(completed), "at_ns": time.time_ns()})
        return {
            "success": True, "plan_id": plan["plan_id"], "moved": len(completed),
            "created_directories": created_dirs, "journal": str(journal_path),
        }, 0
    finally:
        os.close(root_fd)


def bounded(value: int, minimum: int, maximum: int, name: str) -> int:
    if not minimum <= value <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
    return value


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Safely organize loose top-level download files")
    sub = root.add_subparsers(dest="command", required=True)
    inspect_cmd = sub.add_parser("inspect")
    inspect_cmd.add_argument("--root", default="~/Downloads")
    inspect_cmd.add_argument("--min-age-seconds", type=lambda value: bounded(int(value), 0, 86400, "min age"), default=DEFAULT_MIN_AGE)
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--root", default="~/Downloads")
    plan_cmd.add_argument("--output", required=True)
    plan_cmd.add_argument("--min-age-seconds", type=lambda value: bounded(int(value), 0, 86400, "min age"), default=DEFAULT_MIN_AGE)
    plan_cmd.add_argument("--ttl-seconds", type=lambda value: bounded(int(value), 60, 86400, "TTL"), default=DEFAULT_TTL)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--plan", required=True)
    mode = apply_cmd.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "inspect":
            root, _ = root_info(args.root)
            emit({"success": True, **inventory(root, args.min_age_seconds)})
            return 0
        if args.command == "plan":
            root, info = root_info(args.root)
            plan = make_plan(root, info, args.min_age_seconds, args.ttl_seconds)
            output = Path(args.output).expanduser().absolute()
            write_json_exclusive(output, plan)
            emit({"success": True, "plan_file": str(output), **plan})
            return 0
        result, code = apply_plan(Path(args.plan).expanduser().absolute(), args.confirm, args.dry_run)
        emit(result)
        return code
    except OrganizerError as exc:
        emit({"success": False, "error": str(exc), "code": exc.code})
        return exc.code
    except (OSError, ValueError) as exc:
        emit({"success": False, "error": str(exc), "code": 2})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
