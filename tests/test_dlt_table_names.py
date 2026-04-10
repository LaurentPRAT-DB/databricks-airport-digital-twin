"""Tests that DLT pipeline table names are consistent across Bronze/Silver/Gold layers.

These tests catch the case where a table is renamed in one layer but not in the
layer that reads from it — a bug that would only surface at DLT runtime.
"""

import ast
import re
from pathlib import Path

import pytest

from src.pipelines import (
    BAGGAGE_EVENTS_BRONZE,
    BAGGAGE_EVENTS_GOLD,
    BAGGAGE_EVENTS_SILVER,
    BAGGAGE_STATUS_GOLD,
    FLIGHTS_BRONZE,
    FLIGHTS_SILVER,
    FLIGHT_STATUS_GOLD,
    LAKEBASE_BAGGAGE_STATUS,
    LAKEBASE_FLIGHT_STATUS,
)

PIPELINES_DIR = Path(__file__).resolve().parent.parent / "src" / "pipelines"


def _extract_table_names_and_reads(filepath: Path) -> tuple[list[str], list[str]]:
    """Parse a pipeline file and extract dlt.table(name=...) and dlt.read_stream(...) values."""
    source = filepath.read_text()
    tree = ast.parse(source)

    table_names: list[str] = []
    read_streams: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # dlt.table(name=X)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "table"
                and isinstance(func.value, ast.Name)
                and func.value.id == "dlt"
            ):
                for kw in node.keywords:
                    if kw.arg == "name":
                        if isinstance(kw.value, ast.Constant):
                            table_names.append(kw.value.value)
                        elif isinstance(kw.value, ast.Name):
                            # It's a constant reference — resolve from module
                            table_names.append(kw.value.id)

            # dlt.read_stream(X) or dlt.read(X)
            if (
                isinstance(func, ast.Attribute)
                and func.attr in ("read_stream", "read")
                and isinstance(func.value, ast.Name)
                and func.value.id == "dlt"
            ):
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant):
                        read_streams.append(arg.value)
                    elif isinstance(arg, ast.Name):
                        read_streams.append(arg.id)

    return table_names, read_streams


# ── Flight pipeline chain ────────────────────────────────────────────


class TestFlightPipelineChain:
    """Verify flights_bronze → flights_silver → flight_status_gold chain."""

    def test_constants_have_correct_values(self):
        assert FLIGHTS_BRONZE == "flights_bronze"
        assert FLIGHTS_SILVER == "flights_silver"
        assert FLIGHT_STATUS_GOLD == "flight_status_gold"

    def test_bronze_declares_correct_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "bronze.py")
        assert "FLIGHTS_BRONZE" in names or FLIGHTS_BRONZE in names

    def test_silver_reads_from_bronze(self):
        _, reads = _extract_table_names_and_reads(PIPELINES_DIR / "silver.py")
        assert "FLIGHTS_BRONZE" in reads or FLIGHTS_BRONZE in reads

    def test_silver_declares_correct_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "silver.py")
        assert "FLIGHTS_SILVER" in names or FLIGHTS_SILVER in names

    def test_gold_reads_from_silver(self):
        _, reads = _extract_table_names_and_reads(PIPELINES_DIR / "gold.py")
        assert "FLIGHTS_SILVER" in reads or FLIGHTS_SILVER in reads

    def test_gold_declares_correct_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "gold.py")
        assert "FLIGHT_STATUS_GOLD" in names or FLIGHT_STATUS_GOLD in names


# ── Baggage pipeline chain ───────────────────────────────────────────


class TestBaggagePipelineChain:
    """Verify baggage_events_bronze → silver → gold chain."""

    def test_constants_have_correct_values(self):
        assert BAGGAGE_EVENTS_BRONZE == "baggage_events_bronze"
        assert BAGGAGE_EVENTS_SILVER == "baggage_events_silver"
        assert BAGGAGE_STATUS_GOLD == "baggage_status_gold"
        assert BAGGAGE_EVENTS_GOLD == "baggage_events_gold"

    def test_bronze_declares_correct_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "baggage_bronze.py")
        assert "BAGGAGE_EVENTS_BRONZE" in names or BAGGAGE_EVENTS_BRONZE in names

    def test_silver_reads_from_bronze(self):
        _, reads = _extract_table_names_and_reads(PIPELINES_DIR / "baggage_silver.py")
        assert "BAGGAGE_EVENTS_BRONZE" in reads or BAGGAGE_EVENTS_BRONZE in reads

    def test_silver_declares_correct_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "baggage_silver.py")
        assert "BAGGAGE_EVENTS_SILVER" in names or BAGGAGE_EVENTS_SILVER in names

    def test_gold_reads_from_silver(self):
        _, reads = _extract_table_names_and_reads(PIPELINES_DIR / "baggage_gold.py")
        assert "BAGGAGE_EVENTS_SILVER" in reads or BAGGAGE_EVENTS_SILVER in reads

    def test_gold_declares_status_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "baggage_gold.py")
        assert "BAGGAGE_STATUS_GOLD" in names or BAGGAGE_STATUS_GOLD in names

    def test_gold_declares_events_table(self):
        names, _ = _extract_table_names_and_reads(PIPELINES_DIR / "baggage_gold.py")
        assert "BAGGAGE_EVENTS_GOLD" in names or BAGGAGE_EVENTS_GOLD in names


# ── Cross-pipeline: every read_stream has a matching table ───────────


class TestPipelineChainIntegrity:
    """Verify that every dlt.read_stream() references a declared dlt.table()."""

    def test_all_reads_have_matching_tables(self):
        all_tables: set[str] = set()
        all_reads: list[tuple[str, str]] = []  # (filename, read_target)

        for py_file in PIPELINES_DIR.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            names, reads = _extract_table_names_and_reads(py_file)
            all_tables.update(names)
            for r in reads:
                all_reads.append((py_file.name, r))

        for filename, read_target in all_reads:
            assert read_target in all_tables, (
                f"{filename} reads from '{read_target}' but no pipeline declares "
                f"dlt.table(name='{read_target}'). Declared tables: {sorted(all_tables)}"
            )


# ── Source FQN matches deployment config ─────────────────────────────


class TestSourceTableFQNs:
    """Verify that bronze layer source FQNs match the expected catalog.schema."""

    EXPECTED_CATALOG_SCHEMA = "serverless_stable_3n0ihb_catalog.airport_digital_twin"

    def test_flight_source_fqn(self):
        assert LAKEBASE_FLIGHT_STATUS.startswith(self.EXPECTED_CATALOG_SCHEMA)

    def test_baggage_source_fqn(self):
        assert LAKEBASE_BAGGAGE_STATUS.startswith(self.EXPECTED_CATALOG_SCHEMA)

    def test_no_hardcoded_fqn_in_pipeline_files(self):
        """Ensure pipeline files use the constant, not a hardcoded FQN string."""
        for py_file in PIPELINES_DIR.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            source = py_file.read_text()
            assert "serverless_stable_3n0ihb_catalog" not in source, (
                f"{py_file.name} still contains a hardcoded catalog FQN — "
                f"use LAKEBASE_* constants from src.pipelines instead"
            )
