"""Mutation engine: inject realistic single-line bugs into Verilog RTL.

Each mutant changes one token or one statement on one line, the way real RTL
bugs look: an off-by-one constant, ``<`` instead of ``<=``, a swapped operator,
an inverted condition, a forgotten assignment.
"""
from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

_TOKEN = re.compile(
    r"""
    (?P<num>\d+\s*'\s*[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ_]+|'[01]|\d[\d_]*)
  | (?P<id>[A-Za-z_$][\w$]*)
  | (?P<op><<<|>>>|===|!==|<<|>>|<=|>=|==|!=|&&|\|\||~&|~\||~\^|\^~|[-+*/%<>!~&|^?:=(){}\[\],;@#.])
  | (?P<ws>\s+)
  | (?P<other>.)
    """,
    re.X,
)

_SKIP_LINE = re.compile(
    r"^\s*(module|endmodule|input|output|inout|parameter|localparam|reg\b|integer|genvar|"
    r"function|endfunction|task|endtask|always\s*@|`|begin\s*$|endcase|default\s*:\s*;)"
    r"|^\s*end\s*(else\s*(begin)?)?\s*$"
)

_SWAP = {
    "+": ["-"], "-": ["+"],
    "<": ["<=", ">"], ">": [">=", "<"], ">=": [">"],
    "==": ["!="], "!=": ["=="],
    "&&": ["||"], "||": ["&&"],
    "&": ["|"], "|": ["&"], "^": ["|"],
    "<<": [">>"], ">>": ["<<"],
}

_OPNAME = {
    "+": "arithmetic", "-": "arithmetic", "<": "relational", ">": "relational", "<=": "relational",
    ">=": "relational", "==": "relational", "!=": "relational", "&&": "logical", "||": "logical",
    "&": "bitwise", "|": "bitwise", "^": "bitwise", "<<": "shift", ">>": "shift",
}


@dataclass
class Mutant:
    id: str
    file: str
    line: int                 # 1-based line number in the file
    operator: str             # kind of bug
    original: str             # original line text
    mutated: str              # mutated line text
    description: str

    def apply(self, text: str) -> str:
        lines = text.split("\n")
        assert lines[self.line - 1] == self.original, "source changed since the mutant was generated"
        lines[self.line - 1] = self.mutated
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)


def _strip_comments(text: str) -> list[str]:
    """Blank out comments, keeping line and column positions."""
    out = []
    in_block = False
    for ln in text.split("\n"):
        res = []
        i = 0
        while i < len(ln):
            if in_block:
                j = ln.find("*/", i)
                if j < 0:
                    res.append(" " * (len(ln) - i))
                    i = len(ln)
                else:
                    res.append(" " * (j + 2 - i))
                    i = j + 2
                    in_block = False
            elif ln.startswith("//", i):
                res.append(" " * (len(ln) - i))
                i = len(ln)
            elif ln.startswith("/*", i):
                in_block = True
            elif ln[i] == '"':
                j = ln.find('"', i + 1)
                j = len(ln) - 1 if j < 0 else j
                res.append(" " * (j + 1 - i))
                i = j + 1
            else:
                res.append(ln[i])
                i += 1
        out.append("".join(res))
    return out


def _tokens(line: str):
    toks = []
    for m in _TOKEN.finditer(line):
        kind = m.lastgroup
        if kind == "ws":
            continue
        toks.append((kind, m.group(), m.start(), m.end()))
    return toks


def _bump_number(tok: str, delta: int) -> str | None:
    m = re.fullmatch(r"(\d+)\s*'\s*([sS]?)([bBoOdDhH])\s*([0-9a-fA-F_]+)", tok)
    if m:
        width, sgn, base, digits = int(m.group(1)), m.group(2), m.group(3).lower(), m.group(4).replace("_", "")
        radix = {"b": 2, "o": 8, "d": 10, "h": 16}[base]
        val = int(digits, radix) + delta
        if val < 0 or val >= (1 << width):
            return None
        fmt = {"b": "b", "o": "o", "d": "d", "h": "X"}[base]
        body = format(val, fmt)
        if base in "bh" and len(body) < len(digits):
            body = body.zfill(len(digits))
        return f"{width}'{sgn}{m.group(3)}{body}"
    if re.fullmatch(r"\d[\d_]*", tok):
        val = int(tok.replace("_", "")) + delta
        return str(val) if val >= 0 else None
    return None


def _is_unary(prev) -> bool:
    return prev is None or prev[0] == "op" and prev[1] not in (")", "]", "}")


def candidates(text: str, file: str = "rtl.v") -> list[Mutant]:
    """Every single-token / single-statement mutant of ``text``."""
    raw = text.split("\n")
    clean = _strip_comments(text)
    muts: list[Mutant] = []
    seen = set()

    def add(lineno, op, new_line, desc):
        orig = raw[lineno - 1]
        if new_line == orig or (lineno, new_line) in seen:
            return
        seen.add((lineno, new_line))
        muts.append(Mutant("", file, lineno, op, orig, new_line, desc))

    in_function_header = False
    for idx, cl in enumerate(clean):
        lineno = idx + 1
        stripped = cl.strip()
        if not stripped:
            continue
        if re.match(r"^\s*function\b", cl):
            in_function_header = True
        if in_function_header and re.match(r"^\s*begin\b", cl):
            in_function_header = False
        if _SKIP_LINE.match(cl) or in_function_header:
            continue
        is_decl = re.match(r"^\s*wire\b", cl) is not None
        toks = _tokens(cl)
        if is_decl:   # only mutate the right-hand side of "wire x = expr;"
            eq = next((i for i, t in enumerate(toks) if t[1] == "="), None)
            if eq is None:
                continue
            first = eq + 1
        else:
            first = 0
        lo, hi = 0, len(cl)
        fm = re.search(r"\bfor\s*\(([^;]*);([^;]*);", cl)
        if fm:                      # in a for-loop header only mutate the loop condition
            lo, hi = fm.start(2), fm.end(2)
        depth = 0
        bracket = 0
        assign_seen = False
        for i, (kind, tok, s, e) in enumerate(toks):
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
            elif tok == "[":
                bracket += 1
            elif tok == "]":
                bracket -= 1
            if i < first or s < lo or e > hi:
                continue
            prev = toks[i - 1] if i > 0 else None
            line = raw[idx]
            if kind == "op" and tok in _SWAP:
                if tok in ("<=",) and depth == 0 and not is_decl:
                    pass  # non-blocking assignment, not a comparison
                elif tok in ("-", "&", "|", "^") and _is_unary(prev):
                    pass  # unary minus / reduction operator
                elif tok in ("+", "-") and bracket > 0:
                    pass  # index arithmetic: leave to constant mutations
                else:
                    for new in _SWAP[tok]:
                        add(lineno, _OPNAME[tok], line[:s] + new + line[e:], f"'{tok}' replaced by '{new}'")
            if tok == "<=" and depth > 0:
                for new in ("<", ">="):
                    add(lineno, "relational", line[:s] + new + line[e:], f"'<=' replaced by '{new}'")
            if tok == "<=" and depth == 0 and not is_decl:
                assign_seen = True
            if kind == "op" and tok == "!" and i + 1 < len(toks) and toks[i + 1][1] != "=":
                add(lineno, "logical", line[:s] + line[e:], "'!' removed")
            if kind == "num":
                for delta in (1, -1):
                    new = _bump_number(tok, delta)
                    if new is not None:
                        add(lineno, "constant", line[:s] + new + line[e:], f"constant {tok} changed to {new}")
            if kind == "id" and tok == "if" and i + 1 < len(toks) and toks[i + 1][1] == "(":
                # invert the whole condition: find the matching parenthesis
                d = 0
                for j in range(i + 1, len(toks)):
                    if toks[j][1] == "(":
                        d += 1
                    elif toks[j][1] == ")":
                        d -= 1
                        if d == 0:
                            cs, ce = toks[i + 1][3], toks[j][2]
                            cond = line[cs:ce]
                            add(lineno, "condition", line[:cs] + "!(" + cond + ")" + line[ce:],
                                f"condition ({cond.strip()}) inverted")
                            break
        # statement deletion: drop a non-blocking assignment
        m = re.search(r"(?:^|\bbegin\b|\belse\b|\)|:)\s*([A-Za-z_][\w\[\]:+ ]*?\s*<=\s*[^;]+;)", raw[idx])
        if assign_seen and m and not is_decl:
            add(lineno, "deleted", raw[idx][: m.start(1)] + ";" + raw[idx][m.end(1):],
                f"assignment '{m.group(1).strip()}' removed")
    return muts


def sample(text: str, file: str, n: int, seed: int = 1) -> list[Mutant]:
    """A reproducible random sample of mutants, spread over operator kinds."""
    cands = candidates(text, file)
    rng = random.Random(seed)
    rng.shuffle(cands)
    by_kind: dict[str, list[Mutant]] = {}
    for m in cands:
        by_kind.setdefault(m.operator, []).append(m)
    ordered: list[Mutant] = []
    kinds = sorted(by_kind)
    while len(ordered) < len(cands):
        for k in kinds:
            if by_kind[k]:
                ordered.append(by_kind[k].pop())
    return ordered[:n] if n else ordered
