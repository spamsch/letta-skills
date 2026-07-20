#!/usr/bin/env python3
"""Dependency-free Paperless-ngx CLI for the Letta skill."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RESOURCES = {
    "tags": ("tags", ["id", "name", "color", "is_inbox_tag", "document_count"]),
    "correspondents": ("correspondents", ["id", "name", "document_count"]),
    "document-types": ("document_types", ["id", "name", "document_count"]),
    "custom-fields": ("custom_fields", ["id", "name", "data_type"]),
}


class PaperlessError(RuntimeError):
    pass


def dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


class Client:
    def __init__(self) -> None:
        saved = dotenv(Path.home() / ".macbot" / ".env")
        self.url = next((v for v in (
            os.getenv("PAPERLESS_URL"), os.getenv("MACBOT_PAPERLESS_URL"),
            saved.get("PAPERLESS_URL"), saved.get("MACBOT_PAPERLESS_URL"),
        ) if v), "").rstrip("/")
        self.token = next((v for v in (
            os.getenv("PAPERLESS_API_TOKEN"), os.getenv("MACBOT_PAPERLESS_API_TOKEN"),
            saved.get("PAPERLESS_API_TOKEN"), saved.get("MACBOT_PAPERLESS_API_TOKEN"),
        ) if v), "")
        if not self.url or not self.token:
            raise PaperlessError(
                "Paperless is not configured. Set PAPERLESS_URL and PAPERLESS_API_TOKEN "
                "(MACBOT_PAPERLESS_* and ~/.macbot/.env are also supported)."
            )

    def call(self, method: str, endpoint: str, *, params: dict[str, Any] | None = None,
             payload: Any = None, body: bytes | None = None, content_type: str | None = None,
             binary: bool = False, timeout: int = 60) -> Any:
        url = self.url + endpoint + (("?" + urlencode(params, doseq=True)) if params else "")
        headers = {"Authorization": f"Token {self.token}", "Accept": "application/json"}
        if payload is not None:
            body, content_type = json.dumps(payload).encode(), "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        try:
            with urlopen(Request(url, data=body, headers=headers, method=method), timeout=timeout) as response:
                data = response.read()
                if binary:
                    return data
                if not data:
                    return None
                text = data.decode()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text.strip().strip('"')
        except HTTPError as exc:
            detail = exc.read(500).decode(errors="replace")
            raise PaperlessError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise PaperlessError(f"Connection error: {exc.reason}") from exc

    def all(self, resource: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.call("GET", f"/api/{resource}/", params={"page": page, "page_size": 100})
            items.extend(data.get("results", []))
            if not data.get("next"):
                return items
            page += 1

    def resolve(self, value: str | int | None, resource: str) -> int | None:
        if value is None:
            return None
        text = str(value).strip().strip('"').strip("'")
        if text.isdigit():
            return int(text)
        matches = [x for x in self.all(resource) if x.get("name", "").casefold() == text.casefold()]
        if len(matches) == 1:
            return int(matches[0]["id"])
        if not matches:
            raise PaperlessError(f"No {resource.replace('_', ' ')} named {text!r}.")
        raise PaperlessError(f"Ambiguous {resource.replace('_', ' ')} name {text!r}.")

    def tags(self, values: list[str] | None) -> list[int]:
        return [int(self.resolve(value, "tags")) for value in values or []]


def document(doc: dict[str, Any], content: bool = False) -> dict[str, Any]:
    fields = ["id", "title", "correspondent", "correspondent__name", "tags", "tags__name",
              "document_type", "document_type__name", "created", "added", "modified",
              "archive_serial_number", "original_file_name", "custom_fields"]
    if content:
        fields.append("content")
    return {field: doc.get(field) for field in fields if field in doc}


def config(c: Client, _a: argparse.Namespace) -> Any:
    data = c.call("GET", "/api/documents/", params={"page_size": 1})
    return {"success": True, "url": c.url, "reachable": True, "document_count": data.get("count")}


def search(c: Client, a: argparse.Namespace) -> Any:
    query, inbox = a.query or "", a.inbox
    if "is:inbox" in query:
        query, inbox = query.replace("is:inbox", "").strip(), True
    params: dict[str, Any] = {"page_size": a.limit}
    if query:
        params["query"] = query
    if inbox:
        params["is_in_inbox"] = "true"
    if a.tag:
        params["tags__id__all"] = ",".join(map(str, c.tags(a.tag)))
    for arg, resource, parameter in (
        (a.correspondent, "correspondents", "correspondent__id"),
        (a.document_type, "document_types", "document_type__id"),
    ):
        resolved = c.resolve(arg, resource)
        if resolved is not None:
            params[parameter] = resolved
    data = c.call("GET", "/api/documents/", params=params)
    return {"success": True, "count": data.get("count", 0),
            "documents": [document(x) for x in data.get("results", [])]}


def get(c: Client, a: argparse.Namespace) -> Any:
    return {"success": True, "document": document(c.call("GET", f"/api/documents/{a.id}/"), True)}


def custom_fields(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PaperlessError(f"custom fields must be valid JSON: {exc}") from exc
    value = [value] if isinstance(value, dict) else value
    if not isinstance(value, list):
        raise PaperlessError('custom fields must look like [{"field":1,"value":"EUR42.50"}]')
    result = []
    for item in value:
        if not isinstance(item, dict) or "field" not in item:
            raise PaperlessError("each custom field needs a field ID and value")
        try:
            result.append({"field": int(item["field"]), "value": item.get("value")})
        except (TypeError, ValueError) as exc:
            raise PaperlessError("custom field IDs must be integers") from exc
    return result


def update(c: Client, a: argparse.Namespace) -> Any:
    patch: dict[str, Any] = {}
    for key in ("title", "created"):
        value = getattr(a, key)
        if value is not None and value.strip():
            patch[key] = value
    for key, resource in (("correspondent", "correspondents"), ("document_type", "document_types")):
        value = getattr(a, key)
        if value is not None and value.strip():
            patch[key] = c.resolve(value, resource)
    if a.clear_tags:
        patch["tags"] = []
    elif a.tag:
        patch["tags"] = c.tags(a.tag)
    if a.clear_custom_fields:
        patch["custom_fields"] = []
    elif a.custom_fields:
        patch["custom_fields"] = custom_fields(a.custom_fields)
    if not patch:
        raise PaperlessError("No fields to update; omitted and blank values leave metadata unchanged.")
    doc = c.call("PATCH", f"/api/documents/{a.id}/", payload=patch)
    return {"success": True, "sent": patch, "document": document(doc)}


def multipart(path: Path, fields: list[tuple[str, str]]) -> tuple[bytes, str]:
    boundary = "----letta-paperless-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields:
        chunks += [f"--{boundary}\r\n".encode(),
                   f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()]
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    chunks += [f"--{boundary}\r\n".encode(),
               f'Content-Disposition: form-data; name="document"; filename="{path.name}"\r\n'.encode(),
               f"Content-Type: {mime}\r\n\r\n".encode(), path.read_bytes(), b"\r\n",
               f"--{boundary}--\r\n".encode()]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload(c: Client, a: argparse.Namespace) -> Any:
    path = Path(a.file).expanduser().resolve()
    if not path.is_file():
        raise PaperlessError(f"File not found: {path}")
    fields: list[tuple[str, str]] = []
    if a.title:
        fields.append(("title", a.title))
    for key, resource in (("correspondent", "correspondents"), ("document_type", "document_types")):
        value = getattr(a, key)
        if value is not None:
            fields.append((key, str(c.resolve(value, resource))))
    fields += [("tags", str(tag)) for tag in c.tags(a.tag)]
    body, content_type = multipart(path, fields)
    task = c.call("POST", "/api/documents/post_document/", body=body,
                  content_type=content_type, timeout=120)
    return {"success": True, "task_id": task, "file": str(path)}


def download(c: Client, a: argparse.Namespace) -> Any:
    info = c.call("GET", f"/api/documents/{a.id}/")
    name = info.get("original_file_name") or f"document_{a.id}.pdf"
    out = Path(a.output).expanduser() if a.output else Path.home() / "Downloads"
    if (out.exists() and out.is_dir()) or str(a.output or "").endswith("/"):
        out /= name
    out.parent.mkdir(parents=True, exist_ok=True)
    data = c.call("GET", f"/api/documents/{a.id}/download/", binary=True)
    out.write_bytes(data)
    return {"success": True, "path": str(out.resolve()), "bytes": len(data)}


def listing(c: Client, a: argparse.Namespace) -> Any:
    endpoint, fields = RESOURCES[a.resource]
    items = c.all(endpoint)
    return {"success": True, "count": len(items), a.resource:
            [{key: item.get(key) for key in fields} for item in items]}


def create(c: Client, a: argparse.Namespace) -> Any:
    endpoint = RESOURCES[a.resource][0]
    payload: dict[str, Any] = {"name": a.name}
    if a.resource == "tags":
        if a.color:
            payload["color"] = a.color
        if a.inbox:
            payload["is_inbox_tag"] = True
    item = c.call("POST", f"/api/{endpoint}/", payload=payload)
    return {"success": True, "created": {"id": item.get("id"), "name": item.get("name")}}


def delete(c: Client, a: argparse.Namespace) -> Any:
    endpoint = RESOURCES[a.resource][0]
    c.call("DELETE", f"/api/{endpoint}/{a.id}/")
    return {"success": True, "deleted": {"resource": a.resource, "id": a.id}}


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Interact with Paperless-ngx")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("config")
    p = sub.add_parser("search"); p.add_argument("--query", default=""); p.add_argument("--limit", type=int, default=10)
    p.add_argument("--inbox", action="store_true"); p.add_argument("--tag", action="append")
    p.add_argument("--correspondent"); p.add_argument("--document-type", dest="document_type")
    p = sub.add_parser("get"); p.add_argument("id", type=int)
    p = sub.add_parser("update"); p.add_argument("id", type=int); p.add_argument("--title"); p.add_argument("--created")
    p.add_argument("--tag", action="append"); p.add_argument("--correspondent"); p.add_argument("--document-type", dest="document_type")
    p.add_argument("--custom-fields"); p.add_argument("--clear-tags", action="store_true"); p.add_argument("--clear-custom-fields", action="store_true")
    p = sub.add_parser("upload"); p.add_argument("file"); p.add_argument("--title"); p.add_argument("--tag", action="append")
    p.add_argument("--correspondent"); p.add_argument("--document-type", dest="document_type")
    p = sub.add_parser("download"); p.add_argument("id", type=int); p.add_argument("--output")
    p = sub.add_parser("list"); p.add_argument("resource", choices=RESOURCES)
    p = sub.add_parser("create-metadata"); p.add_argument("resource", choices=("tags", "correspondents", "document-types"))
    p.add_argument("name"); p.add_argument("--color"); p.add_argument("--inbox", action="store_true")
    p = sub.add_parser("delete-metadata"); p.add_argument("resource", choices=("tags", "correspondents", "document-types")); p.add_argument("id", type=int)
    return root


COMMANDS = {"config": config, "search": search, "get": get, "update": update, "upload": upload,
            "download": download, "list": listing, "create-metadata": create, "delete-metadata": delete}


def main() -> int:
    args = build_parser().parse_args()
    try:
        print(json.dumps(COMMANDS[args.command](Client(), args), indent=2, ensure_ascii=False))
        return 0
    except (PaperlessError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
