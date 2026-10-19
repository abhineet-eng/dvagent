"""End-to-end tests of the agent loops and the benchmark pipeline with a scripted LLM."""
import json
import shutil
from pathlib import Path

import pytest

from dvagent.agent import AgentConfig, DebugAgent, VerifyAgent
from dvagent.bench import run_bench
from dvagent.design import load_design
from dvagent.llm import LLM
from dvagent.mutants import load_mutants, write_variant
from dvagent.report import write_report
from dvagent.sim import failure_report, run_cocotb
from scripted import ScriptedLLM

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
needs_verilator = pytest.mark.skipif(shutil.which("verilator") is None, reason="needs Verilator")


def scripted(design, mutants=None, transcript=None):
    s = ScriptedLLM(design, mutants)
    return s, LLM(provider="script", model="scripted", _backend=s, transcript=transcript)


@needs_verilator
def test_verify_loop_repairs_and_closes_coverage(tmp_path):
    d = load_design(BENCH / "designs" / "uart_tx")
    s, llm = scripted(d, transcript=tmp_path / "t.jsonl")
    res = VerifyAgent(d, llm, tmp_path, AgentConfig(trust_rtl=True)).run()
    # draft with a syntax error -> false design blame (rejected) -> partial fix -> coverage closure
    assert s.calls == ["generate", "fix", "fix", "coverage"]
    assert res.false_alarms == 1
    assert res.passed and res.coverage == 100.0
    assert res.snapshots == {"single": "tb_00.py", "feedback": "tb_01.py", "final": "tb_02.py"}
    assert (tmp_path / "test_uart_tx.py").read_text() == d.ref_test.read_text()
    assert len((tmp_path / "t.jsonl").read_text().splitlines()) == 4


def test_untrusted_design_blame_stops_with_bug_report(tmp_path):
    d = load_design(BENCH / "designs" / "crc8")
    s, llm = scripted(d)
    res = VerifyAgent(d, llm, tmp_path, AgentConfig(coverage=False, trust_rtl=False)).run()
    assert res.design_bug and res.design_bug["blame"] == "design"
    assert not res.passed


def test_debug_agent_fixes_injected_bug(tmp_path):
    d = load_design(BENCH / "designs" / "sync_fifo")
    muts = load_mutants(BENCH, d)
    m = muts[0]
    buggy = write_variant(d, m, tmp_path / "bug")[0]
    res = run_cocotb([buggy], d.top, d.ref_test, tmp_path / "sim", d.parameters)
    assert not res.passed
    s, llm = scripted(d, muts)
    dres = DebugAgent(d, llm, tmp_path / "dbg", AgentConfig()).run(m.id, buggy, d.ref_test, failure_report(res))
    assert dres.fixed_self_check
    assert dres.attempts[0].bug_line == m.line


@needs_verilator
def test_benchmark_pipeline_and_report(tmp_path):
    d = load_design(BENCH / "designs" / "crc8")
    s, llm = scripted(d, load_mutants(BENCH, d), tmp_path / "transcript.jsonl")
    meta = run_bench(BENCH, tmp_path, llm, AgentConfig(), ["crc8"], debug_per_design=2, log=lambda *_: None)
    assert meta["stopped"] is None
    ev = json.loads((tmp_path / "crc8" / "eval.json").read_text())
    assert ev["snapshots"]["single"]["mutation_score"] == 0.0       # the draft did not even run
    assert ev["snapshots"]["final"]["mutation_score"] > 50.0
    dbg = json.loads((tmp_path / "crc8" / "debug.json").read_text())
    assert len(dbg) == 2 and all(c["fixed"] and c["localized_first"] for c in dbg)
    summary = write_report(tmp_path)
    assert summary["overall"]["debug_fix"] == 2
    for f in ("summary.md", "summary.json", "report.html", "chart_light.png", "chart_dark.png"):
        assert (tmp_path / f).exists()
    # resuming does no new LLM work
    calls = len(s.calls)
    run_bench(BENCH, tmp_path, llm, AgentConfig(), ["crc8"], debug_per_design=2, log=lambda *_: None)
    assert len(s.calls) == calls
