#!/usr/bin/env python3
"""Tests for research-knowledge-network.py."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "research-knowledge-network.py"


def load_module():
    spec = importlib.util.spec_from_file_location("research_knowledge_network", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResearchKnowledgeNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def sample_articles(self):
        return [
            {
                "title": "Cross-ketone deacylative coupling via oxidative SH2 homolytic substitution",
                "doi": "10.1038/example",
                "year": "2026",
                "journal": "Nature Communications",
                "abstract": "A nickel-catalyzed radical cross-coupling via bimolecular homolytic substitution (SH2) constructs C(sp3)-C(sp3) linkages.",
                "keywords": ["nickel catalysis", "SH2", "cross-coupling"],
                "concepts": ["Radical", "Coupling reaction"],
            },
            {
                "title": "Nickel photoredox dual catalyzed arylalkylation of nonactivated alkenes",
                "doi": "10.1038/example2",
                "year": "2023",
                "journal": "Nature Communications",
                "abstract": "An enantioselective nickel/photoredox method gives C(sp3)-C(sp3) products with a pyridine-oxazoline ligand.",
                "keywords": ["photoredox catalysis", "enantioselective"],
                "concepts": ["Nickel", "Photoredox catalysis"],
            },
        ]

    def test_detects_mechanistic_terms_without_claiming_full_text(self):
        analysis = self.mod.analysis_for_article(self.sample_articles()[0], None)

        terms = {term["name"] for term in analysis["terms"]}
        project_terms = {term["name"] for term in analysis["project_relevance_terms"]}
        self.assertIn("SH2 mechanism", terms)
        self.assertIn("homolytic substitution", terms)
        self.assertIn("C(sp3)-C(sp3) cross-coupling", terms)
        self.assertIn("nickel catalyst", terms)
        self.assertIn("radical flux", project_terms)
        self.assertNotIn("radical flux", terms)
        self.assertIn("corpus_role", analysis)
        self.assertIn("Local capture directly flags SH2", analysis["mechanistic_summary"])
        self.assertNotIn("yield", json.dumps(analysis).lower())

    def test_evidence_methods_require_specific_language(self):
        loose = {
            "title": "A decarbonylative approach to alkylnickel intermediates",
            "doi": "10.1000/loose",
            "abstract": "The reaction forms an alkylnickel intermediate in a catalytic cycle.",
        }
        strict = {
            "title": "Stoichiometric trapping of a nickel intermediate",
            "doi": "10.1000/strict",
            "abstract": "A stoichiometric experiment trapped and characterized the intermediate by NMR.",
        }

        self.assertNotIn("stoichiometric intermediate", {m["name"] for m in self.mod.detect_evidence_methods(loose)})
        self.assertIn("stoichiometric intermediate", {m["name"] for m in self.mod.detect_evidence_methods(strict)})

    def test_fallback_note_title_accepts_string_authors(self):
        article = {
            "title": "Fallback title from string authors",
            "year": "2026",
            "authors": ["Zhidao Huang", "Michelle E. Akana"],
        }

        self.assertTrue(self.mod.note_title_from_path(None, article).startswith("Huang 2026 - "))

    def test_builds_questions_and_experiments_with_guardrails(self):
        analyses = [self.mod.analysis_for_article(article, None) for article in self.sample_articles()]
        questions = self.mod.build_research_questions(analyses)
        experiments = self.mod.build_experiments(questions)

        self.assertEqual(len(questions), 6)
        self.assertEqual(len(experiments), 6)
        self.assertTrue(all(question["status"] == "research_question_not_literature_conclusion" for question in questions))
        self.assertTrue(any("SH2" in question["title"] for question in questions))
        self.assertTrue(all("no yield" in experiment["safety_note"].lower() for experiment in experiments))
        self.assertTrue(all(experiment["controls"] for experiment in experiments))
        self.assertTrue(all(experiment["risk_failure_criteria"] for experiment in experiments))

    def test_relations_connect_shared_terms(self):
        analyses = [self.mod.analysis_for_article(article, None) for article in self.sample_articles()]
        relations = self.mod.build_relations(analyses)

        self.assertTrue(any(rel["type"] == "shared_mechanistic_or_method_terms" for rel in relations))
        self.assertTrue(any("nickel catalyst" in rel.get("shared_terms", []) for rel in relations))

    def test_version_pairs_and_evidence_method_nodes_are_explicit(self):
        articles = [
            {
                "title": "Ni/Photoredox-Catalyzed C(sp3)-C(sp3) Coupling between Aziridines and Acetals",
                "doi": "10.1021/jacs.example",
                "journal": "Journal of the American Chemical Society",
                "abstract": "DFT was used with nickel photoredox C(sp3)-C(sp3) coupling.",
            },
            {
                "title": "Ni/Photoredox-Catalyzed C(sp3)-C(sp3) Coupling between Aziridines and Acetals",
                "doi": "10.26434/chemrxiv-example",
                "journal": "ChemRxiv",
                "abstract": "A nickel photoredox coupling preprint.",
            },
        ]
        analyses = [self.mod.analysis_for_article(article, None) for article in articles]
        relations = self.mod.build_relations(analyses)
        questions = self.mod.build_research_questions(analyses)
        experiments = self.mod.build_experiments(questions)
        nodes = self.mod.build_nodes(analyses, questions, experiments)

        self.assertTrue(any(rel["type"] == "version_pair" for rel in relations))
        self.assertIn("DFT", {node["name"] for node in nodes})
        self.assertEqual("preprint_version", analyses[1]["corpus_role"])

    def test_writes_vault_managed_blocks_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "Obsidian_Test_Vault_Unit"
            literature = vault / "literature"
            literature.mkdir(parents=True)
            (vault / ".obsidian").mkdir()
            note = literature / "Example 2026.md"
            note.write_text("---\ntitle: Example\n---\n# Example\nDOI: 10.1038/example\n", encoding="utf-8")

            articles = self.sample_articles()
            network = _build_network_from_articles_for_test(self.mod, articles, vault)
            first = self.mod.write_vault_outputs(vault, network, "Unit Research Network")
            first_text = note.read_text(encoding="utf-8")
            second = self.mod.write_vault_outputs(vault, network, "Unit Research Network")
            second_text = note.read_text(encoding="utf-8")
            experiment_note = Path(first["experiment_notes"][0]).read_text(encoding="utf-8")

        self.assertIn(self.mod.MANAGED_START, first_text)
        self.assertIn("Source-detected concepts", first_text)
        self.assertIn("Project-relevance connectors", first_text)
        self.assertIn("Corpus role", first_text)
        self.assertEqual(first_text, second_text)
        self.assertTrue(first["index_note"].endswith("Unit Research Network.md"))
        self.assertEqual(first["index_note"], second["index_note"])
        self.assertIn("## Controls", experiment_note)
        self.assertIn("## Risk / Failure Criteria", experiment_note)

    def test_refuses_formal_vault_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "Obsidian Vault"
            vault.mkdir()
            (vault / ".obsidian").mkdir()
            with self.assertRaises(self.mod.NetworkError):
                self.mod.validate_test_vault(vault)

    def test_build_network_accepts_non_ten_article_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "capture"
            capture.mkdir()
            (capture / "captured.json").write_text(
                json.dumps({"items": self.sample_articles()}),
                encoding="utf-8",
            )

            network = self.mod.build_network(capture, None, None)

        self.assertEqual(2, network["article_count"])


def _build_network_from_articles_for_test(module, articles, vault):
    note_map = module.find_literature_notes(vault, articles)
    analyses = [
        module.analysis_for_article(article, note_map.get(module.normalize_doi(article.get("doi"))))
        for article in articles
    ]
    relations = module.build_relations(analyses)
    questions = module.build_research_questions(analyses)
    experiments = module.build_experiments(questions)
    module.QUESTION_NOTE_TITLES.update(
        {item["id"]: module.safe_note_title(f"{item['id']} - {item['title']}") for item in questions}
    )
    module.EXPERIMENT_NOTE_TITLES.update(
        {item["id"]: module.safe_note_title(f"{item['id']} - {item['title']}") for item in experiments}
    )
    return {
        "schema": module.NETWORK_SCHEMA,
        "created_at": module.utc_now(),
        "capture_dir": "",
        "workflow_dir": "",
        "article_count": len(analyses),
        "articles": analyses,
        "nodes": module.build_nodes(analyses, questions, experiments),
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


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ResearchKnowledgeNetworkTests))
    return suite


if __name__ == "__main__":
    unittest.main()
