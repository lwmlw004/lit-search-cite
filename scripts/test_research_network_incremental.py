"""unittest discovery bridge for test-research-network-incremental.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


LEGACY_TEST_PATH = Path(__file__).with_name("test-research-network-incremental.py")
SPEC = importlib.util.spec_from_file_location("test_research_network_incremental_legacy", LEGACY_TEST_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {LEGACY_TEST_PATH}")
LEGACY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEGACY)

load_tests = LEGACY.load_tests
