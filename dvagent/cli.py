"""Command-line interface: ``python -m dvagent <command>`` (or ``dvagent <command>``)."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"


def _llm(args, transcript: Path | None):
    from .llm import make_llm
    kw = {}
    if args.provider == "replay":
        kw["replay_file"] = args.replay
    if args.provider == "files":
        kw["files_dir"] = args.files_dir
    if getattr(args, "base_url", None):
        kw["base_url"] = args.base_url
    if getattr(args, "rpm", None) is not None:
        kw["rpm"] = args.rpm
    if getattr(args, "reasoning_effort", None):
        kw["reasoning_effort"] = args.reasoning_effort
    return make_llm(args.provider, args.model, transcript=transcript, **kw)


def _cfg(args):
    from .agent import AgentConfig
    return AgentConfig(max_llm_calls=args.max_calls, coverage=not args.no_coverage,
                       show_rtl=args.show_rtl, sim_timeout=args.sim_timeout)


def cmd_check(args):
    ok = True

    def line(name, good, detail):
        nonlocal ok
        ok &= good
        print(f"  [{'ok' if good else '!!'}] {name:12s} {detail}")

    print("DVAgent environment check")
    line("python", sys.version_info >= (3, 10), sys.version.split()[0])
    try:
        import cocotb
        line("cocotb", True, cocotb.__version__)
    except ImportError:
        line("cocotb", False, "not installed: pip install cocotb==1.9.2")
    for tool, flag in (("iverilog", "-V"), ("verilator", "--version")):
        path = shutil.which(tool)
        if path:
            out = subprocess.run([tool, flag], capture_output=True, text=True).stdout.splitlines()
            line(tool, True, (out[0] if out else path)[:60])
        else:
            line(tool, tool == "verilator", "not found" + (" (only needed for coverage)" if tool == "verilator" else ""))
    from .llm import PROVIDERS
    import os
    p = PROVIDERS.get(args.provider)
    if p and p["key_env"]:
        line("api key", bool(os.environ.get(p["key_env"])), f"{p['key_env']} " + ("set" if os.environ.get(p["key_env"]) else "NOT set"))
    return 0 if ok else 1


def cmd_models(args):
    llm = _llm(args, None)
    for m in llm.list_models():
        print(m)
    return 0


def cmd_verify(args):
    from .agent import VerifyAgent
    from .design import load_design
    d = load_design(args.design)
    out = Path(args.out or f"out/{d.name}")
    out.mkdir(parents=True, exist_ok=True)
    llm = _llm(args, out / "transcript.jsonl")
    res = VerifyAgent(d, llm, out, _cfg(args)).run()
    print()
    print(f"Testbench: {out / f'test_{d.top}.py'}")
    if res.design_bug:
        print("The agent believes the DESIGN has a bug:")
        print(json.dumps(res.design_bug, indent=2))
        return 2
    return 0 if res.passed else 1


def cmd_debug(args):
    from .agent import DebugAgent
    from .design import load_design
    from .sim import failure_report, run_cocotb
    d = load_design(args.design)
    if len(d.sources) != 1:
        print("debug currently supports single-file designs")
        return 1
    out = Path(args.out or f"out/{d.name}_debug")
    tb = Path(args.tb)
    res = run_cocotb(d.sources, d.top, tb, out / "sim", d.parameters, timeout=args.sim_timeout)
    print(res.summary())
    if res.passed:
        print("All tests pass: nothing to debug.")
        return 0
    llm = _llm(args, out / "transcript.jsonl")
    cfg = _cfg(args)
    dres = DebugAgent(d, llm, out, cfg).run("case", d.sources[0], tb, failure_report(res))
    for i, a in enumerate(dres.attempts, 1):
        print(f"\nAttempt {i}: line {a.bug_line} -> {a.self_check}\n  {a.explanation}")
        for e in a.edits:
            print(f"  line {e.get('line')}: {e.get('new_text')}")
    if dres.fixed_self_check:
        print(f"\nFixed RTL written to {dres.final.patched_file} (your source file was not changed).")
        return 0
    print("\nNo verified fix found.")
    return 1


def cmd_inject(args):
    """Copy a design with one bug from the benchmark set injected (for demos)."""
    from .design import load_design
    from .mutants import load_mutants, write_variant
    d = load_design(args.design)
    muts = {m.id: m for m in load_mutants(BENCH, d)}
    if args.mutant not in muts:
        print("available bugs:\n" + "\n".join(f"  {k}: line {m.line}, {m.description}" for k, m in muts.items()))
        return 1
    out = Path(args.out)
    shutil.copytree(d.root, out, dirs_exist_ok=True)
    write_variant(d, muts[args.mutant], out / "rtl")
    print(f"Wrote {out} with bug {args.mutant} injected (secret: line {muts[args.mutant].line}).")
    return 0


def cmd_mutants(args):
    from .design import bench_designs
    from .mutants import build_mutant_set
    for d in bench_designs(BENCH):
        if args.designs and d.name not in args.designs.split(","):
            continue
        t0 = time.time()
        data = build_mutant_set(d, Path(args.work) / d.name, n_select=args.per_design, log=lambda s: None)
        (BENCH / "mutants").mkdir(exist_ok=True)
        (BENCH / "mutants" / f"{d.name}.json").write_text(json.dumps(data, indent=1))
        from collections import Counter
        c = Counter(r["status"] for r in data["mutants"])
        print(f"{d.name:16s} {dict(c)}  ({time.time() - t0:.0f} s)")
    return 0


def cmd_bench(args):
    from .bench import run_bench
    from .report import write_report
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm = _llm(args, out / "transcript.jsonl")
    designs = args.designs.split(",") if args.designs else None
    meta = run_bench(BENCH, out, llm, _cfg(args), designs, args.debug_per_design)
    write_report(out)
    print()
    print((out / "summary.md").read_text())
    print(f"Report: {out / 'report.html'}")
    return 3 if meta.get("stopped") else 0


def cmd_report(args):
    from .report import update_readme, write_report
    write_report(Path(args.results))
    print((Path(args.results) / "summary.md").read_text())
    if args.readme:
        ok = update_readme(Path(args.readme), Path(args.results))
        print(f"README results section {'updated' if ok else 'NOT updated (markers missing)'}: {args.readme}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dvagent", description="LLM agent that writes, runs and debugs testbenches.")
    ap.add_argument("--version", action="version", version=f"dvagent {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def llm_opts(p):
        p.add_argument("--provider", default="gemini",
                       help="gemini | groq | openrouter | openai | anthropic | ollama | custom | replay | files")
        p.add_argument("--model", default=None, help="model id (default depends on the provider)")
        p.add_argument("--base-url", default=None, help="for --provider custom")
        p.add_argument("--rpm", type=float, default=None, help="max requests per minute")
        p.add_argument("--reasoning-effort", default=None, help="low | medium | high (if the model supports it)")
        p.add_argument("--replay", default=None, help="transcript.jsonl for --provider replay")
        p.add_argument("--files-dir", default="llm_io", help="folder for --provider files")

    def agent_opts(p):
        p.add_argument("--max-calls", type=int, default=8, help="LLM call budget for writing one testbench")
        p.add_argument("--no-coverage", action="store_true", help="skip Verilator coverage closure")
        p.add_argument("--show-rtl", action="store_true", help="let the agent read the RTL when writing tests")
        p.add_argument("--sim-timeout", type=float, default=240.0, help="seconds per simulation")

    p = sub.add_parser("check", help="check simulators, cocotb and the API key")
    p.add_argument("--provider", default="gemini")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("models", help="list the provider's models")
    llm_opts(p)
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("verify", help="write and refine a testbench for a design folder")
    p.add_argument("design", help="folder with spec.md and rtl/ (and optionally design.json)")
    p.add_argument("--out", default=None)
    llm_opts(p)
    agent_opts(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("debug", help="find and fix the RTL bug behind a failing testbench")
    p.add_argument("design")
    p.add_argument("--tb", required=True, help="cocotb testbench that fails on the design")
    p.add_argument("--out", default=None)
    llm_opts(p)
    agent_opts(p)
    p.set_defaults(func=cmd_debug)

    p = sub.add_parser("inject", help="copy a benchmark design with one known bug injected")
    p.add_argument("design")
    p.add_argument("--mutant", default="", help="bug id (run without it to list them)")
    p.add_argument("--out", default="buggy_design")
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("mutants", help="rebuild the benchmark's bug set (needs no LLM)")
    p.add_argument("--designs", default="")
    p.add_argument("--per-design", type=int, default=12)
    p.add_argument("--work", default="build/mutants")
    p.set_defaults(func=cmd_mutants)

    p = sub.add_parser("bench", help="run the full benchmark (resumable)")
    p.add_argument("--out", default="results/latest")
    p.add_argument("--designs", default="", help="comma-separated subset")
    p.add_argument("--debug-per-design", type=int, default=4)
    llm_opts(p)
    agent_opts(p)
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("report", help="rebuild summary.md, charts and report.html for a results folder")
    p.add_argument("results")
    p.add_argument("--readme", default=None, help="also rewrite the results section of this README")
    p.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    from .llm import LLMError
    try:
        return args.func(args)
    except LLMError as e:
        print(f"LLM error: {e}", file=sys.stderr)
        return 4
