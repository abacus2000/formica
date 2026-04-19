"""Enforcement: Formica code never calls provisioning APIs."""

import pathlib
import re

FORBIDDEN = [
    r"\brun_instances\b",
    r"\bcreate_fleet\b",
    r"\bcreate_launch_template\b",
    r"UpdateNodegroupConfig",
    r"CreateNodegroup",
    r"SetDesiredCapacity",
    r"UpdateAutoScalingGroup",
]

ROOT = pathlib.Path(__file__).resolve().parents[2] / "formica"


def test_no_provisioning_calls_in_source():
    bad: list[str] = []
    for py in ROOT.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for pat in FORBIDDEN:
            if re.search(pat, text):
                bad.append(f"{py}: {pat}")
    assert not bad, "provisioning API references found: " + "; ".join(bad)
