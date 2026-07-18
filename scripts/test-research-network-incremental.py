#!/usr/bin/env python3
"""Tests for research-network-incremental.py."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "research-network-incremental.py"


def load_module():
    spec = importlib.util.spec_from_file_location("research_network_incremental", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResearchNetworkIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()
        cls.rkn = cls.mod.load_rkn_module()

    def make_capture(self, root: Path, articles: list[dict]) -> Path:
        capture = root / "capture"
        capture.mkdir(parents=True)
        (capture / "captured.json").write_text(json.dumps({"items": articles}), encoding="utf-8")
        return capture

    def base_articles(self) -> list[dict]:
        return [
            {
                "title": "Cross-ketone deacylative coupling via oxidative SH2 homolytic substitution",
                "doi": "10.1038/example",
                "year": "2026",
                "journal": "Nature Communications",
                "abstract": "Nickel radical cross-coupling via SH2 gives C(sp3)-C(sp3) products.",
                "keywords": ["nickel catalysis", "SH2"],
            },
            {
                "title": "Ni/Photoredox-Catalyzed C(sp3)-C(sp3) Coupling between Aziridines and Acetals",
                "doi": "10.1021/jacs.example",
                "year": "2022",
                "journal": "Journal of the American Chemical Society",
                "abstract": "DFT was used with nickel photoredox C(sp3)-C(sp3) coupling.",
            },
        ]

    def make_vault_with_network(self, root: Path, capture: Path) -> Path:
        vault = root / "FormalLikeVault"
        (vault / ".obsidian").mkdir(parents=True)
        for article in self.mod.load_capture(capture):
            title, text = self.mod.note_stub_for_article(self.rkn, article)
            path = vault / "literature" / self.rkn.safe_filename(title)
            self.mod.write_text_atomic(path, text)
        network = self.rkn.build_network(capture, None, vault)
        self.rkn.write_vault_outputs(vault, network, "Unit Incremental Network")
        return vault

    def test_inventory_classifies_noop_existing_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = self.make_capture(root, self.base_articles())
            vault = self.make_vault_with_network(root, capture)

            articles = self.mod.load_capture(capture)
            cap_inv = self.mod.capture_inventory(capture, articles)
            vault_inv = self.mod.inventory_vault(vault)
            plan = self.mod.build_plan(cap_inv, vault_inv, [])

        self.assertEqual({"noop": 2}, plan["actions"])
        self.assertEqual(0, plan["analysis_queue_count"])
        self.assertTrue(plan["safe_to_apply"])

    def test_prepare_detects_new_duplicates_and_version_pairs(self):
        articles = self.base_articles() + [
            {
                "title": "Ni/Photoredox-Catalyzed C(sp3)-C(sp3) Coupling between Aziridines and Acetals",
                "doi": "10.26434/chemrxiv-example",
                "year": "2022",
                "journal": "ChemRxiv",
                "abstract": "A preprint version of the nickel photoredox coupling.",
            },
            {
                "title": "Duplicate DOI record",
                "doi": "10.1038/example",
                "year": "2026",
                "journal": "Nature Communications",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = self.make_capture(root, articles)
            vault = root / "FormalLikeVault"
            (vault / ".obsidian").mkdir(parents=True)
            cap_inv = self.mod.capture_inventory(capture, self.mod.load_capture(capture))
            vault_inv = self.mod.inventory_vault(vault)
            plan = self.mod.build_plan(cap_inv, vault_inv, [])

        self.assertEqual(2, plan["actions"]["duplicate_in_capture"])
        self.assertEqual(2, plan["actions"]["new"])
        self.assertEqual(1, len(plan["version_pairs"]))
        self.assertFalse(plan["safe_to_apply"])

    def test_preview_noop_has_zero_changes_after_existing_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = self.make_capture(root, self.base_articles())
            vault = self.make_vault_with_network(root, capture)
            out = root / "out"

            summary = self.mod.run_readonly(
                _args(capture, vault, out, stage="preview", network_title="Unit Incremental Network")
            )
            verify = json.loads((out / "verify_report.json").read_text(encoding="utf-8"))

        self.assertEqual(0, summary["preview_changed_file_count"])
        self.assertEqual(0, summary["analysis_queue_count"])
        self.assertEqual(0, verify["broken_wikilinks_count"])
        self.assertTrue(verify["ok"])

    def test_preview_incremental_new_article_changes_preview_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_capture = self.make_capture(root, self.base_articles())
            vault = self.make_vault_with_network(root, base_capture)
            new_articles = self.base_articles() + [
                {
                    "title": "Electrochemical radical flux in nickel cross-coupling",
                    "doi": "10.1000/new",
                    "year": "2026",
                    "journal": "Preview Journal",
                    "abstract": "Electrode current density controls radical flux in nickel cross-coupling.",
                }
            ]
            capture = self.make_capture(root / "incremental", new_articles)
            out = root / "out"

            summary = self.mod.run_readonly(
                _args(capture, vault, out, stage="preview", network_title="Unit Incremental Network")
            )
            original_literature = sorted((vault / "literature").glob("*.md"))

        self.assertEqual(1, summary["actions"]["new"])
        self.assertGreater(summary["preview_changed_file_count"], 0)
        self.assertEqual(2, len(original_literature))

    def test_apply_requires_explicit_allow_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = self.make_capture(root, self.base_articles())
            vault = self.make_vault_with_network(root, capture)

            with self.assertRaises(self.mod.IncrementalError):
                self.mod.run_apply(_args(capture, vault, root / "out", stage="apply"))


def _args(capture: Path, vault: Path, out: Path, stage: str, network_title: str = "Unit Incremental Network"):
    return type(
        "Args",
        (),
        {
            "capture_dir": str(capture),
            "workflow_dir": "",
            "vault": str(vault),
            "current_runtime": "",
            "out": str(out),
            "network_title": network_title,
            "stage": stage,
            "allow_apply": False,
            "obsidian_importer": "",
        },
    )()


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ResearchNetworkIncrementalTests))
    return suite


if __name__ == "__main__":
    unittest.main()
