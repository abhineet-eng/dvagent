"""Light-weight Verilog helpers: module interface extraction."""
from __future__ import annotations

import re


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def module_header(text: str, top: str) -> str:
    """The module declaration up to and including the port list ``);``.

    This is all the agent sees of the implementation when it writes a
    testbench: the interface, not the logic.
    """
    clean = strip_comments(text)
    m = re.search(rf"\bmodule\s+{re.escape(top)}\b", clean)
    if not m:
        raise ValueError(f"module {top} not found")
    i = m.start()
    depth = 0
    for j in range(m.end(), len(clean)):
        ch = clean[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            header = clean[i:j + 1]
            return "\n".join(ln.rstrip() for ln in header.splitlines() if ln.strip())
    raise ValueError(f"could not find the end of the port list of {top}")


def ports(text: str, top: str) -> list[dict]:
    """[{dir, name, width, signed}] parsed from an ANSI-style header."""
    header = module_header(text, top)
    body = header[header.find("(", header.find(")") if "#(" in header else 0):]
    out = []
    for decl in re.split(r",\s*(?=input|output|inout)", body.strip("();\n ")):
        m = re.match(r"\s*\(?\s*(input|output|inout)\s+(?:wire|reg|logic)?\s*(signed)?\s*(\[[^\]]+\])?\s*(.*)", decl, re.S)
        if not m:
            continue
        for name in re.findall(r"\w+", m.group(4)):
            if name in ("wire", "reg", "logic", "signed"):
                continue
            out.append({"dir": m.group(1), "name": name, "range": (m.group(3) or "").replace(" ", ""),
                        "signed": bool(m.group(2))})
    return out
