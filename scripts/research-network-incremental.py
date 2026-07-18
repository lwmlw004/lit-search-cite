#!/usr/bin/env python3
"""Plan incremental updates for the Research Knowledge Network.

The default path is read-only for the real vault. It inventories a new
lit-search-cite capture batch, prepares an analysis queue, writes an isolated
preview vault under the chosen output directory, and verifies the preview. The
formal apply path is guarded by explicit flags and is not used by tests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SCHEMA = "lit-search-cite.research-network-incremental.v1"
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


class IncrementalError(RuntimeError):
    """Raised when the incremental workflow cannot proceed safely."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = text.replace("\u2212", "-").replace("\u2010", "-").replace("\u2011", "-")
    text = text.replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"C\(sp\s*3\s*\)", "C(sp3)", text, flags=re.IGNORECASE)
    text = re.sub(r"S\s*H\s*2", "SH2", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(".,;)]}").lower()


def title_key(value: Any) -> str:
    text = normalize_text(value).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def safe_filename(value: str, max_len: int = 120) -> str:
    text = normalize_text(value)
    text = re.sub(r'[<>:"/\\|?*]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:max_len].rstrip(" .") or "untitled") + ".md"


def load_rkn_module():
    path = SCRIPT_DIR / "research-knowledge-network.py"
    spec = importlib.util.spec_from_file_location("research_knowledge_network", path)
    if spec is None or spec.loader is None:
        raise IncrementalError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_capture(capture_dir: Path) -> list[dict[str, Any]]:
    path = capture_dir / "captured.json"
    if not path.exists():
        raise IncrementalError(f"captured.json is missing: {capture_dir}")
    raw = read_json(path)
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("items") or raw.get("articles") or raw.get("references") or []
    else:
        raise IncrementalError("captured.json must be a list or object.")
    articles = [item for item in items if isinstance(item, dict)]
    if not articles:
        raise IncrementalError("No captured articles found.")
    return articles


def extract_dois(text: str) -> list[str]:
    pattern = re.compile(r"10\.\d{4,9}/[^\s<>{}\"|\\^`\[\]]+", flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for match in pattern.findall(text):
        doi = normalize_doi(match)
        if doi and doi not in seen:
            seen.add(doi)
            out.append(doi)
    return out


def vault_rel(vault: Path, path: Path) -> str:
    return path.resolve().relative_to(vault.resolve()).as_posix()


def validate_vault_readonly(vault: Path) -> None:
    if not vault.exists():
        raise IncrementalError(f"Vault does not exist: {vault}")
    if not (vault / ".obsidian").exists():
        raise IncrementalError(f"Not an Obsidian vault: {vault}")


def inventory_vault(vault: Path) -> dict[str, Any]:
    validate_vault_readonly(vault)
    literature = vault / "literature"
    notes: list[dict[str, Any]] = []
    doi_to_notes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if literature.exists():
        for path in sorted(literature.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            dois = extract_dois(text)
            note = {
                "path": str(path),
                "vault_relative_path": vault_rel(vault, path),
                "title": path.stem,
                "dois": dois,
                "has_managed_block": "<!-- codex-research-analysis:start -->" in text
                and "<!-- codex-research-analysis:end -->" in text,
                "sha256": file_sha256(path),
            }
            notes.append(note)
            for doi in dois:
                doi_to_notes[doi].append(note)
    return {
        "vault": str(vault),
        "literature_notes": notes,
        "literature_note_count": len(notes),
        "doi_to_notes": {doi: values for doi, values in sorted(doi_to_notes.items())},
    }


def duplicate_groups(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        if value:
            counts[value] += 1
    return {key: count for key, count in sorted(counts.items()) if count > 1}


def load_current_runtime(runtime_dir: Path | None) -> list[dict[str, Any]]:
    if not runtime_dir:
        return []
    network_path = runtime_dir / "knowledge_network.json"
    analysis_path = runtime_dir / "literature_analysis.json"
    if network_path.exists():
        data = read_json(network_path)
        return [item for item in data.get("articles", []) if isinstance(item, dict)]
    if analysis_path.exists():
        data = read_json(analysis_path)
        return [item for item in data.get("articles", []) if isinstance(item, dict)]
    return []


def capture_inventory(capture_dir: Path, articles: list[dict[str, Any]]) -> dict[str, Any]:
    article_rows: list[dict[str, Any]] = []
    for index, article in enumerate(articles, start=1):
        doi = normalize_doi(article.get("doi"))
        title = normalize_text(article.get("title"))
        article_rows.append({
            "index": index,
            "doi": doi,
            "title": title,
            "title_key": title_key(title),
            "year": article.get("year") or "",
            "journal": article.get("journal") or article.get("container_title") or "",
        })
    return {
        "capture_dir": str(capture_dir),
        "article_count": len(article_rows),
        "articles": article_rows,
        "duplicate_dois": duplicate_groups([row["doi"] for row in article_rows]),
        "duplicate_title_keys": duplicate_groups([row["title_key"] for row in article_rows]),
    }


def detect_version_pairs(capture_rows: list[dict[str, Any]], current_articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in capture_rows:
        if row["title_key"]:
            groups[row["title_key"]].append({
                "doi": row["doi"],
                "title": row["title"],
                "source": "incoming_capture",
            })
    for article in current_articles:
        key = title_key(article.get("title") or article.get("note_title"))
        doi = normalize_doi(article.get("doi"))
        if key and doi:
            groups[key].append({
                "doi": doi,
                "title": normalize_text(article.get("title") or article.get("note_title")),
                "source": "current_runtime",
            })
    pairs: list[dict[str, Any]] = []
    for key, values in sorted(groups.items()):
        unique_dois = sorted({item["doi"] for item in values if item["doi"]})
        if len(unique_dois) > 1:
            pairs.append({"title_key": key, "dois": unique_dois, "members": values})
    return pairs


def build_plan(
    capture: dict[str, Any],
    vault_inventory: dict[str, Any],
    current_articles: list[dict[str, Any]],
) -> dict[str, Any]:
    duplicate_dois = set(capture["duplicate_dois"])
    doi_to_notes = vault_inventory["doi_to_notes"]
    items: list[dict[str, Any]] = []
    for row in capture["articles"]:
        doi = row["doi"]
        matches = doi_to_notes.get(doi, []) if doi else []
        if not doi:
            action = "conflict_missing_doi"
            reason = "capture record has no DOI"
        elif doi in duplicate_dois:
            action = "duplicate_in_capture"
            reason = "same DOI appears multiple times in capture"
        elif len(matches) > 1:
            action = "conflict_duplicate_vault_notes"
            reason = "DOI matches multiple formal literature notes"
        elif len(matches) == 0:
            action = "new"
            reason = "DOI not present in current vault literature inventory"
        elif not matches[0].get("has_managed_block"):
            action = "update"
            reason = "existing note is missing Codex managed analysis block"
        else:
            action = "noop"
            reason = "existing note already has Codex managed analysis block"
        items.append({
            **row,
            "action": action,
            "reason": reason,
            "matched_notes": [note["vault_relative_path"] for note in matches],
        })
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item["action"]] += 1
    version_pairs = detect_version_pairs(capture["articles"], current_articles)
    version_pair_dois = {doi for pair in version_pairs for doi in pair["dois"]}
    analysis_queue = [
        item for item in items
        if item["action"] in {"new", "update"} or (item["doi"] in version_pair_dois and item["action"] != "noop")
    ]
    conflicts = [
        item for item in items
        if item["action"].startswith("conflict") or item["action"].startswith("duplicate")
    ]
    return {
        "schema": SCHEMA + ".prepare_plan",
        "created_at": utc_now(),
        "actions": dict(sorted(counts.items())),
        "items": items,
        "version_pairs": version_pairs,
        "analysis_queue": analysis_queue,
        "analysis_queue_count": len(analysis_queue),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "safe_to_apply": len(conflicts) == 0,
    }


def note_stub_for_article(rkn: Any, article: dict[str, Any]) -> tuple[str, str]:
    title = rkn.note_title_from_path(None, article)
    doi = normalize_doi(article.get("doi"))
    text = "\n".join([
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
        'source_type: "lit-search-cite"',
        f'doi: "{doi}"',
        "---",
        "",
        f"# {title}",
        "",
        "## Metadata",
        f"- DOI: {doi}",
        f"- Year: {article.get('year') or ''}",
        f"- Journal: {article.get('journal') or article.get('container_title') or ''}",
        "",
    ])
    return title, text


def copy_if_exists(src_root: Path, dst_root: Path, rel: str) -> None:
    src = src_root / PurePosixPath(rel)
    if not src.exists() or not src.is_file():
        return
    dst = dst_root / PurePosixPath(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def copy_markdown_vault(src_root: Path, dst_root: Path) -> int:
    count = 0
    for src in sorted(src_root.rglob("*.md")):
        if ".obsidian" in src.relative_to(src_root).parts:
            continue
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        count += 1
    return count


def target_paths_for_network(rkn: Any, vault: Path, network: dict[str, Any], network_title: str) -> list[Path]:
    paths: list[Path] = []
    for article in network["articles"]:
        if article.get("note_path"):
            paths.append(Path(article["note_path"]))
    for node in network["nodes"]:
        paths.append(vault / rkn.category_dir(node["category"]) / rkn.safe_filename(node["name"]))
    for question in network["research_questions"]:
        title = rkn.safe_note_title(str(question["id"]) + " - " + str(question["title"]))
        paths.append(vault / "Research Questions" / rkn.safe_filename(title))
    for experiment in network["experiment_suggestions"]:
        title = rkn.safe_note_title(str(experiment["id"]) + " - " + str(experiment["title"]))
        paths.append(vault / "Experiment Suggestions" / rkn.safe_filename(title))
    paths.append(vault / "Research Networks" / rkn.safe_filename(network_title))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path): file_sha256(path) if path.exists() and path.is_file() else "MISSING" for path in paths}


def diff_snapshots(before: dict[str, str], after: dict[str, str], root: Path) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for path, before_hash in sorted(before.items()):
        after_hash = after.get(path, "MISSING")
        if before_hash != after_hash:
            rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
            changes.append({"path": rel, "before": before_hash, "after": after_hash})
    return changes


def preview_update(
    capture_dir: Path,
    workflow_dir: Path | None,
    vault: Path,
    out_dir: Path,
    plan: dict[str, Any],
    network_title: str,
) -> dict[str, Any]:
    rkn = load_rkn_module()
    preview_vault = choose_preview_vault(out_dir)
    if preview_vault.exists():
        raise IncrementalError(f"Preview vault already exists: {preview_vault}")
    (preview_vault / ".obsidian").mkdir(parents=True)
    copied_markdown = copy_markdown_vault(vault, preview_vault)
    articles = load_capture(capture_dir)

    formal_network = rkn.build_network(capture_dir, workflow_dir, vault)
    formal_targets = target_paths_for_network(rkn, vault, formal_network, network_title)
    for target in formal_targets:
        try:
            rel = target.relative_to(vault.resolve()).as_posix()
        except ValueError:
            continue
        copy_if_exists(vault, preview_vault, rel)

    doi_to_item = {item["doi"]: item for item in plan["items"]}
    for article in articles:
        doi = normalize_doi(article.get("doi"))
        item = doi_to_item.get(doi)
        if not item or item["action"] != "new":
            continue
        title, text = note_stub_for_article(rkn, article)
        path = preview_vault / "literature" / rkn.safe_filename(title)
        write_text_atomic(path, text)

    preview_network = rkn.build_network(capture_dir, workflow_dir, preview_vault)
    preview_targets = target_paths_for_network(rkn, preview_vault, preview_network, network_title)
    before = snapshot(preview_targets)
    paths = rkn.write_outputs(out_dir / "analysis", preview_network)
    vault_result = rkn.write_vault_outputs(preview_vault, preview_network, network_title)
    write_json(out_dir / "obsidian_preview_write_result.json", vault_result)
    after = snapshot(preview_targets)
    changes = diff_snapshots(before, after, preview_vault)
    result = {
        "schema": SCHEMA + ".preview",
        "created_at": utc_now(),
        "preview_vault": str(preview_vault),
        "copied_markdown_files": copied_markdown,
        "analysis_out": str(out_dir / "analysis"),
        "paths": paths,
        "target_file_count": len(preview_targets),
        "target_files": [path.resolve().relative_to(preview_vault.resolve()).as_posix() for path in preview_targets],
        "changed_file_count": len(changes),
        "changed_files": changes,
        "vault_result": {
            "literature_notes_updated": [Path(path).resolve().relative_to(preview_vault.resolve()).as_posix() for path in vault_result.get("literature_notes_updated", [])],
            "question_notes": len(vault_result.get("question_notes", [])),
            "experiment_notes": len(vault_result.get("experiment_notes", [])),
            "node_notes": len(vault_result.get("node_notes", [])),
            "index_note": Path(vault_result["index_note"]).resolve().relative_to(preview_vault.resolve()).as_posix(),
        },
    }
    write_json(out_dir / "preview_diff.json", result)
    return result


def choose_preview_vault(out_dir: Path) -> Path:
    candidate = out_dir / "preview_vault"
    if len(str(candidate)) < 140:
        return candidate
    short_root = ROOT / "evals" / "workspace" / "rni"
    return short_root / now_stamp()


def verify_preview(capture_dir: Path, preview: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    preview_vault = Path(preview["preview_vault"])
    capture = load_capture(capture_dir)
    literature = sorted((preview_vault / "literature").glob("*.md"))
    note_names = {path.stem for path in preview_vault.rglob("*.md")}
    target_files = [
        preview_vault / PurePosixPath(rel)
        for rel in preview.get("target_files", [])
    ] or list(preview_vault.rglob("*.md"))
    doi_matches: dict[str, list[str]] = {}
    for article in capture:
        doi = normalize_doi(article.get("doi"))
        hits = []
        for path in literature:
            if doi and doi in path.read_text(encoding="utf-8", errors="replace").lower():
                hits.append(vault_rel(preview_vault, path))
        doi_matches[doi] = hits
    link_pattern = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")
    broken: list[dict[str, str]] = []
    for path in target_files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw in link_pattern.findall(text):
            target = raw.split("|", 1)[0].split("#", 1)[0].strip()
            if not target:
                continue
            target_name = PurePosixPath(target.replace("\\", "/")).stem
            if target_name not in note_names:
                broken.append({"file": vault_rel(preview_vault, path), "link": raw, "target_name": target_name})
    yaml_missing = [
        vault_rel(preview_vault, path)
        for path in target_files
        if path.exists()
        if not path.read_text(encoding="utf-8", errors="replace").startswith("---")
    ]
    result = {
        "schema": SCHEMA + ".verify",
        "created_at": utc_now(),
        "preview_vault": str(preview_vault),
        "doi_unique_matches": {doi: len(paths) for doi, paths in doi_matches.items()},
        "doi_match_paths": doi_matches,
        "broken_wikilinks_count": len(broken),
        "broken_wikilinks": broken[:100],
        "yaml_missing_count": len(yaml_missing),
        "yaml_missing": yaml_missing[:100],
        "has_obsidian_folder": (preview_vault / ".obsidian").exists(),
        "pdfs_copied": 0,
        "modifies_formal_vault": False,
        "ok": all(len(paths) == 1 for paths in doi_matches.values()) and not broken and not yaml_missing,
    }
    write_json(out_dir / "verify_report.json", result)
    return result


def build_batch_report(out_dir: Path, inventory: dict[str, Any], plan: dict[str, Any], preview: dict[str, Any], verify: dict[str, Any]) -> str:
    lines = [
        "# Research Network Incremental Batch Report",
        "",
        f"- Created at: `{utc_now()}`",
        f"- Capture articles: `{inventory['capture']['article_count']}`",
        f"- Formal literature notes inventoried: `{inventory['vault']['literature_note_count']}`",
        f"- Actions: `{json.dumps(plan['actions'], ensure_ascii=False, sort_keys=True)}`",
        f"- Analysis queue: `{plan['analysis_queue_count']}`",
        f"- Version pairs: `{len(plan['version_pairs'])}`",
        f"- Conflicts: `{plan['conflict_count']}`",
        f"- Preview changed files: `{preview['changed_file_count']}`",
        f"- Verify ok: `{verify['ok']}`",
        f"- Broken wikilinks: `{verify['broken_wikilinks_count']}`",
        f"- YAML missing: `{verify['yaml_missing_count']}`",
        "",
        "## Safety",
        "- Formal vault modified: `False`",
        "- Test vault modified: `False`",
        "- Zotero touched: `False`",
        "- PDFs copied: `0`",
        "- Network access: `False`",
        "",
        "## Next Step",
        "Run `--stage apply --allow-apply` only after reviewing this preview and confirming the vault target.",
    ]
    path = out_dir / "batch_report.md"
    write_text_atomic(path, "\n".join(lines) + "\n")
    return str(path)


def run_readonly(args: argparse.Namespace) -> dict[str, Any]:
    capture_dir = Path(args.capture_dir).expanduser().resolve()
    workflow_dir = Path(args.workflow_dir).expanduser().resolve() if args.workflow_dir else None
    vault = Path(args.vault).expanduser().resolve()
    runtime_dir = Path(args.current_runtime).expanduser().resolve() if args.current_runtime else None
    out_dir = Path(args.out).expanduser().resolve() if args.out else capture_dir / "research_network_incremental" / now_stamp()
    out_dir.mkdir(parents=True, exist_ok=True)

    articles = load_capture(capture_dir)
    cap_inv = capture_inventory(capture_dir, articles)
    vault_inv = inventory_vault(vault)
    current_articles = load_current_runtime(runtime_dir)
    plan = build_plan(cap_inv, vault_inv, current_articles)
    inventory = {
        "schema": SCHEMA + ".inventory",
        "created_at": utc_now(),
        "capture": cap_inv,
        "vault": {
            "vault": vault_inv["vault"],
            "literature_note_count": vault_inv["literature_note_count"],
            "doi_count": len(vault_inv["doi_to_notes"]),
        },
        "current_runtime_articles": len(current_articles),
    }
    write_json(out_dir / "inventory.json", inventory)
    write_json(out_dir / "prepare_plan.json", plan)
    write_json(out_dir / "analysis_queue.json", {"schema": SCHEMA + ".analysis_queue", "items": plan["analysis_queue"]})

    preview: dict[str, Any] = {}
    verify: dict[str, Any] = {}
    if args.stage in {"preview", "verify"}:
        preview = preview_update(capture_dir, workflow_dir, vault, out_dir, plan, args.network_title)
        verify = verify_preview(capture_dir, preview, out_dir)
        report = build_batch_report(out_dir, inventory, plan, preview, verify)
    else:
        report = str(out_dir / "prepare_plan.json")
    summary = {
        "ok": bool(not verify or verify.get("ok")),
        "schema": SCHEMA + ".summary",
        "stage": args.stage,
        "out_dir": str(out_dir),
        "inventory": str(out_dir / "inventory.json"),
        "prepare_plan": str(out_dir / "prepare_plan.json"),
        "analysis_queue": str(out_dir / "analysis_queue.json"),
        "preview_diff": str(out_dir / "preview_diff.json") if preview else "",
        "verify_report": str(out_dir / "verify_report.json") if verify else "",
        "batch_report": report,
        "actions": plan["actions"],
        "analysis_queue_count": plan["analysis_queue_count"],
        "conflict_count": plan["conflict_count"],
        "version_pair_count": len(plan["version_pairs"]),
        "preview_changed_file_count": preview.get("changed_file_count", 0),
        "broken_wikilinks_count": verify.get("broken_wikilinks_count", 0) if verify else 0,
        "formal_vault_modified": False,
        "zotero_touched": False,
        "pdfs_copied": 0,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def backup_apply_targets(rkn: Any, vault: Path, network: dict[str, Any], network_title: str, backup_root: Path) -> dict[str, Any]:
    backup_dir = backup_root / now_stamp()
    files_dir = backup_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=False)
    items: list[dict[str, Any]] = []
    for target in target_paths_for_network(rkn, vault, network, network_title):
        if not target.exists() or not target.is_file():
            continue
        rel = target.relative_to(vault.resolve())
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        items.append({
            "vault_relative_path": rel.as_posix(),
            "sha256": file_sha256(target),
            "backup_relative_path": dest.relative_to(backup_dir).as_posix(),
        })
    manifest = {
        "schema": SCHEMA + ".apply_backup",
        "created_at": utc_now(),
        "vault": str(vault),
        "items": items,
        "item_count": len(items),
    }
    write_json(backup_dir / "manifest.json", manifest)
    return {"backup_dir": str(backup_dir), "item_count": len(items)}


def run_apply(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_apply:
        raise IncrementalError("Refusing apply without --allow-apply.")
    if not args.obsidian_importer:
        raise IncrementalError("--stage apply requires --obsidian-importer.")
    capture_dir = Path(args.capture_dir).expanduser().resolve()
    workflow_dir = Path(args.workflow_dir).expanduser().resolve() if args.workflow_dir else None
    vault = Path(args.vault).expanduser().resolve()
    validate_vault_readonly(vault)
    out_dir = Path(args.out).expanduser().resolve() if args.out else capture_dir / "research_network_incremental" / now_stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    readonly = run_readonly(argparse.Namespace(**{**vars(args), "stage": "preview", "out": str(out_dir / "pre_apply_preview")}))
    if readonly["conflict_count"]:
        raise IncrementalError("Refusing apply while prepare plan contains conflicts.")
    rkn = load_rkn_module()
    network_before = rkn.build_network(capture_dir, workflow_dir, vault)
    backup = backup_apply_targets(rkn, vault, network_before, args.network_title, ROOT / "backups" / "research-network-incremental")
    importer = Path(args.obsidian_importer).expanduser().resolve()
    cmd = [
        sys.executable,
        str(importer),
        "import-capture",
        "--capture-dir",
        str(capture_dir),
        "--vault",
        str(vault),
        "--no-copy-pdfs",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise IncrementalError(f"import-capture failed: {completed.stderr.strip()}")
    expected_vault = vault.resolve()

    def validate_apply_vault(target: Path) -> None:
        target = Path(target).resolve()
        if target != expected_vault:
            raise IncrementalError(f"Unexpected apply vault: {target}")
        validate_vault_readonly(target)

    rkn.validate_test_vault = validate_apply_vault
    network_after = rkn.build_network(capture_dir, workflow_dir, vault)
    vault_result = rkn.write_vault_outputs(vault, network_after, args.network_title)
    result = {
        "schema": SCHEMA + ".apply",
        "created_at": utc_now(),
        "backup": backup,
        "import_capture_stdout": completed.stdout,
        "vault_result": vault_result,
        "pdfs_copied": 0,
        "zotero_touched": False,
    }
    write_json(out_dir / "apply_result.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and preview incremental Research Knowledge Network updates.")
    parser.add_argument("--capture-dir", required=True, help="New lit-search-cite capture directory.")
    parser.add_argument("--workflow-dir", default="", help="Optional workflow directory with zotero_link_map.json.")
    parser.add_argument("--vault", required=True, help="Current Obsidian vault to inventory. Read-only unless apply is explicitly allowed.")
    parser.add_argument("--current-runtime", default="", help="Existing research_knowledge_network runtime directory.")
    parser.add_argument("--out", default="", help="Output directory for incremental package.")
    parser.add_argument("--network-title", default="20260713_100712 Research Knowledge Network")
    parser.add_argument("--stage", choices=["inventory", "prepare", "preview", "verify", "apply"], default="preview")
    parser.add_argument("--allow-apply", action="store_true", help="Required with --stage apply to write the target vault.")
    parser.add_argument("--obsidian-importer", default="", help="Path to obsidian_vault_mcp.py for guarded apply.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stage == "apply":
        result = run_apply(args)
    else:
        result = run_readonly(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IncrementalError as exc:
        print(f"research-network-incremental error: {exc}", file=sys.stderr)
        raise SystemExit(2)
