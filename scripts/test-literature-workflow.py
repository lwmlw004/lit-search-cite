#!/usr/bin/env python3
"""No-network tests for scripts/literature-workflow.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "scripts" / "literature-workflow.py"


def load_workflow():
    spec = importlib.util.spec_from_file_location("literature_workflow", WORKFLOW_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {WORKFLOW_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiteratureWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_workflow()

    def test_priority_selection_prefers_relevant_doi_candidates(self):
        candidates = json.loads((ROOT / "evals" / "workflow" / "sample_discovery.json").read_text(encoding="utf-8"))
        selected = self.workflow.select_candidates(
            candidates,
            count=2,
            priority_terms=["radical", "nickel catalysis", "SH2 mechanism"],
            query="asymmetric C(sp3)-C(sp3) coupling radical nickel SH2",
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]["doi"], "10.1234/nickel.radical")
        self.assertIn("radical", selected[0]["workflow_priority_hits"])
        self.assertIn("query match: C(sp3)-C(sp3) bond/coupling", selected[0]["workflow_relevance_reasons"])
        self.assertEqual(selected[1]["doi"], "10.1234/sh2.fixture")
        self.assertNotEqual(selected[0]["doi"], "10.1234/noise")

    def test_selection_dedupes_preprint_and_article_title_variants(self):
        candidates = [
            {
                "title": "Ni/Photoredox-Catalyzed C(sp <sup>3</sup> )–C(sp <sup>3</sup> ) Coupling",
                "doi": "10.1021/article",
                "year": 2024,
                "citations": 20,
                "oa_url": "",
            },
            {
                "title": "Ni/Photoredox-Catalyzed C(sp3)−C(sp3) Coupling",
                "doi": "10.26434/preprint",
                "year": 2023,
                "citations": 5,
                "oa_url": "",
            },
            {
                "title": "Cross-ketone deacylative coupling via oxidative SH2 homolytic substitution",
                "doi": "10.1038/sh2",
                "year": 2026,
                "citations": 3,
                "oa_url": "",
            },
        ]

        selected = self.workflow.select_candidates(
            candidates,
            count=3,
            priority_terms=["SH2 mechanism"],
            query="C(sp3)-C(sp3) coupling SH2",
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual([item["doi"] for item in selected].count("10.1021/article"), 1)
        self.assertNotIn("10.26434/preprint", [item["doi"] for item in selected])

    def test_selected_identifiers_use_doi_urls(self):
        selected = [
            {"doi": "https://doi.org/10.1234/test.one", "title": "Test One"},
            {"doi": "", "oa_url": "https://example.org/two.pdf", "title": "Test Two"},
        ]

        lines = self.workflow.selected_identifier_lines(selected)

        self.assertEqual(lines[0], "https://doi.org/10.1234/test.one")
        self.assertEqual(lines[1], "https://example.org/two.pdf")

    def test_zotero_queue_from_capture_is_safe_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = Path(tmp) / "capture"
            capture_dir.mkdir()
            (capture_dir / "captured.json").write_text(json.dumps([
                {
                    "title": "Fixture Article",
                    "authors": ["Ada Example", "Ben Example"],
                    "year": "2025",
                    "journal": "Journal of Test Chemistry",
                    "doi": "10.1234/fixture",
                    "url": "https://doi.org/10.1234/fixture",
                    "pdf_status": "downloaded",
                    "pdf_path": "pdfs/fixture.pdf",
                    "pdf_url": "https://example.org/fixture.pdf",
                    "license": "cc-by",
                    "oa_status": "gold"
                }
            ]), encoding="utf-8")
            articles = self.workflow.captured_articles(capture_dir)
            queue = self.workflow.build_zotero_queue(
                query="fixture query",
                workflow_dir=Path(tmp) / "workflow",
                capture_dir=capture_dir,
                selected=[],
                articles=articles,
            )

        self.assertEqual(queue["schema"], self.workflow.ZOTERO_QUEUE_SCHEMA)
        self.assertEqual(queue["contract_status"], "intermediate_handoff_contract")
        self.assertIn("runtime plugin schema was not available", queue["target_consumer"])
        self.assertFalse(queue["safety"]["writes_zotero_sqlite"])
        self.assertFalse(queue["safety"]["reads_browser_cookies"])
        self.assertEqual(queue["total_items"], 1)
        item = queue["items"][0]
        self.assertEqual(item["doi"], "10.1234/fixture")
        self.assertEqual(item["bibtex_path"], "captured.bib")
        self.assertEqual(item["ris_path"], "captured.ris")
        self.assertEqual(item["pdf_status"], "downloaded")
        self.assertEqual(item["pdf_path"], "pdfs/fixture.pdf")
        self.assertTrue(any("Zotero.Attachments.importFromFile" in note for note in item["notes"]))

    def test_cli_can_generate_offline_workflow_without_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "workflows"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(WORKFLOW_PATH),
                    "--query",
                    "asymmetric C(sp3)-C(sp3) coupling",
                    "--search-results",
                    str(ROOT / "evals" / "workflow" / "sample_discovery.json"),
                    "--out",
                    str(out),
                    "--select",
                    "2",
                    "--priority",
                    "radical,nickel catalysis,SH2 mechanism",
                    "--skip-capture",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            workflow_dir = Path(summary["workflow_dir"])

            self.assertTrue((workflow_dir / "discovery.json").exists())
            self.assertTrue((workflow_dir / "candidates.md").exists())
            self.assertTrue((workflow_dir / "selected_identifiers.txt").exists())
            self.assertTrue((workflow_dir / "zotero_queue.json").exists())
            self.assertTrue((workflow_dir / "workflow_report.md").exists())
            queue = json.loads((workflow_dir / "zotero_queue.json").read_text(encoding="utf-8"))
            self.assertEqual(queue["total_items"], 2)
            self.assertEqual(queue["items"][0]["pdf_status"], "capture_not_run")
            self.assertIn("web-capture was skipped", (workflow_dir / "workflow_report.md").read_text(encoding="utf-8"))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(LiteratureWorkflowTests))
    return suite


if __name__ == "__main__":
    unittest.main()
