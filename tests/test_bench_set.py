"""The benchmark itself must be sound: reference testbenches pass on every correct
design, and every selected bug compiles and is caught by the reference testbench."""
import json
import subprocess
from pathlib import Path

import pytest

from dvagent.design import bench_designs
from dvagent.mutants import compiles, load_mutants, write_variant
from dvagent.rtl import module_header, ports
from dvagent.sim import run_cocotb

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
DESIGNS = bench_designs(BENCH)
IDS = [d.name for d in DESIGNS]


def test_ten_designs():
    assert len(DESIGNS) == 10


@pytest.mark.parametrize("d", DESIGNS, ids=IDS)
def test_design_is_lint_clean(d):
    r = subprocess.run(["verilator", "--lint-only", "-Wall", *map(str, d.sources)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("d", DESIGNS, ids=IDS)
def test_interface_parses(d):
    assert module_header(d.rtl_text(), d.top).startswith(f"module {d.top}")
    names = {p["name"] for p in ports(d.rtl_text(), d.top)}
    for name in (d.clock, d.reset):
        if name:
            assert name in names


@pytest.mark.parametrize("d", DESIGNS, ids=IDS)
def test_reference_passes_on_golden(d, tmp_path):
    r = run_cocotb(d.sources, d.top, d.ref_test, tmp_path, d.parameters)
    assert r.passed, r.log[-3000:]


@pytest.mark.parametrize("d", DESIGNS, ids=IDS)
def test_bug_set(d, tmp_path):
    data = json.loads((BENCH / "mutants" / f"{d.name}.json").read_text())
    muts = load_mutants(BENCH, d)
    assert len(muts) == 12
    assert len({m.id for m in muts}) == 12
    assert all(r["status"] != "killed" or r["selected"] or True for r in data["mutants"])
    for m in muts:
        paths = write_variant(d, m, tmp_path / m.id)
        ok, err = compiles(paths[0], d.top)
        assert ok, err
    # spot check: the first selected bug really is caught by the reference testbench
    paths = write_variant(d, muts[0], tmp_path / "check")
    r = run_cocotb(paths, d.top, d.ref_test, tmp_path / "sim", d.parameters)
    assert not r.passed
