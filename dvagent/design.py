"""Design descriptions: RTL sources, spec and metadata of a device under test."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Design:
    name: str
    root: Path
    top: str
    sources: list[Path]
    spec: str
    parameters: dict = field(default_factory=dict)
    clock: str | None = None
    reset: str | None = None
    difficulty: str = ""
    summary: str = ""

    @property
    def ref_test(self) -> Path:
        return self.root / "ref" / "test_ref.py"

    def rtl_text(self) -> str:
        return "\n".join(p.read_text() for p in self.sources)


def load_design(path: str | Path) -> Design:
    """Load a design directory.

    A design directory holds ``spec.md`` and either ``design.json`` (top, sources, ...)
    or a single Verilog file in ``rtl/`` whose module name becomes the top.
    """
    root = Path(path).resolve()
    spec_file = root / "spec.md"
    if not spec_file.exists():
        raise FileNotFoundError(f"{spec_file} not found: every design needs a written spec")
    meta_file = root / "design.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        sources = [root / s for s in meta["sources"]]
        top = meta["top"]
    else:
        sources = sorted((root / "rtl").glob("*.v")) + sorted((root / "rtl").glob("*.sv"))
        if not sources:
            raise FileNotFoundError(f"no Verilog sources in {root / 'rtl'}")
        mods = re.findall(r"^\s*module\s+(\w+)", "\n".join(s.read_text() for s in sources), re.M)
        if len(mods) != 1:
            raise ValueError(f"cannot pick a top module from {mods}; add a design.json")
        meta = {"name": root.name}
        top = mods[0]
    for s in sources:
        if not s.exists():
            raise FileNotFoundError(s)
    return Design(
        name=meta.get("name", root.name),
        root=root,
        top=top,
        sources=sources,
        spec=spec_file.read_text(),
        parameters=meta.get("parameters", {}),
        clock=meta.get("clock"),
        reset=meta.get("reset"),
        difficulty=meta.get("difficulty", ""),
        summary=meta.get("summary", ""),
    )


def bench_designs(bench_dir: str | Path) -> list[Design]:
    order = ["alu8", "updown_counter", "seq_detector", "sync_fifo", "rr_arbiter",
             "crc8", "sat_mac", "uart_tx", "spi_master", "apb_regs"]
    root = Path(bench_dir) / "designs"
    names = [n for n in order if (root / n).is_dir()]
    names += sorted(p.name for p in root.iterdir() if p.is_dir() and p.name not in names)
    return [load_design(root / n) for n in names]
