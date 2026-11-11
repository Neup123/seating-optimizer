"""Self-contained smoke checks for the external-corpus comparison harness.

Real test-230 data deliberately stays in the coordinator workspace.
"""
from __future__ import annotations

import json

from seating_optimizer.equivalence import corpus_gate, small_random_gate
from test_generic_engine_foundation import _legacy_instances


def test_random_legacy_vs_generic_without_hidden_objective_terms():
    small_random_gate(samples=12)


def test_external_corpus_directory_interface_with_synthetic_manifest(tmp_path):
    (tmp_path / "test-230").mkdir()
    (tmp_path / "test-230-rerun").mkdir()
    (tmp_path / "test-230" / "guests-216-control.csv").write_text(
        "Name,Size,Language\nA,1,Greek\nB,1,Hebrew\n", encoding="utf-8"
    )
    configuration = {
        "version": 1, "name": "Synthetic venue",
        "zones": [{"id": "z", "name": "Z"}],
        "tables": [{"id": "T", "zone_id": "z", "capacity": 2}],
    }
    (tmp_path / "test-230-rerun" / "venue-configuration.json").write_text(
        json.dumps(configuration), encoding="utf-8"
    )
    inventory = _legacy_instances()
    for record in inventory:
        record["enabled"] = False
    (tmp_path / "test-230-rerun" / "rules-listing.json").write_text(
        json.dumps({"rules": inventory}), encoding="utf-8"
    )
    (tmp_path / "test-230-rerun" / "verdicts-rerun.json").write_text(
        json.dumps({"verdicts": [{"id": f"v{i}", "status": "PASS"}
                                 for i in range(29)]}), encoding="utf-8"
    )
    (tmp_path / "equivalence-cases.json").write_text(
        json.dumps({"cases": [{
            "name": "synthetic-manifest", "guest_file": "test-230/guests-216-control.csv",
            "expected_status": "feasible", "score": 0, "seated": 2,
        }]}), encoding="utf-8"
    )
    assert corpus_gate(tmp_path) == 1
