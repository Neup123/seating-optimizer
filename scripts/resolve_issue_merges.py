#!/usr/bin/env python3
"""Resolve ONLY reviewed conflict hunks in the isolated integration branch.

Never call on main. No generic "ours"/"theirs" strategy: each hunk has an
explicit semantic reconciliation. Unexpected paths or hunk shapes fail closed.
The caller commits the resolved merge only after all checks pass.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


EXPECTED = {
    114: {"tests/ui/visual.test.mjs"},
    119: {
        "src/seating_optimizer/api/web/app.js",
        "src/seating_optimizer/generic_cp.py",
        "src/seating_optimizer/generic_solver.py",
        "src/seating_optimizer/importer.py",
        "src/seating_optimizer/models.py",
        "src/seating_optimizer/solver.py",
    },
    116: {"src/seating_optimizer/api/web/app.js"},
    124: {"src/seating_optimizer/api/web/app.js"},
}
CONFLICT = re.compile(
    r"(?ms)^<<<<<<< HEAD\n(?P<ours>.*?)^=======\n(?P<theirs>.*?)^>>>>>>> [^\n]+\n"
)


def reconcile(pr: int, path: str, ours: str, theirs: str, ordinal: int) -> str:
    if pr == 114 and path.endswith("tests/ui/visual.test.mjs"):
        assert "hard-rule infeasibility" in ours and "table edits are validated" in theirs
        assert ordinal == 1
        # These are two independent test declarations with a shared final '});'.
        return ours + "});\n\n" + theirs

    if pr == 119:
        if path.endswith("/api/web/app.js"):
            assert "staleRules" in ours and "chairs needed" in theirs
            previous = 'result.guests.length + " guests from " + result.rows_imported +'
            next_text = ('result.guests.length + " guests (" +\n'
                         '          result.guests.filter(g => g.requires_chair !== false).length +\n'
                         '          " chairs needed) from " + result.rows_imported +')
            assert previous in ours
            return ours.replace(previous, next_text)
        if path.endswith("/generic_cp.py"):
            assert "admissible" in ours and "chairs_needed" in theirs
            assert "if len(members) > largest" in ours
            return ours.replace("if len(members) > largest", "if chairs_needed(members) > largest")
        if path.endswith("/generic_solver.py"):
            assert "validate_plan_lifecycle" in ours and "chairs_needed" in theirs
            return ours.replace("validate_plan_lifecycle,", "validate_plan_lifecycle, chairs_needed,")
        if path.endswith("/importer.py"):
            assert "_stable_registration_identity" in ours
            assert "lap_value" in theirs and "group_id = str(" in theirs
            lap_logic = theirs[:theirs.index("        group_id = str(")]
            return lap_logic + ours
        if path.endswith("/models.py"):
            assert 'split_mixing_penalty' in ours and 'def chairs_needed' in theirs
            assert 'Shape = Literal' in theirs
            return theirs[:theirs.index("Shape = Literal")] + ours
        if path.endswith("/solver.py"):
            if "validate_plan_lifecycle" in ours and "chairs_needed" in theirs:
                return ours.replace("validate_plan_lifecycle)", "validate_plan_lifecycle, chairs_needed)")
            assert "admissible_by_group" in ours and "adjacent_split" in theirs
            return ours.replace(
                "len(members) > max(tables[j].capacity for j in admissible_by_group[gid])",
                "chairs_needed(members) > max(tables[j].capacity for j in admissible_by_group[gid])"
            )

    if pr == 116 and path.endswith("/api/web/app.js"):
        if ordinal == 1:
            assert "nextFreeTablePosition" in ours and "syncDrawingMetadata" in theirs
            # The original closing brace was outside the conflict hunk.
            return ours + "}\n\n" + theirs
        assert ordinal == 2 and "validatedTables" in ours and "syncDrawingMetadata" in theirs
        # Keep server-validated autosave; re-synchronize canonical metadata only
        # after the table/drawing pair has been accepted.
        return ours.replace(
            "Object.assign(drawing,proposedDrawing);",
            "Object.assign(drawing,proposedDrawing);\n          syncDrawingMetadata(state.tables, state.layout);"
        )

    if pr == 124 and path.endswith("/api/web/app.js"):
        assert "ruleQuery" in ours and "planStale" in theirs
        assert '"plan", "cardsPerPage"' in ours
        return ours.replace('"plan", "cardsPerPage"', '"plan", "lastGoodPlan", "planStale", "cardsPerPage"')

    raise AssertionError(f"Unreviewed merge conflict: PR #{pr} {path} hunk {ordinal}")


def main() -> int:
    pr = int(sys.argv[1])
    assert pr in EXPECTED, f"PR #{pr} has no approved conflict resolution contract"
    files = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=U"], text=True
    ).splitlines()
    assert set(files) == EXPECTED[pr], (
        f"Unexpected unmerged paths for #{pr}: {sorted(files)} != {sorted(EXPECTED[pr])}"
    )
    for path in files:
        original = Path(path).read_text(encoding="utf-8")
        count = 0

        def resolve_match(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return reconcile(pr, path, match["ours"], match["theirs"], count)

        rewritten = CONFLICT.sub(resolve_match, original)
        if pr == 119 and path.endswith("/solver.py"):
            rewritten = rewritten.replace(
                "len(members) > max(tables[j].capacity for j in admissible_by_group[gid])",
                "chairs_needed(members) > max(tables[j].capacity for j in admissible_by_group[gid])"
            )
        assert count >= 1, f"No recognized conflict markers in {path}"
        assert not re.search(r"(?m)^(<<<<<<< |=======|>>>>>>> )", rewritten), (
            f"Conflict markers remain in {path}"
        )
        if pr == 119 and path.endswith("/solver.py"):
            # Full eligibility check must use chair occupancy, not person count.
            assert "chairs_needed(members) > max(tables[j].capacity" in rewritten
        Path(path).write_text(rewritten, encoding="utf-8")
        subprocess.run(["git", "add", "--", path], check=True)
        print(f"PR #{pr}: reconciled {path} ({count} checked hunk(s))")
    if subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=U"], text=True):
        raise AssertionError("Unmerged index entries remain")
    subprocess.run(["git", "diff", "--cached", "--check"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
