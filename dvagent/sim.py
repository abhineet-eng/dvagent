"""Run cocotb testbenches against RTL in a sandboxed child process.

Every run gets a wall-clock timeout, a parsed per-test result, and a condensed
log that keeps what a person (or an LLM) needs to debug a failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .coverage import Coverage, parse_coverage_dat


@dataclass
class TestOutcome:
    name: str
    passed: bool
    message: str = ""


@dataclass
class SimResult:
    status: str                    # pass | fail | tb_error | rtl_error | timeout | no_tests
    tests: list[TestOutcome] = field(default_factory=list)
    log: str = ""
    seconds: float = 0.0
    coverage: Coverage | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def n_pass(self) -> int:
        return sum(t.passed for t in self.tests)

    @property
    def n_fail(self) -> int:
        return sum(not t.passed for t in self.tests)

    def summary(self) -> str:
        s = f"{self.status}: {self.n_pass} passed, {self.n_fail} failed ({self.seconds:.1f} s)"
        if self.coverage is not None:
            s += f", code coverage {self.coverage.percent:.1f}% ({self.coverage.hit}/{self.coverage.total})"
        return s

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "tests": [{"name": t.name, "passed": t.passed, "message": t.message[:500]} for t in self.tests],
            "seconds": round(self.seconds, 2),
            "coverage": self.coverage.to_dict() if self.coverage else None,
        }


def _hash_files(paths, extra: str = "") -> str:
    h = hashlib.sha1(extra.encode())
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:12]


def _kill_tree(proc: subprocess.Popen):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def python_syntax_error(code: str, filename: str = "test.py") -> str | None:
    try:
        compile(code, filename, "exec")
    except SyntaxError as e:
        line = (e.text or "").rstrip()
        return f"SyntaxError: {e.msg} (line {e.lineno})\n    {line}"
    return None


_RUNNING = re.compile(r"\brunning (\S+) \(\d+/\d+\)")
_RESULT = re.compile(r"\b(\S+) (passed|failed)\b")
_NOISE = re.compile(r"^[\s^~]+$|^\s*\+\s+where |UserWarning: Python runners|from cocotb.runner import|^\*\*|^INFO: Results file")


def _clean(line: str) -> str:
    line = re.sub(r'File "[^"]*/([^/"]+)"', r'File "\1"', line.rstrip())
    line = re.sub(r"^\s*-?\d+(?:\.\d+)?\w*\s+(INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+", r"\1 ", line)
    return line.strip()


def condense_log(log: str, test_file: str | None = None, max_chars: int = 3500) -> str:
    """Per failing test: the traceback of the first failure, the assertion message of the
    others, and the testbench's own log lines just before each failure."""
    lines = [ln for ln in log.splitlines() if ln.strip() and not _NOISE.search(ln)]
    out: list[str] = []
    current = None
    context: list[str] = []
    passed: list[str] = []
    detail_given = False
    i = 0
    pre: list[str] = []
    while i < len(lines):
        ln = lines[i]
        m = _RUNNING.search(ln)
        if m:
            current, context = m.group(1), []
            i += 1
            continue
        r = _RESULT.search(ln)
        if r and current and r.group(1) == current:
            if r.group(2) == "passed":
                passed.append(current)
                i += 1
                continue
            block = []
            i += 1
            while i < len(lines) and not _RUNNING.search(lines[i]):
                block.append(_clean(lines[i]))
                i += 1
            exc = [b for b in block if re.match(r"^\w*(Error|Exception|Timeout\w*)\b", b) or b.startswith("assert ")]
            out.append(f"FAILED {current}")
            if context:
                out += ["  testbench log before the failure:"] + [f"    {c}" for c in context[-6:]]
            if not detail_given:
                out += [f"  {b}" for b in block[:30]]
                detail_given = True
            else:
                out += [f"  {b}" for b in (exc[:2] or block[-2:])]
            current = None
            continue
        if current is None:
            pre.append(_clean(ln))
        elif "cocotb.regression" not in ln:
            context.append(_clean(ln))
        i += 1
    head = []
    if any("Traceback" in p or "Error" in p for p in pre):
        head = ["output before the tests ran:"] + [f"  {p}" for p in pre[-25:]]
    if current is not None:          # the simulation stopped in the middle of a test
        head += [f"test {current} did not finish; last testbench output:"] + [f"  {c}" for c in context[-15:]]
    text = "\n".join(head + out)
    if passed:
        text += "\npassed: " + ", ".join(passed)
    if not text.strip():
        text = "\n".join(_clean(x) for x in lines[-40:])
    if len(text) > max_chars:
        text = text[: max_chars * 2 // 3] + "\n... (truncated) ...\n" + text[-max_chars // 3:]
    return text


def _parse_results(xml_path: Path) -> list[TestOutcome]:
    out = []
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError):
        return out
    for tc in root.iter("testcase"):
        name = tc.get("name", "?")
        fail = tc.find("failure")
        if fail is None:
            fail = tc.find("error")
        if tc.find("skipped") is not None:
            continue
        msg = ""
        if fail is not None:
            msg = (fail.get("message") or "") + "\n" + (fail.text or "")
        out.append(TestOutcome(name, fail is None, msg.strip()))
    return out


def run_cocotb(
    sources: list[Path],
    top: str,
    test_file: Path,
    work_dir: Path,
    parameters: dict | None = None,
    simulator: str = "icarus",
    coverage: bool = False,
    timeout: float = 240.0,
    seed: int = 12345,
) -> SimResult:
    """Build ``sources`` and run every @cocotb.test in ``test_file``."""
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    sources = [Path(s).resolve() for s in sources]
    test_file = Path(test_file).resolve()
    if coverage:
        simulator = "verilator"

    code = test_file.read_text()
    syn = python_syntax_error(code, test_file.name)
    if syn:
        return SimResult("tb_error", log=syn)
    if "@cocotb.test" not in code:
        return SimResult("no_tests", log="The file defines no @cocotb.test() functions. If the previous reply was "
                                         "cut off by the output length limit, write a more compact testbench "
                                         "(shared helpers, fewer comments).")

    tag = _hash_files(sources, json.dumps([top, parameters or {}, simulator, coverage], sort_keys=True))
    build_dir = work_dir / "builds" / f"{simulator}{'_cov' if coverage else ''}_{tag}"
    run_id = f"run_{int(time.time() * 1000) % 10**10}_{os.getpid()}"
    test_dir = work_dir / "runs" / run_id
    tb_dir = test_dir / "tb"
    tb_dir.mkdir(parents=True, exist_ok=True)
    module = "test_" + re.sub(r"\W", "_", test_file.stem.removeprefix("test_"))
    shutil.copy(test_file, tb_dir / f"{module}.py")

    cfg = {
        "simulator": simulator, "sources": [str(s) for s in sources], "top": top,
        "parameters": parameters or {}, "build_dir": str(build_dir), "test_dir": str(test_dir),
        "test_module": module, "test_module_dir": str(tb_dir), "seed": seed, "coverage": coverage,
    }
    cfg_file = test_dir / "config.json"
    cfg_file.write_text(json.dumps(cfg, indent=1))

    t0 = time.time()
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)   # cocotb's runner would rename results.xml after it
    env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parent.parent), env.get("PYTHONPATH", "")])
    proc = subprocess.Popen(
        [sys.executable, "-m", "dvagent.simchild", str(cfg_file)],
        cwd=test_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
        start_new_session=True, text=True, errors="replace",
    )
    try:
        log, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        log, _ = proc.communicate()
        timed_out = True
    seconds = time.time() - t0
    (test_dir / "sim.log").write_text(log or "")

    built = (build_dir / ".dvagent_built").exists()
    tests = _parse_results(test_dir / "results.xml")
    cov = None
    if coverage and (test_dir / "coverage.dat").exists():
        cov = parse_coverage_dat(test_dir / "coverage.dat", [str(s) for s in sources])

    if timed_out:
        status = "timeout"
        log = (log or "") + (f"\nTIMEOUT: the simulation did not finish within {timeout:.0f} s of wall-clock time. "
                             "A test is probably waiting forever, e.g. `await RisingEdge(dut.x)` for a signal "
                             "that never changes, or a while-loop that never exits.")
    elif not built:
        status = "rtl_error"
    elif not tests:
        status = "tb_error"
    elif all(t.passed for t in tests):
        status = "pass"
    else:
        status = "fail"
    return SimResult(status, tests, log or "", seconds, cov)


def failure_report(res: SimResult, max_chars: int = 3500) -> str:
    """Text describing why a run did not pass, for feedback to the agent."""
    return res.summary() + "\n" + condense_log(res.log, max_chars=max_chars)
