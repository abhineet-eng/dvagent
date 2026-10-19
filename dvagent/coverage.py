"""Code coverage from Verilator's coverage.dat (line and branch points).

Verilator 5.0's lcov export and annotator merge all points on a source line
into one number, which hides untaken else-branches. This module reads the raw
coverage points instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_ENTRY = re.compile(r"^C '(?P<keys>.*)' (?P<count>\d+)\s*$")

_KIND = {
    "block": "statement block",
    "if": "if-branch taken",
    "else": "else-branch taken",
    "elsif": "if-condition true",
    "case": "case item",
}


@dataclass
class CovPoint:
    file: str
    line: int
    kind: str
    count: int

    @property
    def label(self) -> str:
        return _KIND.get(self.kind, self.kind)


@dataclass
class Coverage:
    points: list[CovPoint] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.points)

    @property
    def hit(self) -> int:
        return sum(1 for p in self.points if p.count > 0)

    @property
    def percent(self) -> float:
        return 100.0 * self.hit / self.total if self.total else 100.0

    def missed(self) -> list[CovPoint]:
        return [p for p in self.points if p.count == 0]

    def describe_missed(self, limit: int = 25) -> str:
        """Human/LLM-readable list of uncovered points with their source lines."""
        out = []
        cache: dict[str, list[str]] = {}
        for p in self.missed()[:limit]:
            if p.file not in cache:
                try:
                    cache[p.file] = Path(p.file).read_text().splitlines()
                except OSError:
                    cache[p.file] = []
            lines = cache[p.file]
            src = lines[p.line - 1].strip() if 0 < p.line <= len(lines) else "?"
            out.append(f"line {p.line}: {p.label} never executed  |  {src}")
        extra = len(self.missed()) - limit
        if extra > 0:
            out.append(f"... and {extra} more")
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {"hit": self.hit, "total": self.total, "percent": round(self.percent, 2),
                "missed": [{"line": p.line, "kind": p.kind} for p in self.missed()]}


def parse_coverage_dat(path: str | Path, only_files: list[str] | None = None) -> Coverage:
    cov = Coverage()
    seen: dict[tuple, CovPoint] = {}
    for raw in Path(path).read_text(errors="replace").splitlines():
        m = _ENTRY.match(raw)
        if not m:
            continue
        fields = {}
        for part in m.group("keys").split("\x01"):
            if "\x02" in part:
                k, v = part.split("\x02", 1)
                fields[k] = v
        page = fields.get("page", "")
        if not (page.startswith("v_line") or page.startswith("v_branch")):
            continue
        f = fields.get("f", "")
        if only_files and not any(Path(f).name == Path(o).name for o in only_files):
            continue
        key = (f, int(fields.get("l", 0)), fields.get("o", ""), fields.get("n", ""))
        count = int(m.group("count"))
        if key in seen:
            seen[key].count += count
        else:
            seen[key] = CovPoint(f, int(fields.get("l", 0)), fields.get("o", ""), count)
    cov.points = sorted(seen.values(), key=lambda p: (p.file, p.line, p.kind))
    return cov
