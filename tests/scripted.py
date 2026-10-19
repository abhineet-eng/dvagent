"""A scripted stand-in for the LLM, used to test the agent loops without an API key."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def first_test_only(code: str) -> str:
    """Keep the helpers and only the first @cocotb.test of a testbench."""
    parts = re.split(r"(?=^@cocotb\.test\(\))", code, flags=re.M)
    return parts[0] + parts[1]


class ScriptedLLM:
    """Plays a plausible conversation for one design:
    draft with a syntax error -> wrong blame on the design (rejected) -> partial fix ->
    coverage step returns the full testbench -> debug answers point at the mutated line."""

    def __init__(self, design, mutants=None):
        self.ref = design.ref_test.read_text()
        self.mutants = {m.mutated.strip(): m for m in (mutants or [])}
        self.calls = []

    def __call__(self, messages, tag):
        kind = tag.split(":")[1]
        self.calls.append(kind)
        user = messages[-1]["content"]
        if kind == "generate":
            return "Here is the plan.\n```python\nimport cocotb\n\n@cocotb.test()\nasync def t(dut)\n    pass\n```"
        if kind == "fix" and "SyntaxError" in user and "reviewer" not in user.lower():
            return '```json\n{"blame": "design", "root_cause": "the design looks wrong"}\n```'
        if kind == "fix":
            return ('```json\n{"blame": "testbench", "root_cause": "missing colon"}\n```\n```python\n'
                    + first_test_only(self.ref) + "```")
        if kind == "coverage":
            return "```python\n" + self.ref + "```"
        if kind == "debug":
            rtl = re.search(r"```verilog\n(.*?)```", user, re.S).group(1)
            for line in rtl.splitlines():
                m = re.match(r"\s*(\d+) \| (.*)$", line)
                if m and m.group(2).strip() in self.mutants:
                    mut = self.mutants[m.group(2).strip()]
                    return "```json\n" + json.dumps({"bug_line": int(m.group(1)), "explanation": "scripted",
                                                     "fix": [{"line": int(m.group(1)), "new_text": mut.original}]}) + "\n```"
            return '{"bug_line": 1, "explanation": "no idea", "fix": []}'
        raise AssertionError(kind)
