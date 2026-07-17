"""unittest discovery bridge for test-research-knowledge-network.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


LEGACY_TEST_PATH = Path(__file__).with_name("test-research-knowledge-network.py")
SPEC = importlib.util.spec_from_file_location("test_research_knowledge_network_legacy", LEGACY_TEST_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {LEGACY_TEST_PATH}")
LEGACY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEGACY)

load_tests = LEGACY.load_tests
