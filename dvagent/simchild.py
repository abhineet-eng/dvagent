"""Child process that builds the RTL and runs one cocotb test module.

Running the simulator in a separate process lets the parent kill a hung
simulation (a testbench waiting forever on a signal) with a wall-clock timeout.
Usage: python -m dvagent.simchild <config.json>
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    cfg = json.loads(Path(sys.argv[1]).read_text())
    from cocotb.runner import get_runner

    sys.path.insert(0, cfg["test_module_dir"])
    runner = get_runner(cfg["simulator"])
    build_dir = Path(cfg["build_dir"])
    marker = build_dir / ".dvagent_built"
    if not marker.exists():
        build_args = []
        if cfg["simulator"] == "verilator":
            build_args = ["-Wno-fatal", "-Wno-lint", "-Wno-style"]
            if cfg.get("coverage"):
                build_args.append("--coverage-line")
        runner.build(
            sources=cfg["sources"],
            hdl_toplevel=cfg["top"],
            parameters=cfg.get("parameters", {}),
            build_dir=str(build_dir),
            build_args=build_args,
            always=True,
            timescale=("1ns", "1ps"),
        )
        marker.write_text("ok")
    os.makedirs(cfg["test_dir"], exist_ok=True)
    runner.test(
        hdl_toplevel=cfg["top"],
        hdl_toplevel_lang="verilog",
        test_module=cfg["test_module"],
        build_dir=str(build_dir),
        test_dir=cfg["test_dir"],
        seed=cfg.get("seed", 12345),
        extra_env={"COCOTB_REDUCED_LOG_FMT": "1"},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
