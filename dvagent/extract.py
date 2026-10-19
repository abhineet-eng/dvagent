"""Pull code blocks and JSON objects out of free-form LLM replies."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```[ \t]*([\w+-]*)[^\n]*\n(.*?)```", re.S)


def code_blocks(text: str, lang: str | None = None) -> list[str]:
    out = []
    for m in _FENCE.finditer(text):
        tag = m.group(1).lower()
        if lang is None or tag == lang or (lang == "python" and tag in ("py", "python3")):
            out.append(m.group(2))
    return out


def extract_python(text: str) -> str | None:
    """The testbench file from a reply: the largest python block that uses cocotb."""
    blocks = [b for b in code_blocks(text, "python") if "cocotb" in b]
    if not blocks:
        blocks = [b for b in code_blocks(text) if "import cocotb" in b]
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    # an unterminated fence (reply cut off) or no fence at all
    m = re.search(r"```(?:python|py)?\s*\n(.*)", text, re.S)
    body = m.group(1) if m else text
    i = body.find("import cocotb")
    j = body.rfind('"""', 0, i) if i > 0 else -1
    if i >= 0:
        start = j if j >= 0 and body[:j].strip() == "" else i
        start = 0 if body[:i].lstrip().startswith(('"""', "#", "import", "from")) else start
        return body[start:].replace("```", "").strip() + "\n"
    return None


def extract_json(text: str) -> dict | None:
    """The first JSON object in a reply (fenced or bare), tolerating small mistakes."""
    candidates = code_blocks(text, "json")
    candidates += [b for b in code_blocks(text) if b.lstrip().startswith("{")]
    # bare objects: scan for balanced braces
    depth, start = 0, None
    in_str, esc = False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth > 0:
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
                start = None
    for c in candidates:
        for attempt in (c, re.sub(r",\s*([}\]])", r"\1", c)):
            try:
                obj = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def number_lines(text: str) -> str:
    lines = text.rstrip("\n").split("\n")
    w = len(str(len(lines)))
    return "\n".join(f"{i + 1:>{w}} | {ln}" for i, ln in enumerate(lines))
