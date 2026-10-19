"""Benchmark: how well does the agent verify and debug real designs?

For each design the agent writes and refines a testbench (VerifyAgent). Three
snapshots of its testbench are scored:

  single    the first draft, before any simulation feedback (= one-shot LLM)
  feedback  the first draft that passes on the correct design (after self-repair)
  final     after coverage closure

Each snapshot is run against the design's fixed set of injected bugs; the
mutation score is the share of bugs it catches. Then the agent debugs a sample
of the bugs its final testbench caught: it must name the faulty line and give
a fix, which is accepted only if the hidden reference testbench passes.
The run is resumable: finished work is stored and skipped on the next run.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Callable

from .agent import AgentConfig, DebugAgent, VerifyAgent, VerifyResult
from .design import Design, bench_designs
from .llm import LLM, LLMError, QuotaExhausted
from .mutants import load_mutants, write_variant
from .sim import failure_report, run_cocotb

SNAPSHOTS = ("single", "feedback", "final")


def _golden_tests(design: Design, tb: Path, work: Path, timeout: float) -> tuple[set[str], int, str, float]:
    res = run_cocotb(design.sources, design.top, tb, work, design.parameters, timeout=timeout)
    passing = {t.name for t in res.tests if t.passed}
    return passing, len(res.tests), res.status, res.seconds


def evaluate_snapshots(design: Design, vres: VerifyResult, ddir: Path, bench_dir: Path,
                       cfg: AgentConfig, log: Callable = print) -> dict:
    """Golden pass rate, coverage and mutation score of each testbench snapshot."""
    mutants = load_mutants(bench_dir, design)
    work = ddir / "eval"
    out: dict = {"mutants": [m.id for m in mutants], "snapshots": {}}
    variants = {}
    for m in mutants:
        variants[m.id] = write_variant(design, m, ddir / "variants" / m.id)
    done: dict[str, dict] = {}
    for snap in SNAPSHOTS:
        name = vres.snapshots.get(snap) or vres.snapshots.get("final")
        if name in done:                       # identical testbench: reuse the scores
            out["snapshots"][snap] = dict(done[name], same_as=done[name]["snapshot"])
            continue
        tb = ddir / "agent" / name
        t0 = time.time()
        passing, total, status, golden_secs = _golden_tests(design, tb, work, cfg.sim_timeout)
        cres = run_cocotb(design.sources, design.top, tb, work, design.parameters, coverage=True,
                          timeout=cfg.sim_timeout)
        cov = cres.coverage.percent if cres.coverage else None
        killed: dict[str, str] = {}
        budget = cfg.sim_timeout
        if passing:
            budget = min(cfg.sim_timeout, max(30.0, 10 * golden_secs))
            for m in mutants:
                r = run_cocotb(variants[m.id], design.top, tb, work, design.parameters, timeout=budget)
                got = {t.name: t.passed for t in r.tests}
                failing = [t for t in passing if not got.get(t, False)]
                if r.status == "timeout" or failing:
                    killed[m.id] = r.status
                    (work / "reports").mkdir(parents=True, exist_ok=True)
                    (work / "reports" / f"{snap}_{m.id}.txt").write_text(failure_report(r))
        rec = {
            "snapshot": snap, "tb": name, "golden_status": status, "tests_total": total,
            "tests_passing": len(passing), "passing_tests": sorted(passing), "coverage": cov,
            "killed": killed, "mutation_score": round(100.0 * len(killed) / len(mutants), 2) if mutants else None,
            "seconds": round(time.time() - t0, 1),
        }
        out["snapshots"][snap] = rec
        done[name] = rec
        log(f"[{design.name}] {snap:8s}: golden {status} ({len(passing)}/{total} tests), "
            f"coverage {'n/a' if cov is None else f'{cov:.1f}%'}, caught {len(killed)}/{len(mutants)} bugs")
    return out


def _points_at(att, line: int) -> bool:
    """The attempt names the right line: its fix edits it, or (no usable fix) it reports it."""
    return line in att.edited_lines if att.edited_lines else att.bug_line == line


def debug_cases(design: Design, ddir: Path, bench_dir: Path, ev: dict, llm: LLM, cfg: AgentConfig,
                per_design: int, log: Callable = print) -> list[dict]:
    final = ev["snapshots"]["final"]
    mutants = {m.id: m for m in load_mutants(bench_dir, design)}
    caught = [mid for mid in ev["mutants"] if mid in final["killed"]][:per_design]
    tb = ddir / "agent" / final["tb"]
    required = set(final["passing_tests"])
    results = []
    dbg_dir = ddir / "debug"
    for mid in caught:
        rec_file = dbg_dir / f"{mid}.score.json"
        if rec_file.exists():
            results.append(json.loads(rec_file.read_text()))
            continue
        m = mutants[mid]
        buggy = ddir / "variants" / mid / Path(m.file).name
        src = final.get("same_as", "final")
        report = (ddir / "eval" / "reports" / f"{src}_{mid}.txt").read_text()
        if not buggy.exists():
            write_variant(design, m, ddir / "variants" / mid)
        agent = DebugAgent(design, llm, dbg_dir, cfg, log)
        res = agent.run(mid, buggy, tb, report, required)
        # ground truth: does the hidden reference testbench pass on the patched RTL?
        ref_ok = []
        for att in res.attempts:
            ok = False
            if att.patched_file and att.self_check in ("pass", "fail"):
                r = run_cocotb([Path(att.patched_file)], design.top, design.ref_test, dbg_dir / "refsim",
                               design.parameters, timeout=cfg.sim_timeout)
                ok = r.passed
            ref_ok.append(ok)
        first = res.attempts[0] if res.attempts else None
        rec = {
            "mutant": mid, "bug_line": m.line, "operator": m.operator, "description": m.description,
            "original": m.original.strip(), "mutated": m.mutated.strip(),
            "attempts": len(res.attempts),
            "localized_first": bool(first and _points_at(first, m.line)),
            "localized_any": any(_points_at(a, m.line) for a in res.attempts),
            "fixed_first": bool(ref_ok and ref_ok[0]),
            "fixed": bool(res.fixed_self_check and ref_ok and ref_ok[-1]),
            "self_check_pass": res.fixed_self_check,
            "predicted_lines": [a.edited_lines[0] if a.edited_lines else a.bug_line for a in res.attempts],
            "fixes": [[str(e.get("new_text", "")).strip() for e in a.edits] for a in res.attempts],
            "explanations": [a.explanation for a in res.attempts],
        }
        rec_file.write_text(json.dumps(rec, indent=1))
        results.append(rec)
    return results


def run_bench(bench_dir: Path, out_dir: Path, llm: LLM, cfg: AgentConfig, designs: list[str] | None = None,
              debug_per_design: int = 4, log: Callable = print) -> dict:
    bench_dir, out_dir = Path(bench_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg.trust_rtl = True
    meta_file = out_dir / "run.json"
    if meta_file.exists():
        old = json.loads(meta_file.read_text())
        if old.get("model") != llm.model:
            raise SystemExit(f"{out_dir} holds results of model '{old.get('model')}', not '{llm.model}'. "
                             "Use a new results folder (run_name) for a different model.")
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {
        "provider": llm.provider, "model": llm.model, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": cfg.__dict__, "debug_per_design": debug_per_design}
    meta_file.write_text(json.dumps(meta, indent=1))
    all_designs = bench_designs(bench_dir)
    chosen = [d for d in all_designs if not designs or d.name in designs]
    stopped = None
    for d in chosen:
        ddir = out_dir / d.name
        try:
            vfile = ddir / "agent" / "verify.json"
            if vfile.exists():
                vres = VerifyResult.from_dict(json.loads(vfile.read_text()))
            else:
                shutil.rmtree(ddir / "agent", ignore_errors=True)
                vres = VerifyAgent(d, llm, ddir / "agent", cfg, log).run()
            efile = ddir / "eval.json"
            if efile.exists():
                ev = json.loads(efile.read_text())
            else:
                ev = evaluate_snapshots(d, vres, ddir, bench_dir, cfg, log)
                efile.write_text(json.dumps(ev, indent=1))
            dbg = debug_cases(d, ddir, bench_dir, ev, llm, cfg, debug_per_design, log)
            (ddir / "debug.json").write_text(json.dumps(dbg, indent=1))
        except QuotaExhausted as e:
            stopped = f"LLM quota exhausted while working on {d.name}: {str(e)[:400]}"
            log("STOPPED: " + stopped + "\nRun the same command again later to resume.")
            break
        except LLMError as e:
            stopped = f"LLM error while working on {d.name}: {str(e)[:600]}"
            log("STOPPED: " + stopped + "\nRun the same command again later to resume.")
            break
        shutil.rmtree(ddir / "variants", ignore_errors=True)
        for sub in ("eval", "agent", "debug"):
            shutil.rmtree(ddir / sub / "sim", ignore_errors=True)
            shutil.rmtree(ddir / sub / "builds", ignore_errors=True)
            shutil.rmtree(ddir / sub / "runs", ignore_errors=True)
            shutil.rmtree(ddir / sub / "refsim", ignore_errors=True)
    meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta["stopped"] = stopped
    meta_file.write_text(json.dumps(meta, indent=1))
    return meta
