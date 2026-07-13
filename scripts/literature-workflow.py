#!/usr/bin/env python3
"""Keyword-driven literature discovery -> capture -> Zotero queue -> Obsidian MVP.

This script intentionally stays as a thin orchestrator around existing tools:

1. discover candidates with multi-search.py, or read a prepared discovery JSON;
2. select a small DOI/URL list;
3. run web-capture.py to create the standard capture directory;
4. write a Zotero handoff queue JSON;
5. optionally call obsidian-vault-mcp import-capture for a test vault.

It never writes zotero.sqlite, never reads browser cookies, and never bypasses
publisher login, captcha, HTTP 403/429, or paywalls.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SCHEMA_VERSION = "lit-search-cite.workflow.v1"
ZOTERO_QUEUE_SCHEMA = "lit-search-cite.zotero-handoff-queue.v1"
DEFAULT_OUT = "references/workflows"
DEFAULT_CAPTURE_OUT = "references/captured"


class WorkflowError(RuntimeError):
    """Raised when an orchestration stage cannot continue safely."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalise_doi(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(".,;)]}，。；）】")


def doi_url(doi: Any) -> str:
    clean = normalise_doi(doi)
    return f"https://doi.org/{clean}" if clean else ""


def load_multi_search_module() -> Any:
    path = repo_root() / "scripts" / "multi-search.py"
    spec = importlib.util.spec_from_file_location("lit_search_cite_multi_search", path)
    if spec is None or spec.loader is None:
        raise WorkflowError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def active_sources(module: Any, domain: str, sources: str) -> list[str]:
    if sources:
        return [item.strip().lower() for item in sources.split(",") if item.strip()]
    defaults = getattr(module, "DEFAULT_SOURCES", {})
    return list(defaults.get(domain) or defaults.get("general") or ["openalex", "crossref"])


def discover_candidates(
    query: str,
    domain: str,
    sources: str = "",
    limit: int = 15,
    total: int = 30,
    year_from: int = 0,
    year_to: int = 0,
    online_rank: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run the existing multi-search source functions and return normalized candidates."""
    module = load_multi_search_module()
    selected_sources = active_sources(module, domain, sources)
    candidates: list[dict[str, Any]] = []
    for source in selected_sources:
        if source == "openalex":
            candidates.extend(module.search_openalex(query, limit, year_from, year_to))
        elif source == "crossref":
            candidates.extend(module.search_crossref(query, limit, year_from, year_to))
        elif source == "pubmed":
            candidates.extend(module.search_pubmed(query, limit, year_from, year_to))
        elif source == "arxiv":
            candidates.extend(module.search_arxiv(query, limit, domain, year_from, year_to))
    candidates = dedupe_candidates(candidates)
    candidates.sort(key=lambda item: (-(intish(item.get("citations"))), -(intish(item.get("year")))))
    output = candidates[:total]
    if online_rank:
        apply_multi_search_ranks(module, output)
    return output, selected_sources


def apply_multi_search_ranks(module: Any, candidates: list[dict[str, Any]]) -> None:
    """Reuse multi-search.py ranking helpers without making them part of the contract."""
    try:
        ranks_local = module.load_ranks_local()
    except Exception:
        ranks_local = {}
    for item in candidates:
        venue = str(item.get("venue") or "")
        try:
            tier = module.get_tier_offline(venue, ranks_local)
        except Exception:
            tier = ""
        if tier:
            item["journal_rank"] = tier


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_doi: dict[str, dict[str, Any]] = {}
    seen_title: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in candidates:
        doi = normalise_doi(item.get("doi"))
        if doi:
            old = seen_doi.get(doi.lower())
            if old:
                if intish(item.get("citations")) > intish(old.get("citations")):
                    idx = output.index(old)
                    output[idx] = item
                    seen_doi[doi.lower()] = item
                continue
            seen_doi[doi.lower()] = item
            output.append(item)
            continue
        title_key = normalize_for_match(item.get("title"))
        if title_key and title_key in seen_title:
            continue
        if title_key:
            seen_title.add(title_key)
        output.append(item)
    return output


def intish(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def normalize_for_match(value: Any) -> str:
    text = html.unescape(str(value or "")).lower()
    text = re.sub(r"</?(?:sub|sup)[^>]*>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-").replace("‑", "-").replace("鈥揅", "-")
    text = re.sub(r"\bc\s*\(\s*sp\s*3\s*\)\s*[- ]\s*c\s*\(\s*sp\s*3\s*\)", "c(sp3)-c(sp3)", text)
    text = re.sub(r"\bs\s*h\s*2\b", "sh2", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def split_priority_terms(values: list[str] | None) -> list[str]:
    terms: list[str] = []
    for value in values or []:
        for part in re.split(r"[,;]", value):
            term = part.strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def priority_hit(term: str, text: str) -> bool:
    needle = normalize_for_match(term)
    if not needle:
        return False
    if needle in text:
        return True
    if needle in {"sh2", "sh2 mechanism"}:
        return "sh2" in text
    if needle in {"nickel catalysis", "nickel catalyst"}:
        return "nickel" in text or "ni catalyzed" in text or "ni catalyst" in text
    if needle in {"radical", "radical mechanism", "radical cross coupling"}:
        return "radical" in text
    return False


def query_relevance_terms(query: str) -> list[tuple[str, str]]:
    query_key = normalize_for_match(query)
    terms: list[tuple[str, str]] = []
    if "c sp3 c sp3" in query_key:
        terms.append(("C(sp3)-C(sp3) bond/coupling", "c sp3 c sp3"))
    if "cross coupling" in query_key or "coupling" in query_key:
        terms.append(("coupling", "coupling"))
    if "asymmetric" in query_key or "enantio" in query_key:
        terms.append(("asymmetric or enantioselective", "enantio"))
    return terms


def text_has_relevance_term(text: str, needle: str) -> bool:
    if needle == "enantio":
        return any(term in text for term in ("enantio", "asymmetric", "stereoselective", "enantioselective", "enantioconvergent"))
    return needle in text


def candidate_relevance(
    candidate: dict[str, Any],
    priority_terms: list[str],
    query: str = "",
    current_year: int | None = None,
) -> tuple[float, list[str], list[str]]:
    current_year = current_year or dt.datetime.now().year
    text = normalize_for_match(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("title", "abstract", "venue", "source", "oa_url")
        )
    )
    score = 0.0
    reasons: list[str] = []
    if normalise_doi(candidate.get("doi")):
        score += 30
        reasons.append("has DOI")
    if candidate.get("oa_url"):
        score += 8
        reasons.append("has OA URL")
    score += min(intish(candidate.get("citations")), 500) / 20.0
    year = intish(candidate.get("year"))
    if year:
        score += max(0, 8 - max(0, current_year - year))
        if current_year - year <= 5:
            reasons.append("recent")
    priority_hits: list[str] = []
    for term in priority_terms:
        if priority_hit(term, text):
            score += 20
            priority_hits.append(term)
            reasons.append(f"priority term: {term}")
    for label, needle in query_relevance_terms(query):
        if text_has_relevance_term(text, needle):
            score += 18 if needle == "c sp3 c sp3" else 8
            reasons.append(f"query match: {label}")
    if "review" in text or "perspective" in text or "overview" in text or "paradigm shift" in text or "landscape" in text:
        score -= 12
        reasons.append("penalty: likely review or broad overview")
    if "carbon nitrogen" in text or " c n coupling" in text or "amination" in text:
        if "c sp3 c sp3" not in text:
            score -= 15
            reasons.append("penalty: C-N chemistry without C(sp3)-C(sp3) match")
    return round(score, 3), priority_hits, stable_unique(reasons)


def stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def select_candidates(candidates: list[dict[str, Any]], count: int, priority_terms: list[str], query: str = "") -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for item in candidates:
        copy = dict(item)
        copy["doi"] = normalise_doi(copy.get("doi"))
        score, priority_hits, reasons = candidate_relevance(copy, priority_terms, query)
        copy["workflow_score"] = score
        copy["workflow_priority_hits"] = priority_hits
        copy["workflow_relevance_reasons"] = reasons
        scored.append(copy)
    scored.sort(key=lambda item: (-(float(item.get("workflow_score") or 0)), -(intish(item.get("year"))), str(item.get("title") or "")))
    output: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in scored:
        title_key = normalize_for_match(item.get("title"))
        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)
        output.append(item)
        if len(output) >= count:
            break
    return output


def load_candidates_from_json(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, dict):
        data = data.get("items") or data.get("results") or data.get("candidates") or []
    if not isinstance(data, list):
        raise WorkflowError(f"Discovery JSON must contain a list: {path}")
    return [dict(item) for item in data if isinstance(item, dict)]


def selected_identifier_lines(selected: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in selected:
        if normalise_doi(item.get("doi")):
            lines.append(doi_url(item.get("doi")))
        elif item.get("oa_url"):
            lines.append(str(item["oa_url"]).strip())
        elif item.get("url"):
            lines.append(str(item["url"]).strip())
        elif item.get("title"):
            lines.append(str(item["title"]).strip())
    return lines


def parse_capture_output(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        match = re.match(r"\s*Output:\s*(.+?)\s*$", line)
        if match:
            return Path(match.group(1)).expanduser()
    return None


def run_web_capture(
    identifiers_path: Path,
    capture_out: Path,
    limit: int,
    pdf: str,
    profile: str = "",
    verbose: bool = False,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(repo_root() / "scripts" / "web-capture.py"),
        "--text",
        str(identifiers_path),
        "--out",
        str(capture_out),
        "--limit",
        str(limit),
        "--pdf",
        pdf,
    ]
    if profile:
        command.extend(["--profile", profile])
    if verbose:
        command.append("--verbose")
    proc = subprocess.run(command, cwd=str(repo_root()), capture_output=True, text=True, encoding="utf-8", errors="replace")
    capture_dir = parse_capture_output(proc.stdout or "")
    if capture_dir and not capture_dir.is_absolute():
        capture_dir = (repo_root() / capture_dir).resolve()
    result = {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "capture_dir": str(capture_dir) if capture_dir else "",
    }
    if proc.returncode != 0:
        raise WorkflowError(f"web-capture failed with exit code {proc.returncode}: {proc.stderr or proc.stdout}")
    if not capture_dir:
        raise WorkflowError("web-capture did not report an output directory.")
    return result


def captured_articles(capture_dir: Path) -> list[dict[str, Any]]:
    data = read_json(capture_dir / "captured.json")
    if isinstance(data, dict):
        data = data.get("items") or data.get("articles") or []
    if not isinstance(data, list):
        raise WorkflowError(f"captured.json must contain a list: {capture_dir}")
    return [dict(item) for item in data if isinstance(item, dict)]


def relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return str(path)


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"\s*[;,]\s*", text) if part.strip()]


def build_zotero_queue(
    *,
    query: str,
    workflow_dir: Path,
    capture_dir: Path | None,
    selected: list[dict[str, Any]],
    articles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_items = articles if articles is not None else selected
    items: list[dict[str, Any]] = []
    for index, item in enumerate(source_items, start=1):
        doi = normalise_doi(item.get("doi"))
        title = str(item.get("title") or "").strip()
        pdf_path = str(item.get("pdf_path") or "").strip()
        if pdf_path and capture_dir:
            pdf_path = relative_or_absolute(capture_dir / pdf_path, capture_dir)
        items.append({
            "id": f"doi:{doi}" if doi else f"title:{normalize_for_match(title)[:80] or index}",
            "status": "pending",
            "action": "upsert_metadata_and_attach_legal_pdf_if_available",
            "doi": doi,
            "doi_url": doi_url(doi),
            "title": title,
            "authors": listify(item.get("authors")),
            "year": item.get("year") or "",
            "journal": item.get("journal") or item.get("venue") or "",
            "url": item.get("url") or item.get("source_page") or item.get("oa_url") or doi_url(doi),
            "source": item.get("source") or item.get("metadata_source") or "",
            "capture_dir": str(capture_dir.resolve()) if capture_dir else "",
            "capture_json": "captured.json" if capture_dir else "",
            "bibtex_path": "captured.bib" if capture_dir else "",
            "ris_path": "captured.ris" if capture_dir else "",
            "pdf_status": item.get("pdf_status") or ("not_requested" if capture_dir else "capture_not_run"),
            "pdf_path": pdf_path,
            "pdf_url": item.get("pdf_url") or "",
            "oa_status": item.get("oa_status") or "",
            "license": item.get("license") or "",
            "notes": [
            "Queue only. Import must use Zotero API such as Zotero.Attachments.importFromFile().",
            "Never write zotero.sqlite directly.",
        ],
        })
    return {
        "schema": ZOTERO_QUEUE_SCHEMA,
        "contract_status": "intermediate_handoff_contract",
        "target_consumer": "Zotero Attachment Hub or a manual Zotero API importer; runtime plugin schema was not available in this workspace.",
        "created_at": utc_now(),
        "query": query,
        "workflow_dir": str(workflow_dir.resolve()),
        "capture_dir": str(capture_dir.resolve()) if capture_dir else "",
        "total_items": len(items),
        "safety": {
            "writes_zotero_sqlite": False,
            "reads_browser_cookies": False,
            "bypasses_paywalls": False,
            "downloads_only_legal_open_pdf": True,
            "requires_user_or_plugin_to_execute_queue": True,
        },
        "instructions": [
            "Import metadata through Zotero API or normal Zotero import UI.",
            "Attach local PDFs only when pdf_status is downloaded and the file exists.",
            "Use Zotero.Attachments.importFromFile() for attachment writes.",
            "Do not store passwords, cookies, tokens, or school login sessions in this queue.",
        ],
        "items": items,
    }


def write_candidates_markdown(
    path: Path,
    query: str,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    priority_terms: list[str],
) -> None:
    lines = [
        "# Literature Discovery Candidates",
        "",
        f"- Query: {query}",
        f"- Priority terms: {'; '.join(priority_terms)}",
        f"- Selected: {len(selected)}",
        f"- Candidates: {len(candidates)}",
        "",
        "## Selected",
        "",
    ]
    for index, item in enumerate(selected, start=1):
        lines.extend([
            f"### {index}. {item.get('title') or '(untitled)'}",
            "",
            f"- DOI: {item.get('doi') or ''}",
            f"- Year: {item.get('year') or ''}",
            f"- Venue: {item.get('venue') or item.get('journal') or ''}",
            f"- Source: {item.get('source') or ''}",
            f"- Citations: {item.get('citations') or 0}",
            f"- Workflow score: {item.get('workflow_score') or ''}",
            f"- Priority hits: {'; '.join(item.get('workflow_priority_hits') or [])}",
            f"- Relevance reasons: {'; '.join(item.get('workflow_relevance_reasons') or [])}",
            f"- OA URL: {item.get('oa_url') or ''}",
            "",
        ])
    write_text("\n".join(lines), path)


def write_workflow_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Literature Workflow Report",
        "",
        f"- Created at: {summary.get('created_at')}",
        f"- Query: {summary.get('query')}",
        f"- Domain: {summary.get('domain')}",
        f"- Year from: {summary.get('year_from') or ''}",
        f"- Year to: {summary.get('year_to') or ''}",
        f"- Sources: {'; '.join(summary.get('sources') or [])}",
        f"- Candidates discovered: {summary.get('candidates_total')}",
        f"- Candidates selected: {summary.get('selected_total')}",
        f"- Workflow directory: {summary.get('workflow_dir')}",
        f"- Capture directory: {summary.get('capture_dir') or 'not run'}",
        f"- Zotero queue: {summary.get('zotero_queue')}",
        f"- Obsidian import: {summary.get('obsidian_status') or 'not_requested'}",
        "",
        "## Zotero Queue Contract",
        "",
        "- `zotero_queue.json` is an intermediate handoff contract.",
        "- The Zotero Attachment Hub runtime schema was not available in this workspace.",
        "- A Zotero plugin or script should validate the queue before executing writes.",
        "",
        "## Safety",
        "",
        "- Zotero handoff is a JSON queue only.",
        "- This workflow does not write zotero.sqlite.",
        "- This workflow does not read browser cookies or saved credentials.",
        "- Publisher 403, 429, captcha, and login-required pages are not bypassed.",
        "- PDF downloads are delegated to web-capture.py --pdf legal only.",
    ]
    warnings = summary.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    write_text("\n".join(lines) + "\n", path)


def default_obsidian_command(obsidian_command: str = "") -> list[str]:
    if obsidian_command:
        if obsidian_command.lower().endswith(".py"):
            return [sys.executable, obsidian_command]
        return [obsidian_command]
    sibling = repo_root().parent / "obsidian-vault-mcp" / "scripts" / "obsidian_vault_mcp.py"
    if sibling.exists():
        return [sys.executable, str(sibling)]
    return ["obsidian-vault-mcp"]


def run_obsidian_import(
    capture_dir: Path,
    vault: Path,
    obsidian_command: str = "",
    copy_pdfs: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    command = default_obsidian_command(obsidian_command)
    command.extend(["import-capture", "--capture-dir", str(capture_dir), "--vault", str(vault)])
    if not copy_pdfs:
        command.append("--no-copy-pdfs")
    if overwrite:
        command.append("--overwrite")
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "ok": proc.returncode == 0,
    }


def effective_year_from(args: argparse.Namespace) -> int:
    if args.year_from:
        return args.year_from
    if args.all_years:
        return 0
    if args.recent_years > 0:
        return dt.datetime.now().year - args.recent_years + 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run keyword-driven discovery, standard capture, Zotero queue handoff, and optional Obsidian import."
    )
    parser.add_argument("--query", "-q", required=True, help="Keyword query for discovery and reporting.")
    parser.add_argument("--domain", "-d", default="chemistry", help="multi-search domain, e.g. chemistry, biomedicine, general.")
    parser.add_argument("--sources", default="", help="Comma-separated search sources. Defaults to multi-search domain routing.")
    parser.add_argument("--search-results", default="", help="Existing discovery JSON. When set, live discovery is skipped.")
    parser.add_argument("--capture-dir", default="", help="Existing web-capture output directory. When set, web-capture is skipped.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Workflow output root.")
    parser.add_argument("--capture-out", default=DEFAULT_CAPTURE_OUT, help="web-capture output root.")
    parser.add_argument("--discover-limit", type=int, default=15, help="Per-source discovery limit.")
    parser.add_argument("--total", type=int, default=30, help="Total discovered candidates to keep before selection.")
    parser.add_argument("--select", type=int, default=10, help="Number of candidates to capture and queue.")
    parser.add_argument("--recent-years", type=int, default=5, help="Default year window when --year-from is omitted.")
    parser.add_argument("--all-years", action="store_true", help="Disable the default recent-years filter.")
    parser.add_argument("--year-from", type=int, default=0)
    parser.add_argument("--year-to", type=int, default=0)
    parser.add_argument("--priority", action="append", default=[], help="Priority term. May be repeated or comma-separated.")
    parser.add_argument("--online-rank", action="store_true", help="Reuse multi-search online ranking when configured.")
    parser.add_argument("--pdf", choices=["none", "legal"], default="legal", help="PDF mode passed to web-capture.")
    parser.add_argument("--profile", default="", help="Optional safe retrieval profile passed to web-capture.")
    parser.add_argument("--skip-capture", action="store_true", help="Write discovery and queue only; do not call web-capture.")
    parser.add_argument("--zotero-queue-path", default="", help="Optional extra queue.json destination. Not used by default.")
    parser.add_argument("--import-obsidian", action="store_true", help="Call obsidian-vault-mcp import-capture after capture.")
    parser.add_argument("--vault", default="", help="Obsidian vault path for --import-obsidian.")
    parser.add_argument("--obsidian-command", default="", help="Optional obsidian-vault-mcp command or script path.")
    parser.add_argument("--copy-pdfs", action="store_true", help="Allow obsidian-vault-mcp to copy PDFs. Default is --no-copy-pdfs.")
    parser.add_argument("--overwrite", action="store_true", help="Pass --overwrite to obsidian-vault-mcp import-capture.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workflow_dir = (Path(args.out) / now_stamp()).resolve()
    workflow_dir.mkdir(parents=True, exist_ok=True)
    priority_terms = split_priority_terms(args.priority)
    year_from = effective_year_from(args)
    warnings: list[str] = []

    if args.search_results:
        candidates = load_candidates_from_json(Path(args.search_results))
        sources = ["provided-json"]
    else:
        candidates, sources = discover_candidates(
            args.query,
            args.domain,
            args.sources,
            limit=args.discover_limit,
            total=args.total,
            year_from=year_from,
            year_to=args.year_to,
            online_rank=args.online_rank,
        )
    selected = select_candidates(candidates, args.select, priority_terms, args.query)
    identifiers = selected_identifier_lines(selected)

    write_json(
        {
            "schema": SCHEMA_VERSION,
            "created_at": utc_now(),
            "query": args.query,
            "domain": args.domain,
            "sources": sources,
            "year_from": year_from,
            "year_to": args.year_to,
            "priority_terms": priority_terms,
            "candidates": candidates,
            "selected": selected,
        },
        workflow_dir / "discovery.json",
    )
    write_candidates_markdown(workflow_dir / "candidates.md", args.query, selected, candidates, priority_terms)
    write_text("\n".join(identifiers) + ("\n" if identifiers else ""), workflow_dir / "selected_identifiers.txt")

    capture_dir: Path | None = Path(args.capture_dir).expanduser().resolve() if args.capture_dir else None
    if args.skip_capture:
        warnings.append("web-capture was skipped by --skip-capture.")
    elif capture_dir is None:
        if not identifiers:
            raise WorkflowError("No selected DOI/URL/title identifiers are available for web-capture.")
        capture_result = run_web_capture(
            workflow_dir / "selected_identifiers.txt",
            Path(args.capture_out),
            limit=args.select,
            pdf=args.pdf,
            profile=args.profile,
            verbose=args.verbose,
        )
        capture_dir = Path(capture_result["capture_dir"]).resolve()
        write_json(capture_result, workflow_dir / "web_capture_result.json")

    articles: list[dict[str, Any]] | None = None
    if capture_dir is not None and (capture_dir / "captured.json").exists():
        articles = captured_articles(capture_dir)
    elif capture_dir is not None:
        warnings.append(f"capture_dir does not contain captured.json: {capture_dir}")

    queue = build_zotero_queue(
        query=args.query,
        workflow_dir=workflow_dir,
        capture_dir=capture_dir,
        selected=selected,
        articles=articles,
    )
    queue_path = workflow_dir / "zotero_queue.json"
    write_json(queue, queue_path)
    if capture_dir is not None and capture_dir.exists():
        write_json(queue, capture_dir / "zotero_queue.json")
    if args.zotero_queue_path:
        write_json(queue, Path(args.zotero_queue_path))

    obsidian_status = "not_requested"
    if args.import_obsidian:
        if capture_dir is None:
            raise WorkflowError("--import-obsidian requires a capture directory.")
        if not args.vault:
            raise WorkflowError("--import-obsidian requires --vault.")
        obsidian_result = run_obsidian_import(
            capture_dir,
            Path(args.vault).expanduser().resolve(),
            obsidian_command=args.obsidian_command,
            copy_pdfs=args.copy_pdfs,
            overwrite=args.overwrite,
        )
        obsidian_status = "ok" if obsidian_result.get("ok") else "failed"
        write_json(obsidian_result, workflow_dir / "obsidian_import_result.json")
        if not obsidian_result.get("ok"):
            warnings.append("Obsidian import failed; see obsidian_import_result.json.")

    summary = {
        "schema": SCHEMA_VERSION,
        "created_at": utc_now(),
        "query": args.query,
        "domain": args.domain,
        "sources": sources,
        "year_from": year_from,
        "year_to": args.year_to,
        "candidates_total": len(candidates),
        "selected_total": len(selected),
        "workflow_dir": str(workflow_dir),
        "capture_dir": str(capture_dir) if capture_dir else "",
        "zotero_queue": str(queue_path),
        "zotero_queue_items": queue["total_items"],
        "obsidian_status": obsidian_status,
        "warnings": warnings,
    }
    write_json(summary, workflow_dir / "workflow_summary.json")
    write_workflow_report(workflow_dir / "workflow_report.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if obsidian_status == "failed" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkflowError as exc:
        print(f"literature-workflow error: {exc}", file=sys.stderr)
        raise SystemExit(2)
