"""Build and load the benchmark's fixed set of bugs (mutants) for each design.

A candidate mutant is kept only if it
  1. compiles in Icarus Verilog and Verilator, and
  2. is caught by the human-written reference testbench without hanging
     (so it is a real, observable bug and not an equivalent mutant).
The kept set is stored in bench/mutants/<design>.json so every benchmark run
uses exactly the same bugs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .design import Design
from .mutate import Mutant, sample
from .sim import run_cocotb


def compiles(path: Path, top: str) -> tuple[bool, str]:
    r = subprocess.run(["iverilog", "-g2012", "-s", top, "-o", "/dev/null", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-800:]
    if shutil.which("verilator"):
        r = subprocess.run(["verilator", "--lint-only", "-Wno-fatal", "-Wno-lint", "-Wno-style",
                            "--top-module", top, str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            return False, r.stderr[-800:]
    return True, ""


def write_variant(design: Design, mutant: Mutant | None, out_dir: Path) -> list[Path]:
    """Write the design's sources with ``mutant`` applied (or unchanged) into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for src in design.sources:
        text = src.read_text()
        if mutant is not None and Path(mutant.file).name == src.name:
            text = mutant.apply(text)
        dst = out_dir / src.name
        dst.write_text(text)
        paths.append(dst)
    return paths


def build_mutant_set(design: Design, work: Path, n_select: int = 12, seed: int = 2027,
                     log=print) -> dict:
    src = design.sources[0]
    cands = sample(src.read_text(), src.name, 0, seed=seed)
    golden = run_cocotb(design.sources, design.top, design.ref_test, work / "golden", design.parameters)
    if not golden.passed:
        raise RuntimeError(f"{design.name}: reference testbench fails on the golden RTL:\n{golden.log[-2000:]}")
    budget = max(30.0, golden.seconds * 8)
    records = []
    selected = 0
    for k, m in enumerate(cands):
        m.id = f"{design.name}_m{k:03d}"
        vdir = work / "variants" / m.id
        paths = write_variant(design, m, vdir)
        ok, err = compiles(paths[0], design.top)
        rec = m.to_dict()
        if not ok:
            rec["status"] = "no_compile"
        else:
            r = run_cocotb(paths, design.top, design.ref_test, work / "sim", design.parameters, timeout=budget)
            rec["status"] = {"pass": "survived", "timeout": "hang"}.get(r.status, "killed")
            if r.status in ("tb_error", "rtl_error"):
                rec["status"] = "error"
        rec["selected"] = rec["status"] == "killed" and selected < n_select
        selected += rec["selected"]
        records.append(rec)
        shutil.rmtree(vdir, ignore_errors=True)
        log(f"  {m.id} {rec['status']:10s} {'*' if rec['selected'] else ' '} line {m.line}: {m.description}")
    return {"design": design.name, "file": src.name, "seed": seed, "mutants": records}


def load_mutants(bench_dir: Path, design: Design, selected_only: bool = True) -> list[Mutant]:
    f = Path(bench_dir) / "mutants" / f"{design.name}.json"
    data = json.loads(f.read_text())
    out = []
    for r in data["mutants"]:
        if selected_only and not r.get("selected"):
            continue
        out.append(Mutant(r["id"], r["file"], r["line"], r["operator"], r["original"], r["mutated"],
                          r["description"]))
    return out
