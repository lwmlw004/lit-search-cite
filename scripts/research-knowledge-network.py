#!/usr/bin/env python3
"""Build a local research knowledge network from lit-search-cite captures.

This script is intentionally offline. It reads existing capture metadata and
optional Zotero link maps, then writes deterministic analysis JSON and
Obsidian test-vault notes. It does not access Zotero, network resources, PDFs,
browser cookies, or formal vaults.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import textwrap
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any


if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


MANAGED_START = "<!-- codex-research-analysis:start -->"
MANAGED_END = "<!-- codex-research-analysis:end -->"
NODE_START = "<!-- codex-research-network:start -->"
NODE_END = "<!-- codex-research-network:end -->"
NETWORK_SCHEMA = "lit-search-cite.research-knowledge-network.v1"


class NetworkError(RuntimeError):
    """Raised when the workflow cannot proceed safely."""


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


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(".,;)]}").lower()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = text.replace("\u2212", "-").replace("\u2010", "-").replace("\u2011", "-")
    text = text.replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("鈥", "").replace("�", "")
    text = re.sub(r"C\(sp\s*3\s*\)", "C(sp3)", text, flags=re.IGNORECASE)
    text = re.sub(r"C\s*sp\s*3", "C(sp3)", text, flags=re.IGNORECASE)
    text = re.sub(r"S\s*H\s*2", "SH2", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = normalize_text(value)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def normalized_title_key(value: Any) -> str:
    text = normalize_text(value).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def safe_filename(value: str, max_len: int = 120) -> str:
    text = normalize_text(value)
    text = re.sub(r'[<>:"/\\|?*]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:max_len].rstrip(" .") or "untitled") + ".md"


def safe_note_title(value: str) -> str:
    return safe_filename(value)[:-3]


def yaml_quote(value: Any) -> str:
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def frontmatter(title: str, kind: str, tags: list[str]) -> str:
    lines = ["---", f"title: {yaml_quote(title)}", f"type: {yaml_quote(kind)}", "tags:"]
    lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(["---", ""])
    return "\n".join(lines)


TERM_RULES: list[dict[str, Any]] = [
    {"name": "SH2 mechanism", "category": "mechanism", "patterns": [r"\bSH2\b", r"homolytic substitution"]},
    {"name": "homolytic substitution", "category": "mechanism", "patterns": [r"homolytic substitution"]},
    {"name": "reductive elimination", "category": "mechanism", "patterns": [r"reductive elimination"]},
    {"name": "radical recombination", "category": "mechanism", "patterns": [r"radical recombination", r"\brecombination\b"]},
    {"name": "radical cross-coupling", "category": "mechanism", "patterns": [r"radical .*cross-coupling", r"cross-coupling .*radical"]},
    {"name": "radical capture", "category": "mechanism", "patterns": [r"trap organic radicals", r"radical trap", r"radical capture"]},
    {"name": "single electron transfer", "category": "mechanism", "patterns": [r"single[- ]electron", r"\bSET\b"]},
    {"name": "oxidative addition", "category": "mechanism", "patterns": [r"oxidative addition"]},
    {"name": "decarbonylation", "category": "mechanism", "patterns": [r"decarbonylation", r"decarbonylative"]},
    {"name": "decarboxylation", "category": "mechanism", "patterns": [r"decarboxylation", r"decarboxylative"]},
    {"name": "photoelectrochemistry", "category": "method", "patterns": [r"photoelectro", r"photo-electro"]},
    {"name": "photoredox catalysis", "category": "method", "patterns": [r"photoredox", r"photocatalysis"]},
    {"name": "electrochemistry", "category": "method", "patterns": [r"electrochem", r"electrode", r"electrocatal"]},
    {"name": "C(sp3)-C(sp3) cross-coupling", "category": "method", "patterns": [r"C\(sp3\)\s*[- ]\s*C\(sp3\)", r"Csp ?3.*Csp ?3"]},
    {"name": "cross-coupling", "category": "method", "patterns": [r"\bcross-coupling\b", r"coupling reaction"]},
    {"name": "nickel catalyst", "category": "catalyst", "patterns": [r"\bnickel\b", r"\bNi/photoredox\b", r"\bNi-catal"]},
    {"name": "chiral nickel catalyst", "category": "catalyst", "patterns": [r"enantioselective.*nickel", r"chiral.*nickel", r"pyridine-oxazoline"]},
    {"name": "palladium catalyst", "category": "catalyst", "patterns": [r"\bpalladium\b", r"\bPd\b"]},
    {"name": "bismuth radical", "category": "catalyst", "patterns": [r"\bbismuth\b", r"bismuth\(II\) radical"]},
    {"name": "alkyl radical", "category": "chemical", "patterns": [r"alkyl radical"]},
    {"name": "alkylnickel intermediate", "category": "chemical", "patterns": [r"alkylnickel", r"organonickel"]},
    {"name": "carboxylic acid", "category": "reactant", "patterns": [r"carboxylic acid"]},
    {"name": "carboxylic acid ester", "category": "reactant", "patterns": [r"carboxylic acid ester"]},
    {"name": "alkyl halide", "category": "reactant", "patterns": [r"alkyl halide", r"alkyl iodide"]},
    {"name": "aziridine", "category": "reactant", "patterns": [r"aziridine"]},
    {"name": "acetal", "category": "reactant", "patterns": [r"acetal"]},
    {"name": "alkene", "category": "reactant", "patterns": [r"\balkene\b"]},
    {"name": "radical flux", "category": "concept", "patterns": [r"radical concentration", r"radical flux", r"radical generation rate", r"current density"]},
    {"name": "stereocontrol", "category": "concept", "patterns": [r"enantioselective", r"stereochemistry", r"stereocontrol", r"\bee\b"]},
    {"name": "electrode-catalyst decoupling", "category": "concept", "patterns": [r"electrode.*oxidation state", r"heterogeneous electrode", r"photoredox catalyst or.*electrode"]},
    {"name": "N-alpha carbon radical", "category": "concept", "patterns": [r"N.?alpha", r"N-alpha", r"alpha-amino", r"\u03b1-amino"]},
]

EVIDENCE_RULES: list[dict[str, Any]] = [
    {"name": "DFT", "patterns": [r"\bDFT\b", r"density functional"]},
    {"name": "cyclic voltammetry", "patterns": [r"\bCV\b", r"cyclic voltam"]},
    {"name": "radical clock", "patterns": [r"radical clock"]},
    {
        "name": "stoichiometric intermediate",
        "patterns": [
            r"stoichiometric.{0,80}intermediate",
            r"intermediate.{0,80}stoichiometric",
            r"isolat(?:ed|ion).{0,80}intermediate",
            r"intermediate.{0,80}isolat(?:ed|ion)",
            r"trapp(?:ed|ing).{0,80}intermediate",
            r"intermediate.{0,80}trapp(?:ed|ing)",
            r"characteri[sz](?:ed|ation).{0,80}intermediate",
            r"intermediate.{0,80}(?:NMR|crystal|X-ray|EPR)",
        ],
    },
    {"name": "control experiment", "patterns": [r"control experiment"]},
    {"name": "sequential addition", "patterns": [r"sequential addition", r"order of addition"]},
    {"name": "Stern-Volmer", "patterns": [r"Stern[- ]Volmer"]},
    {"name": "EPR", "patterns": [r"\bEPR\b"]},
]


def source_fields(article: dict[str, Any]) -> dict[str, str]:
    return {
        "title": normalize_text(article.get("title")),
        "abstract": normalize_text(article.get("abstract")),
        "keywords": normalize_text("; ".join(article.get("keywords") or [])),
        "concepts": normalize_text("; ".join(article.get("concepts") or [])),
    }


def first_evidence(fields: dict[str, str], patterns: list[str]) -> dict[str, str]:
    for source, text in fields.items():
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                start = max(0, match.start() - 90)
                end = min(len(text), match.end() + 140)
                return {
                    "source_field": source,
                    "excerpt": text[start:end].strip(),
                }
    return {"source_field": "", "excerpt": ""}


def detect_terms(article: dict[str, Any]) -> list[dict[str, Any]]:
    fields = source_fields(article)
    detected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in TERM_RULES:
        evidence = first_evidence(fields, rule["patterns"])
        if evidence["source_field"] and rule["name"].lower() not in seen:
            seen.add(rule["name"].lower())
            detected.append({
                "name": rule["name"],
                "category": rule["category"],
                "evidence": evidence,
            })
    return detected


def detect_evidence_methods(article: dict[str, Any]) -> list[dict[str, Any]]:
    fields = source_fields(article)
    out: list[dict[str, Any]] = []
    for rule in EVIDENCE_RULES:
        evidence = first_evidence(fields, rule["patterns"])
        if evidence["source_field"]:
            out.append({"name": rule["name"], "evidence": evidence})
    return out


def derive_project_relevance_terms(article: dict[str, Any], source_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create explicitly labeled project connectors without claiming source facts."""
    names = {term["name"] for term in source_terms}
    text = " ".join(source_fields(article).values()).lower()
    candidates: list[tuple[str, str, str]] = []
    if names & {"radical cross-coupling", "photoredox catalysis", "decarboxylation", "alkyl radical", "single electron transfer"}:
        candidates.append((
            "radical flux",
            "concept",
            "project connector inferred from local radical/redox context; not a direct flux measurement claim",
        ))
    if {"electrochemistry", "nickel catalyst"} <= names or ("electrode" in text and "nickel" in text):
        candidates.append((
            "electrode-catalyst decoupling",
            "concept",
            "project connector for separating electrode redox activation from nickel catalysis",
        ))
    if names & {"SH2 mechanism", "homolytic substitution", "reductive elimination"}:
        candidates.append((
            "SH2 vs reductive elimination",
            "concept",
            "project connector for distinguishing stereodefining mechanism hypotheses",
        ))
    if names & {"stereocontrol", "chiral nickel catalyst"}:
        candidates.append((
            "enantioselective radical capture",
            "concept",
            "project connector for asymmetric radical capture and stereocontrol",
        ))
    if "nhpi" in text or "carboxylic acid ester" in names or "carboxylic acid" in names:
        candidates.append((
            "NHPI ester SET axis",
            "concept",
            "project connector for redox-active ester radical generation hypotheses",
        ))

    out: list[dict[str, Any]] = []
    seen = {term["name"].lower() for term in source_terms}
    for name, category, reason in candidates:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name,
            "category": category,
            "evidence": {
                "source_field": "project_relevance",
                "excerpt": reason,
            },
        })
    return out


def classify_corpus_role(article: dict[str, Any], source_terms: list[dict[str, Any]]) -> str:
    title = normalize_text(article.get("title")).lower()
    doi = normalize_doi(article.get("doi"))
    journal = normalize_text(article.get("journal") or article.get("container_title")).lower()
    term_names = {term["name"].lower() for term in source_terms}
    if "chemrxiv" in doi or "chemrxiv" in journal:
        return "preprint_version"
    if "review" in title or "paradigm shift" in title:
        return "review_context"
    if "palladium catalyst" in term_names or "bismuth radical" in term_names:
        return "contrast_control"
    if "c-n" in title or "carbon-nitrogen" in title or "amination" in title:
        return "adjacent_method"
    if "chiral nickel catalyst" in term_names or "stereocontrol" in term_names:
        return "core_asymmetric_ni_relevance"
    if {"nickel catalyst", "c(sp3)-c(sp3) cross-coupling"} <= term_names:
        return "core_ni_csp3_csp3_context"
    if "c(sp3)-c(sp3) cross-coupling" in term_names or "radical cross-coupling" in term_names:
        return "near_core_radical_coupling"
    return "background_context"


def wikilink(value: str) -> str:
    return f"[[{value}]]"


def article_key(article: dict[str, Any]) -> str:
    doi = normalize_doi(article.get("doi"))
    return doi or normalize_text(article.get("title")).lower()


def note_title_from_path(path: Path | None, article: dict[str, Any]) -> str:
    if path:
        return path.stem
    year = str(article.get("year") or "n.d.")
    first_author = "Unknown"
    authors = article.get("authors") or []
    if authors:
        first = authors[0]
        first_author = str(first.get("lastName") or first.get("family") or first.get("name") or first).split()[-1]
    return f"{first_author} {year} - {normalize_text(article.get('title'))[:60]}"


def analysis_for_article(article: dict[str, Any], note_path: Path | None) -> dict[str, Any]:
    terms = detect_terms(article)
    project_terms = derive_project_relevance_terms(article, terms)
    evidence_methods = detect_evidence_methods(article)
    by_category: dict[str, list[str]] = defaultdict(list)
    for term in terms:
        by_category[term["category"]].append(term["name"])
    project_by_category: dict[str, list[str]] = defaultdict(list)
    for term in project_terms:
        project_by_category[term["category"]].append(term["name"])
    abstract = normalize_text(article.get("abstract"))
    limitations: list[str] = []
    if not abstract:
        limitations.append("No abstract in local capture; analysis is limited to title/metadata.")
    if not evidence_methods:
        limitations.append("No explicit DFT/CV/radical-clock/stoichiometric evidence method was detected in local capture text.")
    if "stereocontrol" not in [term["name"] for term in terms]:
        limitations.append("No direct ee/stereocontrol evidence was detected in local capture text.")
    relevance_parts = []
    if by_category.get("mechanism"):
        relevance_parts.append("mechanistic radical or organometallic clue")
    if by_category.get("method"):
        relevance_parts.append("C(sp3) coupling or redox method")
    if by_category.get("catalyst"):
        relevance_parts.append("metal or catalyst context")
    if project_terms:
        relevance_parts.append("project-hypothesis connector")
    if not relevance_parts:
        relevance_parts.append("background context only")
    title = normalize_text(article.get("title"))
    return {
        "doi": normalize_doi(article.get("doi")),
        "title": title,
        "year": article.get("year") or "",
        "journal": article.get("journal") or article.get("container_title") or "",
        "note_title": note_title_from_path(note_path, article),
        "note_path": str(note_path) if note_path else "",
        "zotero_key": article.get("zotero_key") or article.get("zoteroKey") or "",
        "zotero_attachment_keys": article.get("zotero_attachment_keys") or [],
        "terms": terms,
        "source_terms": terms,
        "project_relevance_terms": project_terms,
        "terms_by_category": {key: compact_list(value) for key, value in sorted(by_category.items())},
        "project_terms_by_category": {key: compact_list(value) for key, value in sorted(project_by_category.items())},
        "evidence_methods": evidence_methods,
        "mechanistic_summary": build_article_summary(by_category, article),
        "relevance_to_project": "; ".join(relevance_parts),
        "corpus_role": classify_corpus_role(article, terms),
        "version_group_key": normalized_title_key(title),
        "limitations": limitations,
    }


def build_article_summary(by_category: dict[str, list[str]], article: dict[str, Any]) -> str:
    title = normalize_text(article.get("title")).lower()
    terms = {term.lower() for values in by_category.values() for term in values}
    if "sh2 mechanism" in terms or "homolytic substitution" in terms:
        return "Local capture directly flags SH2/homolytic substitution as a mechanistic motif."
    if "alkylnickel intermediate" in terms:
        return "Local capture supports organonickel/alkylnickel intermediate formation as a mechanistic anchor."
    if "radical recombination" in terms:
        return "Local capture supports radical recombination or radical-pair control as the main mechanistic clue."
    if "photoredox catalysis" in terms and "nickel catalyst" in terms:
        return "Local capture supports metallaphotoredox radical generation coupled to nickel catalysis."
    if "electrochemistry" in terms or "photoelectrochemistry" in terms:
        return "Local capture supports electro/photo-mediated redox control as a method context."
    if "review" in title or "paradigm shift" in title:
        return "Local capture is best treated as review/background context rather than a primary mechanistic result."
    return "Local capture provides contextual chemistry terms, but mechanism remains underdetermined from metadata alone."


def build_relations(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for left, right in combinations(analyses, 2):
        if left.get("version_group_key") and left.get("version_group_key") == right.get("version_group_key"):
            relations.append({
                "source": left["doi"],
                "target": right["doi"],
                "type": "version_pair",
                "shared_terms": [],
                "version_note": "same normalized title; treat as article/preprint version pair rather than independent evidence",
                "confidence": "high",
            })
        left_terms = {term["name"] for term in left["terms"]}
        right_terms = {term["name"] for term in right["terms"]}
        shared = sorted(left_terms & right_terms)
        if len(shared) >= 2:
            relations.append({
                "source": left["doi"],
                "target": right["doi"],
                "type": "shared_mechanistic_or_method_terms",
                "shared_terms": shared,
                "confidence": "medium",
            })
        if "SH2 mechanism" in left_terms and "reductive elimination" in right_terms:
            relations.append(relation_contrast(left, right, "SH2 mechanism", "reductive elimination"))
        if "SH2 mechanism" in right_terms and "reductive elimination" in left_terms:
            relations.append(relation_contrast(right, left, "SH2 mechanism", "reductive elimination"))
        if "nickel catalyst" in left_terms and "palladium catalyst" in right_terms:
            relations.append(relation_contrast(left, right, "nickel catalyst", "palladium catalyst"))
        if "nickel catalyst" in right_terms and "palladium catalyst" in left_terms:
            relations.append(relation_contrast(right, left, "nickel catalyst", "palladium catalyst"))
    return relations


def relation_contrast(left: dict[str, Any], right: dict[str, Any], left_term: str, right_term: str) -> dict[str, Any]:
    return {
        "source": left["doi"],
        "target": right["doi"],
        "type": "contrast_for_hypothesis_testing",
        "shared_terms": [],
        "contrast": f"{left_term} vs {right_term}",
        "confidence": "low",
    }


def articles_for_term(analyses: list[dict[str, Any]], term: str) -> list[dict[str, str]]:
    out = []
    for analysis in analyses:
        names = {item["name"].lower() for item in analysis["terms"]}
        names.update(item["name"].lower() for item in analysis.get("project_relevance_terms", []))
        names.update(item["name"].lower() for item in analysis.get("evidence_methods", []))
        if term.lower() in names:
            out.append({"doi": analysis["doi"], "note_title": analysis["note_title"]})
    return out


def build_research_questions(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    templates = [
        {
            "id": "RQ1",
            "title": "Which radical binds Ni(I) first in asymmetric C(sp3)-C(sp3) coupling?",
            "concepts": ["nickel catalyst", "alkyl radical", "alkylnickel intermediate", "radical flux"],
            "why": "The batch contains organonickel formation, radical precursor, and metallaphotoredox examples, but local captures do not establish radical binding order.",
        },
        {
            "id": "RQ2",
            "title": "Can SH2 homolytic substitution be distinguished from reductive elimination in the stereodefining step?",
            "concepts": ["SH2 mechanism", "homolytic substitution", "reductive elimination", "stereocontrol"],
            "why": "SH2 is directly represented, while reductive elimination is a competing hypothesis that requires targeted evidence rather than assumption.",
        },
        {
            "id": "RQ3",
            "title": "How does radical flux affect ee and cross-selectivity?",
            "concepts": ["radical flux", "stereocontrol", "photoredox catalysis", "electrochemistry"],
            "why": "The user hypothesis emphasizes flux; local captures provide redox method context but not a direct flux-ee law.",
        },
        {
            "id": "RQ4",
            "title": "Can electrode-driven radical generation be decoupled from chiral nickel capture?",
            "concepts": ["electrode-catalyst decoupling", "electrochemistry", "nickel catalyst", "chiral nickel catalyst"],
            "why": "Electro/photo-mediated nickel literature frames redox-state control, but this batch should be treated as context unless a specific experiment tests decoupling.",
        },
        {
            "id": "RQ5",
            "title": "Does NHPI ester single-electron reduction create a radical concentration regime that favors side reactions?",
            "concepts": ["single electron transfer", "carboxylic acid ester", "radical flux", "cross-coupling"],
            "why": "NHPI is part of the project hypothesis, but direct NHPI evidence is weak in this local batch, so this remains a proposed test axis.",
        },
        {
            "id": "RQ6",
            "title": "Which evidence package can separate productive radical capture from self-coupling?",
            "concepts": ["radical capture", "radical recombination", "cross-coupling", "alkyl radical"],
            "why": "Several papers involve radical coupling or recombination, but metadata alone does not quantify productive versus side pathways.",
        },
    ]
    questions = []
    for template in templates:
        evidence = []
        for concept in template["concepts"]:
            evidence.extend(articles_for_term(analyses, concept))
        seen: set[str] = set()
        unique = []
        for item in evidence:
            if item["doi"] and item["doi"] not in seen:
                seen.add(item["doi"])
                unique.append(item)
        questions.append({**template, "evidence_articles": unique[:6], "status": "research_question_not_literature_conclusion"})
    return questions


def build_experiments(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        ("EX1", "Radical clock panel under matched current/light input", "RQ2", ["radical clock", "SH2 mechanism"], "Compare rearranged versus direct products while varying radical generation rate; this tests pathway timing without claiming a known rate law."),
        ("EX2", "Stoichiometric Ni intermediate trapping and sequential radical addition", "RQ1", ["stoichiometric intermediate", "nickel catalyst"], "Generate or observe candidate Ni intermediates before introducing the second radical precursor; readout is product formation versus off-cycle decay."),
        ("EX3", "CV-guided redox-window map for NHPI ester and Ni catalyst", "RQ5", ["cyclic voltammetry", "single electron transfer"], "Measure whether the radical precursor and nickel complex can be activated in separable potential windows."),
        ("EX4", "AC/DC/electrode-area radical flux matrix", "RQ3", ["electrochemistry", "radical flux"], "Vary current mode, electrode area, and light/electrode timing while tracking conversion, side products, and ee."),
        ("EX5", "Cross-over and self-coupling competition assay", "RQ6", ["radical recombination", "cross-coupling"], "Use two distinguishable radical precursors to quantify cross-product versus self-coupled products."),
        ("EX6", "Chiral ligand perturbation against SH2-sensitive substrate set", "RQ2", ["stereocontrol", "SH2 mechanism"], "Compare ligand-dependent ee and product ratios for substrates expected to alter SH2 versus reductive-elimination sensitivity."),
    ]
    by_id = {question["id"]: question for question in questions}
    experiments = []
    for exp_id, title, rq_id, concepts, rationale in specs:
        question = by_id.get(rq_id, {})
        experiments.append({
            "id": exp_id,
            "title": title,
            "research_question_id": rq_id,
            "concepts": concepts,
            "rationale": rationale,
            "expected_readouts": ["conversion", "cross/self product ratio", "ee where applicable", "radical-trap or intermediate signature"],
            "controls": [
                "no-light or no-current control as applicable",
                "no-metal or no-ligand control as applicable",
                "matched substrate concentration and reaction time",
                "blank radical precursor control where chemically meaningful",
            ],
            "risk_failure_criteria": [
                "Product ratio changes without a matching radical or intermediate readout should not be overinterpreted.",
                "A null ee trend does not exclude SH2 unless substrate conversion and side-product balance are comparable.",
                "Metadata-derived rationale must be checked against full text before lab execution.",
            ],
            "evidence_articles": question.get("evidence_articles", [])[:4],
            "safety_note": "Proposed experiment; no yield, ee, page, or energy barrier is inferred from local metadata.",
        })
    return experiments


def build_nodes(analyses: list[dict[str, Any]], questions: list[dict[str, Any]], experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_map: dict[tuple[str, str], dict[str, Any]] = {}
    term_categories: dict[str, str] = {}
    for analysis in analyses:
        for term in analysis["terms"]:
            term_categories.setdefault(term["name"].lower(), term["category"])
            key = (term["category"], term["name"].lower())
            node = node_map.setdefault(key, {
                "name": term["name"],
                "category": term["category"],
                "articles": [],
                "questions": [],
                "experiments": [],
            })
            node["articles"].append({"doi": analysis["doi"], "note_title": analysis["note_title"], "evidence": term["evidence"]})
        for term in analysis.get("project_relevance_terms", []):
            term_categories.setdefault(term["name"].lower(), term["category"])
            key = (term["category"], term["name"].lower())
            node = node_map.setdefault(key, {
                "name": term["name"],
                "category": term["category"],
                "articles": [],
                "questions": [],
                "experiments": [],
            })
            node["articles"].append({
                "doi": analysis["doi"],
                "note_title": analysis["note_title"],
                "evidence": term["evidence"],
                "source_type": "project_relevance",
            })
        for method in analysis.get("evidence_methods", []):
            term_categories.setdefault(method["name"].lower(), "concept")
            key = ("concept", method["name"].lower())
            node = node_map.setdefault(key, {
                "name": method["name"],
                "category": "concept",
                "articles": [],
                "questions": [],
                "experiments": [],
            })
            node["articles"].append({
                "doi": analysis["doi"],
                "note_title": analysis["note_title"],
                "evidence": method["evidence"],
                "source_type": "evidence_method",
            })
    for question in questions:
        for concept in question["concepts"]:
            category = term_categories.get(concept.lower(), "concept")
            key = (category, concept.lower())
            node = node_map.setdefault(key, {"name": concept, "category": category, "articles": [], "questions": [], "experiments": []})
            node["questions"].append(question["id"])
    for experiment in experiments:
        for concept in experiment["concepts"]:
            category = term_categories.get(concept.lower(), "concept")
            key = (category, concept.lower())
            node = node_map.setdefault(key, {"name": concept, "category": category, "articles": [], "questions": [], "experiments": []})
            node["experiments"].append(experiment["id"])
    return sorted(node_map.values(), key=lambda item: (item["category"], item["name"].lower()))


def load_capture(capture_dir: Path) -> list[dict[str, Any]]:
    data = read_json(capture_dir / "captured.json")
    if isinstance(data, dict):
        articles = data.get("items") or data.get("articles") or []
    else:
        articles = data
    if not isinstance(articles, list):
        raise NetworkError("captured.json must be a list or object with items/articles.")
    return [dict(item) for item in articles if isinstance(item, dict)]


def load_link_map(workflow_dir: Path | None, capture_dir: Path) -> dict[str, dict[str, Any]]:
    candidates = []
    if workflow_dir:
        candidates.append(workflow_dir / "zotero_link_map.json")
    candidates.append(capture_dir / "zotero_link_map.json")
    for path in candidates:
        if path.exists():
            data = read_json(path)
            return {normalize_doi(item.get("doi")): item for item in data.get("items", []) if isinstance(item, dict)}
    return {}


def merge_zotero_links(articles: list[dict[str, Any]], link_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    for article in articles:
        item = dict(article)
        mapped = link_map.get(normalize_doi(item.get("doi")))
        if mapped:
            for key in (
                "zotero_item_key", "zotero_item_uri", "zotero_key", "zotero_select", "zotero_uri",
                "zotero_attachment_keys", "zotero_attachment_uris", "zotero_attachment_key", "zotero_attachment_uri",
                "zotero_link_status", "zotero_link_verified_at",
            ):
                if mapped.get(key) not in ("", None, []):
                    item[key] = mapped[key]
        merged.append(item)
    return merged


def find_literature_notes(vault: Path, articles: list[dict[str, Any]]) -> dict[str, Path]:
    notes_dir = vault / "literature"
    matches: dict[str, Path] = {}
    if not notes_dir.exists():
        return matches
    md_files = list(notes_dir.glob("*.md"))
    for article in articles:
        doi = normalize_doi(article.get("doi"))
        if not doi:
            continue
        found = []
        needle = doi.lower()
        for path in md_files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            if needle in text:
                found.append(path)
        if len(found) == 1:
            matches[doi] = found[0]
    return matches


def category_dir(category: str) -> str:
    return {
        "mechanism": "Mechanisms",
        "method": "Methods",
        "catalyst": "Catalysts",
        "reactant": "Reactants",
        "chemical": "Chemicals",
        "concept": "Concepts",
    }.get(category, "Concepts")


def replace_block(text: str, start: str, end: str, block: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", flags=re.DOTALL)
    clean = block.strip() + "\n"
    if pattern.search(text):
        return pattern.sub(clean, text, count=1)
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + "\n" + clean


def article_block(analysis: dict[str, Any], questions: list[dict[str, Any]], experiments: list[dict[str, Any]]) -> str:
    terms = [term["name"] for term in analysis["terms"]]
    project_terms = [term["name"] for term in analysis.get("project_relevance_terms", [])]
    source_links = ", ".join(wikilink(term) for term in terms[:14]) or "No high-confidence local source term match."
    project_links = ", ".join(wikilink(term) for term in project_terms[:10]) or "No additional project connector assigned."
    rq_links = [question for question in questions if any(term in question["concepts"] for term in terms)]
    rq_links.extend(question for question in questions if any(term in question["concepts"] for term in project_terms))
    exp_links = [experiment for experiment in experiments if any(term in experiment["concepts"] for term in terms)]
    exp_links.extend(experiment for experiment in experiments if any(term in experiment["concepts"] for term in project_terms))
    rq_links = list({question["id"]: question for question in rq_links}.values())
    exp_links = list({experiment["id"]: experiment for experiment in exp_links}.values())
    lines = [
        MANAGED_START,
        "## Codex Literature Analysis",
        "",
        "> [!note] Evidence boundary",
        "> This section is generated from local capture metadata and existing Obsidian note text only. It does not claim full-PDF extraction or new experimental facts.",
        "",
        f"- Analysis status: `local_metadata_analysis`",
        f"- Corpus role: `{analysis.get('corpus_role', 'background_context')}`",
        f"- Project relevance: {analysis['relevance_to_project']}",
        f"- Mechanistic summary: {analysis['mechanistic_summary']}",
        f"- Source-detected concepts: {source_links}",
        f"- Project-relevance connectors: {project_links}",
        "",
        "### Evidence Methods Detected",
    ]
    if analysis["evidence_methods"]:
        for method in analysis["evidence_methods"]:
            lines.append(f"- {wikilink(method['name'])}: `{method['evidence']['source_field']}`")
    else:
        lines.append("- None explicitly detected in local capture text.")
    lines.extend(["", "### Linked Research Questions"])
    if rq_links:
        for question in rq_links[:4]:
            lines.append(f"- [[{question_note_title_by_id(question['id'])}]]")
    else:
        lines.append("- No specific generated research question matched the detected terms.")
    lines.extend(["", "### Linked Experiment Suggestions"])
    if exp_links:
        for experiment in exp_links[:4]:
            lines.append(f"- [[{experiment_note_title_by_id(experiment['id'])}]]")
    else:
        lines.append("- No specific generated experiment matched the detected terms.")
    if analysis["limitations"]:
        lines.extend(["", "### Metadata Limitations"])
        lines.extend(f"- {item}" for item in analysis["limitations"])
    lines.append(MANAGED_END)
    return "\n".join(lines)


def write_literature_blocks(vault: Path, analyses: list[dict[str, Any]], questions: list[dict[str, Any]], experiments: list[dict[str, Any]]) -> list[str]:
    changed = []
    for analysis in analyses:
        path_text = analysis.get("note_path") or ""
        if not path_text:
            continue
        path = Path(path_text)
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = replace_block(original, MANAGED_START, MANAGED_END, article_block(analysis, questions, experiments))
        if updated != original:
            write_text_atomic(path, updated)
            changed.append(str(path))
    return changed


def node_block(node: dict[str, Any], network_title: str) -> str:
    lines = [
        NODE_START,
        "## Codex Research Network",
        "",
        f"- Network: [[{network_title}]]",
        f"- Node category: `{node['category']}`",
        "",
        "### Evidence Papers",
    ]
    if node["articles"]:
        for item in node["articles"][:12]:
            source_type = item.get("source_type") or "source_detected"
            lines.append(f"- [[{item['note_title']}]] ({item['doi']}) - `{source_type}` / `{item['evidence'].get('source_field', '')}`")
    else:
        lines.append("- No direct batch paper evidence; included as a research-hypothesis connector.")
    if node["questions"]:
        lines.extend(["", "### Research Questions"])
        lines.extend(f"- [[{question_note_title_by_id(qid)}]]" for qid in sorted(set(node["questions"])))
    if node["experiments"]:
        lines.extend(["", "### Experiment Suggestions"])
        lines.extend(f"- [[{experiment_note_title_by_id(eid)}]]" for eid in sorted(set(node["experiments"])))
    lines.append(NODE_END)
    return "\n".join(lines)


QUESTION_NOTE_TITLES: dict[str, str] = {}
EXPERIMENT_NOTE_TITLES: dict[str, str] = {}


def question_note_title_by_id(qid: str) -> str:
    return QUESTION_NOTE_TITLES.get(qid, f"{qid} - Research Question")


def experiment_note_title_by_id(eid: str) -> str:
    return EXPERIMENT_NOTE_TITLES.get(eid, f"{eid} - Experiment Suggestion")


def ensure_node_file(vault: Path, node: dict[str, Any], network_title: str) -> str:
    folder = vault / category_dir(node["category"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_filename(node["name"])
    if path.exists():
        original = path.read_text(encoding="utf-8", errors="replace")
    else:
        original = frontmatter(node["name"], f"knowledge_{node['category']}", ["knowledge-node", "codex-research-network"]) + f"# {node['name']}\n"
    updated = replace_block(original, NODE_START, NODE_END, node_block(node, network_title))
    if updated != original:
        write_text_atomic(path, updated)
    return str(path)


def write_question_notes(vault: Path, questions: list[dict[str, Any]], network_title: str) -> list[str]:
    folder = vault / "Research Questions"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for question in questions:
        title = safe_note_title(f"{question['id']} - {question['title']}")
        lines = [
            frontmatter(title, "research_question", ["research-question", "codex-research-network"]),
            f"# {title}",
            "",
            f"- Network: [[{network_title}]]",
            f"- Status: `{question['status']}`",
            "",
            "## Why This Question Matters",
            question["why"],
            "",
            "## Concept Links",
            ", ".join(wikilink(item) for item in question["concepts"]),
            "",
            "## Evidence Papers",
        ]
        if question["evidence_articles"]:
            lines.extend(f"- [[{item['note_title']}]] ({item['doi']})" for item in question["evidence_articles"])
        else:
            lines.append("- No direct evidence paper in this batch; retain as hypothesis context.")
        lines.extend(["", "## Guardrail", "Do not treat this question as a literature conclusion until supported by direct experiments or full-text evidence."])
        path = folder / safe_filename(title)
        write_text_atomic(path, "\n".join(lines) + "\n")
        paths.append(str(path))
    return paths


def write_experiment_notes(vault: Path, experiments: list[dict[str, Any]], network_title: str) -> list[str]:
    folder = vault / "Experiment Suggestions"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for exp in experiments:
        title = safe_note_title(f"{exp['id']} - {exp['title']}")
        lines = [
            frontmatter(title, "experiment_suggestion", ["experiment-suggestion", "codex-research-network"]),
            f"# {title}",
            "",
            f"- Network: [[{network_title}]]",
            f"- Research question: [[{question_note_title_by_id(exp['research_question_id'])}]]",
            "",
            "## Rationale",
            exp["rationale"],
            "",
            "## Concept Links",
            ", ".join(wikilink(item) for item in exp["concepts"]),
            "",
            "## Expected Readouts",
        ]
        lines.extend(f"- {item}" for item in exp["expected_readouts"])
        lines.extend(["", "## Controls"])
        lines.extend(f"- {item}" for item in exp.get("controls", []))
        lines.extend(["", "## Risk / Failure Criteria"])
        lines.extend(f"- {item}" for item in exp.get("risk_failure_criteria", []))
        lines.extend(["", "## Evidence Papers"])
        if exp["evidence_articles"]:
            lines.extend(f"- [[{item['note_title']}]] ({item['doi']})" for item in exp["evidence_articles"])
        else:
            lines.append("- No direct evidence paper in this batch; use as design hypothesis.")
        lines.extend(["", "## Guardrail", exp["safety_note"]])
        path = folder / safe_filename(title)
        write_text_atomic(path, "\n".join(lines) + "\n")
        paths.append(str(path))
    return paths


def write_index_note(vault: Path, network: dict[str, Any], network_title: str) -> str:
    folder = vault / "Research Networks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_filename(network_title)
    analyses = network["articles"]
    lines = [
        frontmatter(network_title, "research_network_index", ["research-network", "codex-research-network"]),
        f"# {network_title}",
        "",
        "## Scope",
        "Local metadata-based network for the 20260713 keyword workflow batch. It is designed to connect literature notes, mechanisms, research questions, and experiment suggestions without claiming unsupported full-text facts.",
        "",
        "## Literature Corpus",
    ]
    by_version: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in analyses:
        by_version[item.get("version_group_key") or item["doi"]].append(item)
    for group in by_version.values():
        if len(group) == 1:
            item = group[0]
            lines.append(f"- [[{item['note_title']}]] - {item['year']} - `{item['doi']}` - `{item.get('corpus_role', '')}`")
        else:
            primary = next((item for item in group if "chemrxiv" not in item["doi"].lower()), group[0])
            alternates = [item for item in group if item is not primary]
            lines.append(f"- [[{primary['note_title']}]] - {primary['year']} - `{primary['doi']}` - `{primary.get('corpus_role', '')}`")
            for alt in alternates:
                lines.append(f"  - version pair: [[{alt['note_title']}]] - `{alt['doi']}` - `{alt.get('corpus_role', '')}`")
    lines.extend(["", "## Corpus Role Summary"])
    role_counts = Counter(item.get("corpus_role", "background_context") for item in analyses)
    for role, count in sorted(role_counts.items()):
        lines.append(f"- `{role}`: {count}")
    lines.extend(["", "## High-Frequency Source Concepts"])
    counts = Counter(term["name"] for article in analyses for term in article["terms"])
    for name, count in counts.most_common(15):
        lines.append(f"- [[{name}]]: {count}")
    lines.extend(["", "## Project-Relevance Connectors"])
    project_counts = Counter(term["name"] for article in analyses for term in article.get("project_relevance_terms", []))
    for name, count in project_counts.most_common(15):
        lines.append(f"- [[{name}]]: {count}")
    if not project_counts:
        lines.append("- None")
    lines.extend(["", "## Research Questions"])
    for question in network["research_questions"]:
        lines.append(f"- [[{question_note_title_by_id(question['id'])}]]")
    lines.extend(["", "## Experiment Suggestions"])
    for exp in network["experiment_suggestions"]:
        lines.append(f"- [[{experiment_note_title_by_id(exp['id'])}]]")
    lines.extend(["", "## Relationship Highlights"])
    for rel in network["relations"][:20]:
        source = next((a["note_title"] for a in analyses if a["doi"] == rel["source"]), rel["source"])
        target = next((a["note_title"] for a in analyses if a["doi"] == rel["target"]), rel["target"])
        detail = ", ".join(rel.get("shared_terms") or [rel.get("contrast", "")])
        lines.append(f"- [[{source}]] -> [[{target}]]: `{rel['type']}` {detail}")
    write_text_atomic(path, "\n".join(lines) + "\n")
    return str(path)


def validate_test_vault(vault: Path) -> None:
    if not vault.exists():
        raise NetworkError(f"Vault does not exist: {vault}")
    if vault.name == "Obsidian Vault":
        raise NetworkError("Refusing to write to formal Obsidian Vault.")
    if not (vault / ".obsidian").exists():
        raise NetworkError(f"Not an Obsidian vault: {vault}")


def build_network(capture_dir: Path, workflow_dir: Path | None, vault: Path | None = None) -> dict[str, Any]:
    articles = load_capture(capture_dir)
    if len(articles) != 10:
        raise NetworkError(f"Expected 10 capture records for this MVP; found {len(articles)}.")
    articles = merge_zotero_links(articles, load_link_map(workflow_dir, capture_dir))
    note_map = find_literature_notes(vault, articles) if vault else {}
    analyses = [analysis_for_article(article, note_map.get(normalize_doi(article.get("doi")))) for article in articles]
    relations = build_relations(analyses)
    questions = build_research_questions(analyses)
    experiments = build_experiments(questions)
    QUESTION_NOTE_TITLES.update({item["id"]: safe_note_title(f"{item['id']} - {item['title']}") for item in questions})
    EXPERIMENT_NOTE_TITLES.update({item["id"]: safe_note_title(f"{item['id']} - {item['title']}") for item in experiments})
    nodes = build_nodes(analyses, questions, experiments)
    return {
        "schema": NETWORK_SCHEMA,
        "created_at": utc_now(),
        "capture_dir": str(capture_dir),
        "workflow_dir": str(workflow_dir) if workflow_dir else "",
        "article_count": len(analyses),
        "articles": analyses,
        "nodes": nodes,
        "relations": relations,
        "research_questions": questions,
        "experiment_suggestions": experiments,
        "safety": {
            "offline_only": True,
            "uses_zotero_sqlite": False,
            "modifies_zotero": False,
            "modifies_formal_vault": False,
            "copies_pdfs": False,
            "uses_ocr": False,
        },
    }


def write_outputs(out_dir: Path, network: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "analysis_json": str(out_dir / "literature_analysis.json"),
        "network_json": str(out_dir / "knowledge_network.json"),
        "research_questions_json": str(out_dir / "research_questions.json"),
        "experiment_suggestions_json": str(out_dir / "experiment_suggestions.json"),
        "run_report": str(out_dir / "run_report.md"),
    }
    write_json(Path(paths["analysis_json"]), {"schema": NETWORK_SCHEMA + ".articles", "articles": network["articles"]})
    write_json(Path(paths["network_json"]), network)
    write_json(Path(paths["research_questions_json"]), {"questions": network["research_questions"]})
    write_json(Path(paths["experiment_suggestions_json"]), {"experiments": network["experiment_suggestions"]})
    write_text_atomic(Path(paths["run_report"]), build_run_report(network, paths))
    return paths


def build_run_report(network: dict[str, Any], paths: dict[str, str]) -> str:
    lines = [
        "# Research Knowledge Network Run Report",
        "",
        f"- Created at: `{network['created_at']}`",
        f"- Articles: `{network['article_count']}`",
        f"- Nodes: `{len(network['nodes'])}`",
        f"- Relations: `{len(network['relations'])}`",
        f"- Research questions: `{len(network['research_questions'])}`",
        f"- Experiment suggestions: `{len(network['experiment_suggestions'])}`",
        "",
        "## Safety",
    ]
    for key, value in network["safety"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Outputs"])
    for key, value in paths.items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


def write_vault_outputs(vault: Path, network: dict[str, Any], network_title: str) -> dict[str, Any]:
    validate_test_vault(vault)
    changed_literature = write_literature_blocks(vault, network["articles"], network["research_questions"], network["experiment_suggestions"])
    question_paths = write_question_notes(vault, network["research_questions"], network_title)
    experiment_paths = write_experiment_notes(vault, network["experiment_suggestions"], network_title)
    node_paths = [ensure_node_file(vault, node, network_title) for node in network["nodes"]]
    index_path = write_index_note(vault, network, network_title)
    return {
        "literature_notes_updated": changed_literature,
        "question_notes": question_paths,
        "experiment_notes": experiment_paths,
        "node_notes": node_paths,
        "index_note": index_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an offline Codex/Obsidian research knowledge network from local captures.")
    parser.add_argument("--capture-dir", required=True, help="lit-search-cite capture directory containing captured.json.")
    parser.add_argument("--workflow-dir", default="", help="Optional keyword workflow directory containing zotero_link_map.json.")
    parser.add_argument("--out", default="", help="Output directory for analysis JSON.")
    parser.add_argument("--vault", default="", help="Obsidian test vault path.")
    parser.add_argument("--write-vault", action="store_true", help="Write managed Obsidian notes to the test vault.")
    parser.add_argument("--network-title", default="20260713_100712 Research Knowledge Network")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    capture_dir = Path(args.capture_dir).expanduser().resolve()
    workflow_dir = Path(args.workflow_dir).expanduser().resolve() if args.workflow_dir else None
    vault = Path(args.vault).expanduser().resolve() if args.vault else None
    if args.write_vault and not vault:
        raise NetworkError("--write-vault requires --vault")
    out_dir = Path(args.out).expanduser().resolve() if args.out else (workflow_dir or capture_dir) / "research_knowledge_network" / now_stamp()
    network = build_network(capture_dir, workflow_dir, vault)
    paths = write_outputs(out_dir, network)
    vault_result: dict[str, Any] = {}
    if args.write_vault:
        vault_result = write_vault_outputs(vault, network, args.network_title)
        write_json(out_dir / "obsidian_write_result.json", vault_result)
    summary = {
        "ok": True,
        "schema": NETWORK_SCHEMA + ".summary",
        "out_dir": str(out_dir),
        "article_count": network["article_count"],
        "node_count": len(network["nodes"]),
        "relation_count": len(network["relations"]),
        "research_question_count": len(network["research_questions"]),
        "experiment_suggestion_count": len(network["experiment_suggestions"]),
        "paths": paths,
        "vault_written": bool(args.write_vault),
        "vault_result": vault_result,
        "safety": network["safety"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NetworkError as exc:
        print(f"research-knowledge-network error: {exc}", file=sys.stderr)
        raise SystemExit(2)
