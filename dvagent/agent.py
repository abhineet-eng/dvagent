"""The DVAgent loops: testbench generation with self-repair and coverage closure,
and RTL debugging with verified fixes."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import prompts
from .design import Design
from .extract import extract_json, extract_python
from .llm import LLM, Usage
from .mutants import compiles
from .sim import SimResult, failure_report, run_cocotb


@dataclass
class AgentConfig:
    max_llm_calls: int = 8          # budget for the testbench-generation phase
    coverage: bool = True           # close RTL line/branch coverage with Verilator
    coverage_target: float = 100.0
    max_coverage_rounds: int = 3
    show_rtl: bool = False          # give the full RTL (not just the interface) when writing tests
    trust_rtl: bool = False         # benchmark mode: the RTL is known-good, design blame is rejected
    sim_timeout: float = 240.0
    debug_attempts: int = 3


@dataclass
class Step:
    index: int
    kind: str                       # generate | fix | coverage
    tb_file: str
    sim: dict | None = None
    coverage: dict | None = None
    blame: str | None = None
    root_cause: str | None = None
    note: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class VerifyResult:
    design: str
    steps: list[Step] = field(default_factory=list)
    snapshots: dict = field(default_factory=dict)   # single | feedback | final -> tb file
    passed: bool = False
    coverage: float | None = None
    design_bug: dict | None = None
    false_alarms: int = 0
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["steps"] = [s.__dict__ for s in self.steps]
        return d

    @staticmethod
    def from_dict(d: dict) -> "VerifyResult":
        r = VerifyResult(d["design"])
        for k, v in d.items():
            if k != "steps":
                setattr(r, k, v)
        r.steps = [Step(**s) for s in d.get("steps", [])]
        return r


def _short(res: SimResult) -> str:
    failed = [t.name for t in res.tests if not t.passed]
    s = res.summary()
    if failed:
        s += " [failing: " + ", ".join(failed[:4]) + (" ..." if len(failed) > 4 else "") + "]"
    return s


class VerifyAgent:
    """Write a testbench from the spec, run it, repair it, close coverage."""

    def __init__(self, design: Design, llm: LLM, out_dir: Path, cfg: AgentConfig | None = None,
                 log: Callable[[str], None] = print, sources: list[Path] | None = None):
        self.d = design
        self.llm = llm
        self.out = Path(out_dir)
        self.cfg = cfg or AgentConfig()
        self.log = log
        self.sources = sources or design.sources
        self.work = self.out / "sim"
        self.out.mkdir(parents=True, exist_ok=True)

    def _ask(self, messages, tag) -> tuple[str, Usage]:
        before = Usage(**{k: getattr(self.llm.usage, k) for k in ("calls", "prompt_tokens",
                                                                  "completion_tokens", "seconds")})
        reply = self.llm.complete(messages, tag=f"{self.d.name}:{tag}")
        u = self.llm.usage
        return reply.text, Usage(u.calls - before.calls, u.prompt_tokens - before.prompt_tokens,
                                 u.completion_tokens - before.completion_tokens, u.seconds - before.seconds)

    def _save_tb(self, n: int, code: str) -> Path:
        p = self.out / f"tb_{n:02d}.py"
        p.write_text(code)
        return p

    def _sim(self, tb: Path, coverage: bool = False) -> SimResult:
        return run_cocotb(self.sources, self.d.top, tb, self.work, self.d.parameters,
                          coverage=coverage, timeout=self.cfg.sim_timeout)

    def run(self) -> VerifyResult:
        t0 = time.time()
        cfg = self.cfg
        result = VerifyResult(self.d.name)
        start_calls = self.llm.usage.calls
        usage0 = self.llm.usage.to_dict()

        def calls_used():
            return self.llm.usage.calls - start_calls

        # 1. first draft, straight from the spec
        self.log(f"[{self.d.name}] writing a testbench from the spec")
        text, u = self._ask(prompts.generate(self.d, cfg.show_rtl), "generate")
        code = extract_python(text)
        if code is None:
            text, u2 = self._ask(prompts.generate(self.d, cfg.show_rtl) + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "Your reply contained no ```python code block. "
                                            "Reply with the complete testbench file in one ```python block."}],
                "generate-retry")
            u.add(u2)
            code = extract_python(text) or "# the model returned no code\n"
        n = 0
        tb = self._save_tb(n, code)
        result.steps.append(Step(n, "generate", tb.name, usage=u.to_dict()))
        result.snapshots["single"] = tb.name

        history: list[str] = []
        best: tuple[float, str] | None = None        # (coverage, tb file) of the best passing testbench
        last_cov: float | None = None
        cov_rounds = 0
        stall = 0
        reviewer_note = ""
        res: SimResult | None = None
        need_sim = True

        while True:
            step = result.steps[-1]
            if need_sim:
                res = self._sim(tb)
                step.sim = res.to_dict()
                self.log(f"[{self.d.name}] step {n} ({step.kind}): {_short(res)}")
            need_sim = True

            if res.passed:
                result.snapshots.setdefault("feedback", tb.name)
                if not cfg.coverage:
                    best = (0.0, tb.name)
                    break
                cres = self._sim(tb, coverage=True)
                if cres.coverage is None:
                    step.note = f"coverage run: {cres.status}"
                    best = best or (0.0, tb.name)
                    break
                cov = cres.coverage
                step.coverage = cov.to_dict()
                if cres.status != "pass":
                    step.note = f"passes in Icarus but {cres.status} in Verilator"
                self.log(f"[{self.d.name}]   coverage {cov.percent:.1f}% ({cov.hit}/{cov.total})")
                if best is None or cov.percent >= best[0]:
                    best = (cov.percent, tb.name)
                if last_cov is not None and cov.percent <= last_cov:
                    stall += 1
                last_cov = max(cov.percent, last_cov or 0.0)
                if (cov.percent >= cfg.coverage_target or cov_rounds >= cfg.max_coverage_rounds
                        or stall >= 2 or calls_used() >= cfg.max_llm_calls):
                    break
                cov_rounds += 1
                text, u = self._ask(prompts.coverage(self.d, tb.read_text(), cov.percent,
                                                     cov.describe_missed(), cfg.show_rtl), "coverage")
                code = extract_python(text)
                if code is None:
                    result.steps.append(Step(n, "coverage", tb.name, note="no code in reply", usage=u.to_dict()))
                    break
                n += 1
                tb = self._save_tb(n, code)
                result.steps.append(Step(n, "coverage", tb.name, usage=u.to_dict()))
                continue

            # the testbench failed: triage and repair
            if calls_used() >= cfg.max_llm_calls:
                break
            report = failure_report(res)
            text, u = self._ask(prompts.fix(self.d, tb.read_text(), report, history, cfg.show_rtl,
                                            reviewer_note), "fix")
            verdict = extract_json(text) or {}
            blame = str(verdict.get("blame", "testbench")).lower()
            cause = str(verdict.get("root_cause", ""))[:300]
            code = extract_python(text)
            if blame == "design" and code is None:
                if cfg.trust_rtl:
                    result.false_alarms += 1
                    reviewer_note = ("A reviewer checked your bug report against the specification and rejected "
                                     "it: this design is signed off and correct, so the mismatch comes from the "
                                     "testbench. Re-read the specification carefully (exact cycle timing, reset "
                                     "values, priorities, corner cases) and fix the testbench.")
                    history.append(f"blamed the design ({cause}); the reviewer rejected that")
                    result.steps.append(Step(n, "fix", tb.name, blame="design", root_cause=cause,
                                             note="design blamed; rejected by reviewer", usage=u.to_dict()))
                    need_sim = False
                    continue
                result.design_bug = verdict
                result.steps.append(Step(n, "fix", tb.name, blame="design", root_cause=cause,
                                         note="agent reports a design bug", usage=u.to_dict()))
                self.log(f"[{self.d.name}] agent reports a DESIGN BUG: {cause}")
                break
            reviewer_note = ""
            if code is None:
                history.append(f"{_short(res)} -> reply had no code")
                result.steps.append(Step(n, "fix", tb.name, blame=blame, root_cause=cause,
                                         note="no code in reply", usage=u.to_dict()))
                need_sim = False
                continue
            history.append(f"{_short(res)} -> diagnosed as {blame} issue: {cause}")
            n += 1
            tb = self._save_tb(n, code)
            result.steps.append(Step(n, "fix", tb.name, blame=blame, root_cause=cause, usage=u.to_dict()))

        result.snapshots["final"] = best[1] if best else tb.name
        result.passed = best is not None
        result.coverage = best[0] if best and cfg.coverage else None
        final = self.out / result.snapshots["final"]
        (self.out / f"test_{self.d.top}.py").write_text(final.read_text())
        u1 = self.llm.usage.to_dict()
        result.usage = {k: round(u1[k] - usage0[k], 1) for k in u1}
        result.seconds = round(time.time() - t0, 1)
        (self.out / "verify.json").write_text(json.dumps(result.to_dict(), indent=1))
        self.log(f"[{self.d.name}] done: {'PASS' if result.passed else 'no passing testbench'}"
                 + (f", coverage {result.coverage:.1f}%" if result.coverage is not None else "")
                 + f", {result.usage['calls']} LLM calls")
        return result


# ---------------------------------------------------------------------------- debugging
@dataclass
class DebugAttempt:
    bug_line: int | None
    explanation: str
    edits: list[dict]
    applied: bool
    self_check: str                 # pass | fail | invalid | no_compile
    patched_file: str | None = None
    usage: dict = field(default_factory=dict)
    edited_lines: list[int] = field(default_factory=list)


@dataclass
class DebugResult:
    case: str
    attempts: list[DebugAttempt] = field(default_factory=list)
    fixed_self_check: bool = False

    @property
    def final(self) -> DebugAttempt | None:
        return self.attempts[-1] if self.attempts else None

    def to_dict(self) -> dict:
        return {"case": self.case, "fixed_self_check": self.fixed_self_check,
                "attempts": [a.__dict__ for a in self.attempts]}


def apply_edits(text: str, edits: list[dict]) -> tuple[str | None, list[int], str]:
    """Apply whole-line replacements. Each edit names a line number and, ideally, the line's
    current text; the text wins when the number is off (models often miscount lines).
    Returns (patched text or None, the lines actually changed, a problem description)."""
    lines = text.split("\n")
    changed: list[int] = []
    for e in edits:
        try:
            ln = int(e["line"])
            new = str(e["new_text"])
        except (KeyError, TypeError, ValueError):
            return None, changed, f"malformed fix entry {e}"
        if "\n" in new.strip("\n"):
            return None, changed, "new_text must be a single line"
        old = e.get("old_text")
        if old is not None and str(old).strip():
            old = str(old).strip()
            if not (1 <= ln <= len(lines) and lines[ln - 1].strip() == old):
                hits = [i + 1 for i, x in enumerate(lines) if x.strip() == old]
                if not hits:
                    return None, changed, f"old_text `{old}` does not appear in the file"
                ln = min(hits, key=lambda h: abs(h - ln))
        elif not 1 <= ln <= len(lines):
            return None, changed, f"line {ln} is outside the file"
        new = new.rstrip("\n")
        if new.strip() and not new[:1].isspace():
            indent = lines[ln - 1][: len(lines[ln - 1]) - len(lines[ln - 1].lstrip())]
            new = indent + new
        lines[ln - 1] = new
        changed.append(ln)
    return "\n".join(lines), changed, ""


class DebugAgent:
    """Localise and fix an RTL bug exposed by a failing testbench, verifying every fix."""

    def __init__(self, design: Design, llm: LLM, out_dir: Path, cfg: AgentConfig | None = None,
                 log: Callable[[str], None] = print):
        self.d = design
        self.llm = llm
        self.out = Path(out_dir)
        self.cfg = cfg or AgentConfig()
        self.log = log

    def run(self, case: str, buggy_file: Path, tb_file: Path, report: str,
            required_tests: set[str] | None = None) -> DebugResult:
        """``buggy_file`` is the faulty RTL (single-file designs). ``required_tests`` are the tests
        that must pass after the fix (default: all tests in ``tb_file``)."""
        self.out.mkdir(parents=True, exist_ok=True)
        buggy = buggy_file.read_text()
        tb = tb_file.read_text()
        result = DebugResult(case)
        previous: list[str] = []
        for k in range(self.cfg.debug_attempts):
            u0 = self.llm.usage.to_dict()
            reply = self.llm.complete(prompts.debug(self.d, buggy, buggy_file.name, tb, report, previous),
                                      tag=f"{self.d.name}:debug:{case}:{k}")
            u1 = self.llm.usage.to_dict()
            usage = {key: round(u1[key] - u0[key], 1) for key in u1}
            obj = extract_json(reply.text) or {}
            edits = obj.get("fix") or []
            if isinstance(edits, dict):
                edits = [edits]
            try:
                bug_line = int(obj.get("bug_line")) if obj.get("bug_line") is not None else None
            except (TypeError, ValueError):
                bug_line = None
            patched, changed, problem = apply_edits(buggy, edits) if edits else (None, [], "no fix given")
            att = DebugAttempt(bug_line, str(obj.get("explanation", ""))[:600], edits, patched is not None,
                               "invalid", usage=usage, edited_lines=changed)
            result.attempts.append(att)
            if patched is None or patched == buggy:
                previous.append(f"attempt {k + 1}: the fix could not be applied ({problem or 'it changes nothing'})")
                continue
            pdir = self.out / f"{case}_fix{k + 1}"
            pdir.mkdir(parents=True, exist_ok=True)
            pfile = pdir / buggy_file.name
            pfile.write_text(patched)
            att.patched_file = str(pfile)
            ok, err = compiles(pfile, self.d.top)
            if not ok:
                att.self_check = "no_compile"
                plines = patched.split("\n")
                shown = "; ".join(f"line {n} became `{plines[n - 1].strip()}`" for n in changed)
                err = err.replace(str(pdir) + "/", "")
                previous.append(f"attempt {k + 1}: {shown} -> compile error: {err[:300]}")
                report = f"Your previous fix did not compile ({shown}):\n{err[:1500]}"
                continue
            res = run_cocotb([pfile], self.d.top, tb_file, self.out / "sim", self.d.parameters,
                             timeout=self.cfg.sim_timeout)
            need = required_tests if required_tests is not None else {t.name for t in res.tests}
            failed = {t.name for t in res.tests if not t.passed} & need
            missing = need - {t.name for t in res.tests}
            if res.status in ("timeout", "rtl_error", "tb_error") or failed or missing:
                att.self_check = "fail"
                plines = patched.split("\n")
                edit_txt = "; ".join(f"line {n} -> `{plines[n - 1].strip()}`" for n in changed)
                previous.append(f"attempt {k + 1}: {edit_txt} -> tests still fail ({_short(res)})")
                report = failure_report(res)
                self.log(f"[{self.d.name}] debug {case}: attempt {k + 1} (line {changed[0] if changed else bug_line}) "
                         "did not fix it")
                continue
            att.self_check = "pass"
            result.fixed_self_check = True
            where = changed[0] if changed else bug_line
            self.log(f"[{self.d.name}] debug {case}: fixed at line {where} on attempt {k + 1}")
            break
        (self.out / f"{case}.json").write_text(json.dumps(result.to_dict(), indent=1))
        return result
