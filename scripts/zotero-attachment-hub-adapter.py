#!/usr/bin/env python3
"""Adapt lit-search-cite Zotero handoff queues to Zotero Attachment Hub.

The script only writes explicit output paths. It never reads or writes
zotero.sqlite, browser cookies, credentials, or publisher sessions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


HUB_QUEUE_SCHEMA = "zotero-attachment-hub.queue.v1"
LINK_MAP_SCHEMA = "lit-search-cite.zotero-link-map.v1"
DEFAULT_API_BASE = "http://127.0.0.1:23119/api/users/0"


class AdapterError(RuntimeError):
    """Raised when an adapter operation cannot continue safely."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def atomic_write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    json.loads(payload)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def queue_counts(queue: Any) -> dict[str, int]:
    if not isinstance(queue, dict):
        queue = {}
    return {name: len(listify(queue.get(name))) for name in ("pending", "processing", "processed", "failed")}


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(".,;)]}").lower()


def doi_url(doi: Any) -> str:
    clean = normalize_doi(doi)
    return f"https://doi.org/{clean}" if clean else ""


def zotero_select_uri(key: str) -> str:
    return f"zotero://select/library/items/{key}" if key else ""


def zotero_open_pdf_uri(key: str) -> str:
    return f"zotero://open-pdf/library/items/{key}" if key else ""


def empty_hub_queue() -> dict[str, list[dict[str, Any]]]:
    return {"pending": [], "processing": [], "processed": [], "failed": []}


def listify(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def equivalent_task_key(task: dict[str, Any]) -> str:
    return "|".join([
        str(task.get("type") or "si").strip().lower(),
        normalize_doi(task.get("doi")),
        str(task.get("zoteroKey") or task.get("key") or "").strip(),
    ])


def normalize_hub_task(task: Any) -> dict[str, Any] | None:
    if isinstance(task, str):
        task = {"type": "si", "doi": task}
    if not isinstance(task, dict):
        return None
    task_type = str(task.get("type") or "si").strip().lower()
    if task_type not in {"si", "pdf", "fill-missing-pdf", "list-missing-pdf-doi"}:
        return None
    doi = normalize_doi(task.get("doi"))
    zotero_key = str(task.get("zoteroKey") or task.get("key") or "").strip()
    if task_type in {"si", "pdf"} and not doi and not zotero_key:
        return None
    normalized = dict(task)
    normalized.update({
        "type": task_type,
        "doi": doi,
        "status": task.get("status") or "pending",
        "createdAt": task.get("createdAt") or utc_now(),
    })
    if zotero_key:
        normalized["zoteroKey"] = zotero_key
    else:
        normalized.pop("zoteroKey", None)
    return normalized


def normalize_hub_queue(queue: Any) -> dict[str, list[dict[str, Any]]]:
    normalized = empty_hub_queue()
    if not isinstance(queue, dict):
        return normalized
    for list_name in ("pending", "processing", "processed", "failed"):
        seen: set[str] = set()
        for task in listify(queue.get(list_name)):
            normalized_task = normalize_hub_task(task)
            if not normalized_task:
                continue
            key = equivalent_task_key(normalized_task)
            if key in seen:
                continue
            seen.add(key)
            normalized[list_name].append(normalized_task)
    return normalized


def source_items_from_handoff(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("items") or data.get("pending") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [dict(item) for item in items if isinstance(item, dict)]


def captured_items(capture_dir: Path | None) -> list[dict[str, Any]]:
    if not capture_dir:
        return []
    captured_path = capture_dir / "captured.json"
    if not captured_path.exists():
        return []
    data = read_json(captured_path)
    if isinstance(data, dict):
        data = data.get("items") or data.get("articles") or []
    if not isinstance(data, list):
        return []
    return [dict(item) for item in data if isinstance(item, dict)]


def merge_capture_metadata(queue_items: list[dict[str, Any]], capture_dir: Path | None) -> list[dict[str, Any]]:
    captured = captured_items(capture_dir)
    by_doi = {normalize_doi(item.get("doi")): item for item in captured if normalize_doi(item.get("doi"))}
    merged: list[dict[str, Any]] = []
    for item in queue_items:
        doi = normalize_doi(item.get("doi"))
        combined = dict(item)
        if doi in by_doi:
            richer = dict(by_doi[doi])
            richer.update({key: value for key, value in item.items() if value not in ("", None, [])})
            combined = richer
        merged.append(combined)
    if not queue_items:
        merged.extend(captured)
    return merged


def filter_items_by_doi(items: list[dict[str, Any]], dois: list[str]) -> list[dict[str, Any]]:
    wanted = [normalize_doi(doi) for doi in dois if normalize_doi(doi)]
    if not wanted:
        return items
    by_doi = {normalize_doi(item.get("doi")): item for item in items if normalize_doi(item.get("doi"))}
    return [by_doi[doi] for doi in wanted if doi in by_doi]


def compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in data.items()
        if value not in ("", None, []) and value != {}
    }


def creator_from_name(name: str) -> dict[str, str]:
    text = str(name or "").strip()
    if not text:
        return {}
    if "," in text:
        last, first = [part.strip() for part in text.split(",", 1)]
        return compact_dict({"firstName": first, "lastName": last, "creatorType": "author"})
    parts = text.split()
    if len(parts) == 1:
        return {"lastName": parts[0], "creatorType": "author"}
    return {"firstName": " ".join(parts[:-1]), "lastName": parts[-1], "creatorType": "author"}


def creators_from_authors(value: Any) -> list[dict[str, str]]:
    authors = value if isinstance(value, list) else []
    creators: list[dict[str, str]] = []
    for author in authors:
        if isinstance(author, dict):
            creator = compact_dict({
                "firstName": author.get("firstName") or author.get("given") or "",
                "lastName": author.get("lastName") or author.get("family") or author.get("name") or "",
                "creatorType": author.get("creatorType") or "author",
            })
        else:
            creator = creator_from_name(str(author))
        if creator.get("firstName") or creator.get("lastName"):
            creators.append(creator)
    return creators


def zotero_metadata_from_article(item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    title = str(item.get("title") or "").strip()
    doi = normalize_doi(item.get("doi"))
    item_type = str(item.get("itemType") or "").strip()
    if not item_type:
        item_type = "journalArticle"
        warnings.append(f"{doi or title}: itemType missing; defaulted to journalArticle")
    metadata = {
        "itemType": item_type,
        "title": title,
        "creators": creators_from_authors(item.get("authors")),
        "publicationTitle": item.get("journal") or item.get("venue") or "",
        "date": item.get("date") or item.get("year") or "",
        "year": item.get("year") or "",
        "DOI": doi,
        "url": item.get("url") or item.get("doi_url") or doi_url(doi),
        "abstractNote": item.get("abstract") or "",
    }
    return compact_dict(metadata)


def local_pdf_info(item: dict[str, Any], capture_dir: Path | None, warnings: list[str]) -> dict[str, Any]:
    pdf_status = str(item.get("pdf_status") or "")
    pdf_path_value = str(item.get("pdf_path") or "").strip()
    if pdf_status != "downloaded" or not pdf_path_value or not capture_dir:
        return {}
    candidate = Path(pdf_path_value)
    full = candidate if candidate.is_absolute() else capture_dir / candidate
    full = full.resolve()
    try:
        full.relative_to(capture_dir.resolve())
    except ValueError:
        warnings.append(f"{item.get('doi') or item.get('title')}: pdf_path escapes capture_dir")
        return {}
    if not full.exists() or not full.is_file():
        warnings.append(f"{item.get('doi') or item.get('title')}: local PDF does not exist: {full}")
        return {}
    if full.stat().st_size <= 0:
        warnings.append(f"{item.get('doi') or item.get('title')}: local PDF is empty: {full}")
        return {}
    if full.suffix.lower() != ".pdf":
        warnings.append(f"{item.get('doi') or item.get('title')}: local file is not .pdf: {full}")
        return {}
    with full.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        warnings.append(f"{item.get('doi') or item.get('title')}: local file header is not %PDF-: {full}")
        return {}
    sha = file_sha256(full)
    return {
        "localPath": str(full),
        "mimeType": "application/pdf",
        "fileSha256": sha,
    }


def build_hub_tasks(
    items: list[dict[str, Any]],
    *,
    capture_dir: Path | None = None,
    task_type: str = "pdf",
    create_parent_if_missing: bool = False,
    max_items: int = 0,
    created_at: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    tasks: list[dict[str, Any]] = []
    warnings: list[str] = []
    created_at = created_at or utc_now()
    for item in items:
        doi = normalize_doi(item.get("doi"))
        zotero_key = str(item.get("zotero_key") or item.get("zoteroKey") or item.get("zoteroKeyMatched") or "").strip()
        metadata = zotero_metadata_from_article(item, warnings)
        title = str(metadata.get("title") or item.get("title") or "").strip()
        if not title:
            warnings.append(f"skipped item without title: {doi or item.get('id') or '(unknown)'}")
            continue
        if not doi and not zotero_key:
            warnings.append(f"skipped item without DOI or Zotero key: {title or item.get('id') or '(untitled)'}")
            continue
        pdf_info = local_pdf_info(item, capture_dir, warnings)
        dedupe_key = "|".join(part for part in [
            "lit-search-cite",
            doi,
            pdf_info.get("fileSha256") or "",
            pdf_info.get("localPath") or "",
        ] if part)
        task = {
            "type": task_type,
            "doi": doi,
            "zoteroKey": zotero_key,
            "createParentIfMissing": bool(create_parent_if_missing),
            "status": "pending",
            "createdAt": created_at,
            "source": "lit-search-cite",
            "sourceItemId": item.get("id") or (f"doi:{doi}" if doi else ""),
            "title": title,
            "dedupeKey": dedupe_key,
            "metadata": metadata,
            "captureDir": item.get("capture_dir") or "",
            "pdfStatus": item.get("pdf_status") or "",
            "pdfPath": item.get("pdf_path") or "",
            "pdfUrl": item.get("pdf_url") or "",
            "oaStatus": item.get("oa_status") or "",
            "license": item.get("license") or "",
        }
        task.update(pdf_info)
        task = compact_dict(task)
        normalized = normalize_hub_task(task)
        if not normalized:
            warnings.append(f"skipped invalid Attachment Hub task for DOI {doi or '(missing)'}")
            continue
        tasks.append(normalized)
        if max_items and len(tasks) >= max_items:
            break
    return tasks, warnings


def build_staging_queue(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    queue = empty_hub_queue()
    queue["pending"] = tasks
    queue["schema"] = HUB_QUEUE_SCHEMA
    queue["createdAt"] = utc_now()
    queue["producer"] = "lit-search-cite"
    queue["contractStatus"] = "attachment_hub_runtime_queue"
    queue["safety"] = {
        "writesZoteroSqlite": False,
        "readsBrowserCookies": False,
        "bypassesPaywalls": False,
        "requiresZoteroAttachmentHub": True,
    }
    return queue


def merge_hub_queue(existing: Any, new_tasks: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int, int, int]:
    queue = normalize_hub_queue(existing)
    locked_keys = {
        equivalent_task_key(task)
        for list_name in ("processing", "processed")
        for task in queue[list_name]
    }
    pending_index = {equivalent_task_key(task): index for index, task in enumerate(queue["pending"])}
    added = 0
    skipped = 0
    upgraded = 0
    for task in new_tasks:
        key = equivalent_task_key(task)
        if key in locked_keys:
            skipped += 1
            continue
        if key in pending_index:
            index = pending_index[key]
            old = queue["pending"][index]
            upgraded_task = dict(old)
            for field, value in task.items():
                if value not in ("", None, [], {}):
                    upgraded_task[field] = value
            upgraded_task["status"] = old.get("status") or "pending"
            upgraded_task["createdAt"] = old.get("createdAt") or task.get("createdAt")
            upgraded_task["updatedAt"] = utc_now()
            queue["pending"][index] = upgraded_task
            upgraded += 1
            continue
        queue["pending"].append(task)
        pending_index[key] = len(queue["pending"]) - 1
        added += 1
    return queue, added, skipped, upgraded


def latest_zotero_profile() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AdapterError("APPDATA is not set; cannot locate Zotero profile.")
    profiles_root = Path(appdata) / "Zotero" / "Zotero" / "Profiles"
    if not profiles_root.exists():
        raise AdapterError(f"Zotero profile root does not exist: {profiles_root}")
    profiles = [path for path in profiles_root.iterdir() if path.is_dir()]
    if not profiles:
        raise AdapterError(f"No Zotero profile directories found under {profiles_root}")
    return max(profiles, key=lambda path: path.stat().st_mtime)


def default_profile_queue_path() -> Path:
    return latest_zotero_profile() / "zotero-attachment-hub" / "queue.json"


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak-{now_stamp()}")
    shutil.copy2(path, backup)
    return backup


def fetch_zotero_items(url: str, timeout: float) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def zotero_parent_matches(payload: list[dict[str, Any]], doi: str) -> list[dict[str, Any]]:
    matches = []
    for entry in payload:
        data = entry.get("data") or {}
        if str(data.get("itemType") or "").lower() == "attachment":
            continue
        item_doi = normalize_doi(data.get("DOI"))
        if item_doi != doi:
            continue
        key = str(data.get("key") or entry.get("key") or "").strip()
        matches.append({
            "key": key,
            "doi": item_doi,
            "title": data.get("title") or "",
            "itemType": data.get("itemType") or "",
            "deleted": bool(data.get("deleted")),
            "zotero_select": zotero_select_uri(key),
        })
    return matches


def scan_zotero_items_for_doi(
    doi: str,
    api_base: str,
    timeout: float,
    *,
    scan_limit: int = 500,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for start in range(0, max(0, scan_limit), page_size):
        query = urllib.parse.urlencode({
            "format": "json",
            "include": "data,meta",
            "includeTrashed": "1",
            "limit": min(page_size, scan_limit - start),
            "start": start,
        })
        payload = fetch_zotero_items(f"{api_base.rstrip('/')}/items?{query}", timeout)
        matches.extend(zotero_parent_matches(payload, doi))
        if len(payload) < page_size:
            break
    return matches


def query_zotero_for_doi(doi: str, api_base: str = DEFAULT_API_BASE, timeout: float = 5.0) -> dict[str, Any]:
    doi = normalize_doi(doi)
    if not doi:
        return {"doi": "", "match_status": "no_doi", "matches": []}
    query = urllib.parse.urlencode({
        "format": "json",
        "include": "data,meta",
        "includeTrashed": "1",
        "q": doi,
    })
    url = f"{api_base.rstrip('/')}/items?{query}"
    matches = zotero_parent_matches(fetch_zotero_items(url, timeout), doi)
    if not matches:
        matches = scan_zotero_items_for_doi(doi, api_base, timeout)
    if len(matches) == 1 and not matches[0].get("deleted"):
        status = "unique"
    elif matches:
        status = "ambiguous_or_trashed"
    else:
        status = "not_found"
    return {"doi": doi, "match_status": status, "matches": matches}


def build_link_map_from_matches(tasks: list[dict[str, Any]], matches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for task in tasks:
        doi = normalize_doi(task.get("doi"))
        result = matches.get(doi) or {"doi": doi, "match_status": "not_checked", "matches": []}
        exact = result.get("matches") or []
        item: dict[str, Any] = {
            "doi": doi,
            "title": task.get("title") or "",
            "match_status": result.get("match_status") or "not_checked",
        }
        if result.get("match_status") == "unique" and exact:
            key = str(exact[0].get("key") or "")
            item.update({
                "zotero_key": key,
                "zotero_select": zotero_select_uri(key),
                "zotero_uri": zotero_select_uri(key),
            })
        items.append(item)
    return {
        "schema": LINK_MAP_SCHEMA,
        "created_at": utc_now(),
        "source": "zotero-local-api",
        "items": items,
    }


def build_link_map_from_processed_queue(queue: Any) -> dict[str, Any]:
    normalized = normalize_hub_queue(queue)
    items: list[dict[str, Any]] = []
    for task in normalized["processed"]:
        doi = normalize_doi(task.get("doi"))
        parent_key = str(task.get("parentKey") or task.get("zoteroKey") or "").strip()
        attachment_key = str(task.get("attachmentKey") or "").strip()
        item: dict[str, Any] = {
            "doi": doi,
            "title": task.get("title") or "",
            "status": "processed",
            "task_type": task.get("type") or "",
            "reason": task.get("reason") or "",
            "note": task.get("note") or "",
            "result": task.get("result") or "",
            "filename": task.get("filename") or "",
            "source": task.get("source") or "",
            "url": task.get("url") or "",
            "zotero_link_status": "verified" if parent_key else "missing_parent_key",
            "zotero_link_verified_at": task.get("updatedAt") or task.get("finishedAt") or utc_now(),
        }
        if parent_key:
            item.update({
                "zotero_item_key": parent_key,
                "zotero_item_uri": zotero_select_uri(parent_key),
                "zotero_key": parent_key,
                "zotero_select": zotero_select_uri(parent_key),
                "zotero_uri": zotero_select_uri(parent_key),
            })
        if attachment_key:
            item.update({
                "zotero_attachment_keys": [attachment_key],
                "zotero_attachment_uris": [zotero_open_pdf_uri(attachment_key)],
                "zotero_attachment_key": attachment_key,
                "zotero_attachment_uri": zotero_open_pdf_uri(attachment_key),
            })
        items.append(item)
    return {
        "schema": LINK_MAP_SCHEMA,
        "created_at": utc_now(),
        "source": "attachment-hub-queue-processed",
        "items": items,
    }


def copy_capture_with_links(capture_dir: Path, link_map: dict[str, Any], out_dir: Path | None = None) -> tuple[int, Path]:
    captured_path = capture_dir / "captured.json"
    if not captured_path.exists():
        raise AdapterError(f"captured.json does not exist: {captured_path}")
    if out_dir is None:
        out_dir = capture_dir.parent / f"{capture_dir.name}_zotero_enriched_{now_stamp()}"
    if out_dir.exists():
        raise AdapterError(f"enriched capture output already exists: {out_dir}")
    shutil.copytree(capture_dir, out_dir)
    captured_path = out_dir / "captured.json"
    data = read_json(captured_path)
    if isinstance(data, dict):
        articles = data.get("items") or data.get("articles")
    else:
        articles = data
    if not isinstance(articles, list):
        raise AdapterError(f"captured.json must contain a list or items list: {captured_path}")
    by_doi = {normalize_doi(item.get("doi")): item for item in link_map.get("items", []) if isinstance(item, dict)}
    changed = 0
    for article in articles:
        if not isinstance(article, dict):
            continue
        mapped = by_doi.get(normalize_doi(article.get("doi")))
        if not mapped:
            continue
        updates = {
            "zotero_item_key": mapped.get("zotero_item_key") or mapped.get("zotero_key") or "",
            "zotero_item_uri": mapped.get("zotero_item_uri") or mapped.get("zotero_select") or "",
            "zotero_key": mapped.get("zotero_item_key") or mapped.get("zotero_key") or "",
            "zoteroKey": mapped.get("zotero_item_key") or mapped.get("zotero_key") or "",
            "zotero_select": mapped.get("zotero_item_uri") or mapped.get("zotero_select") or "",
            "zoteroSelect": mapped.get("zotero_item_uri") or mapped.get("zotero_select") or "",
            "zotero_uri": mapped.get("zotero_item_uri") or mapped.get("zotero_uri") or "",
            "zotero_attachment_keys": mapped.get("zotero_attachment_keys") or [],
            "zotero_attachment_uris": mapped.get("zotero_attachment_uris") or [],
            "zotero_attachment_key": mapped.get("zotero_attachment_key") or "",
            "zotero_attachment_uri": mapped.get("zotero_attachment_uri") or "",
            "zotero_link_status": mapped.get("zotero_link_status") or "",
            "zotero_link_verified_at": mapped.get("zotero_link_verified_at") or "",
        }
        for key in list(updates):
            if not updates[key]:
                updates.pop(key)
        if not updates:
            continue
        before = {key: article.get(key) for key in updates}
        article.update(updates)
        if any(before.get(key) != updates[key] for key in updates):
            changed += 1
    if not changed:
        return 0, out_dir
    write_json(data, captured_path)
    write_json(link_map, out_dir / "zotero_link_map.json")
    return changed, out_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adapt lit-search-cite Zotero queues to Zotero Attachment Hub runtime queues.")
    parser.add_argument("--input-queue", required=True, help="lit-search-cite intermediate zotero_queue.json.")
    parser.add_argument("--capture-dir", default="", help="Matching lit-search-cite capture directory used for metadata and local PDFs.")
    parser.add_argument("--out", default="", help="Staging Attachment Hub queue output path.")
    parser.add_argument("--task-type", choices=["pdf", "si"], default="pdf", help="Attachment Hub task type for per-item tasks.")
    parser.add_argument("--doi", action="append", default=[], help="Restrict tasks to this DOI. May be repeated.")
    parser.add_argument("--max-items", type=int, default=0, help="Limit tasks for controlled smoke tests.")
    parser.add_argument("--create-parent-if-missing", action="store_true", help="Allow Attachment Hub to create a Zotero parent item from task metadata.")
    parser.add_argument("--match-zotero-local-api", action="store_true", help="Read-only match DOI to Zotero parent items via local API.")
    parser.add_argument("--zotero-api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--link-map-out", default="", help="Write Zotero key/URI mapping JSON.")
    parser.add_argument("--profile-queue-path", default="", help="Existing Attachment Hub profile queue. Defaults to latest Zotero profile.")
    parser.add_argument("--apply-profile-queue", action="store_true", help="Backup and merge pending tasks into the real profile queue.")
    parser.add_argument("--processed-queue", default="", help="Read a processed Attachment Hub queue and build a link map from its results.")
    parser.add_argument("--update-capture-dir", default="", help="Create an enriched copy of this capture dir with verified Zotero link fields.")
    parser.add_argument("--enriched-capture-out", default="", help="Output directory for the enriched capture copy.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_queue = Path(args.input_queue).expanduser().resolve()
    handoff = read_json(input_queue)
    workflow_dir = input_queue.parent
    capture_dir = Path(args.capture_dir).expanduser().resolve() if args.capture_dir else None
    out_path = Path(args.out).expanduser().resolve() if args.out else workflow_dir / "zotero_attachment_hub_queue.json"
    link_map_path = Path(args.link_map_out).expanduser().resolve() if args.link_map_out else workflow_dir / "zotero_link_map.json"

    items = filter_items_by_doi(merge_capture_metadata(source_items_from_handoff(handoff), capture_dir), args.doi)
    tasks, warnings = build_hub_tasks(
        items,
        capture_dir=capture_dir,
        task_type=args.task_type,
        create_parent_if_missing=args.create_parent_if_missing,
        max_items=max(0, args.max_items),
    )
    staging_queue = build_staging_queue(tasks)
    write_json(staging_queue, out_path)

    matches: dict[str, dict[str, Any]] = {}
    if args.match_zotero_local_api:
        for task in tasks:
            doi = normalize_doi(task.get("doi"))
            if not doi:
                continue
            try:
                matches[doi] = query_zotero_for_doi(doi, args.zotero_api_base)
            except Exception as exc:  # local Zotero may simply be closed
                matches[doi] = {"doi": doi, "match_status": "api_error", "matches": [], "error": str(exc)}
                warnings.append(f"Zotero local API match failed for {doi}: {exc}")
        write_json(build_link_map_from_matches(tasks, matches), link_map_path)

    processed_link_map: dict[str, Any] | None = None
    if args.processed_queue:
        processed_link_map = build_link_map_from_processed_queue(read_json(Path(args.processed_queue).expanduser().resolve()))
        write_json(processed_link_map, link_map_path)

    profile_queue_path = ""
    backup_path = ""
    profile_queue_sha256_before = ""
    profile_queue_counts_before: dict[str, int] = {}
    profile_queue_counts_after: dict[str, int] = {}
    added = 0
    skipped = 0
    upgraded = 0
    if args.apply_profile_queue:
        if len(tasks) > 2:
            raise AdapterError("--apply-profile-queue is limited to at most 2 tasks.")
        queue_path = Path(args.profile_queue_path).expanduser().resolve() if args.profile_queue_path else default_profile_queue_path()
        profile_queue_path = str(queue_path)
        existing = read_json(queue_path) if queue_path.exists() else empty_hub_queue()
        profile_queue_counts_before = queue_counts(existing)
        profile_queue_sha256_before = file_sha256(queue_path) if queue_path.exists() else ""
        merged, added, skipped, upgraded = merge_hub_queue(existing, tasks)
        profile_queue_counts_after = queue_counts(merged)
        backup = backup_file(queue_path)
        backup_path = str(backup) if backup else ""
        atomic_write_json(merged, queue_path)

    updated_capture = 0
    enriched_capture_dir = ""
    if args.update_capture_dir:
        link_map = processed_link_map or (read_json(link_map_path) if link_map_path.exists() else {})
        changed, enriched = copy_capture_with_links(
            Path(args.update_capture_dir).expanduser().resolve(),
            link_map,
            Path(args.enriched_capture_out).expanduser().resolve() if args.enriched_capture_out else None,
        )
        updated_capture = changed
        enriched_capture_dir = str(enriched)

    summary = {
        "schema": "lit-search-cite.zotero-attachment-hub-adapter.summary.v1",
        "created_at": utc_now(),
        "input_queue": str(input_queue),
        "staging_queue": str(out_path),
        "tasks_total": len(tasks),
        "task_type": args.task_type,
        "link_map": str(link_map_path) if (args.match_zotero_local_api or args.processed_queue) else "",
        "profile_queue": profile_queue_path,
        "profile_queue_applied": bool(args.apply_profile_queue),
        "profile_queue_backup": backup_path,
        "profile_queue_sha256_before": profile_queue_sha256_before,
        "profile_queue_counts_before": profile_queue_counts_before,
        "profile_queue_counts_after": profile_queue_counts_after,
        "profile_queue_added": added,
        "profile_queue_skipped_existing": skipped,
        "profile_queue_upgraded_pending": upgraded,
        "capture_updated_items": updated_capture,
        "enriched_capture_dir": enriched_capture_dir,
        "warnings": warnings,
        "safety": {
            "writes_zotero_sqlite": False,
            "reads_browser_cookies": False,
            "bypasses_paywalls": False,
            "writes_profile_queue_only_with_apply": True,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdapterError as exc:
        print(f"zotero-attachment-hub-adapter error: {exc}", file=sys.stderr)
        raise SystemExit(2)
