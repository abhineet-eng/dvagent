"""Aggregate benchmark results into summary.json, summary.md, charts and report.html."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from .bench import SNAPSHOTS

STAGE_LABEL = {"single": "One-shot LLM", "feedback": "+ simulation feedback", "final": "+ coverage closure"}


def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def collect(results_dir: Path) -> dict:
    results_dir = Path(results_dir)
    meta = _load(results_dir / "run.json") or {}
    rows = []
    order = ["alu8", "updown_counter", "seq_detector", "sync_fifo", "rr_arbiter", "crc8", "sat_mac",
             "uart_tx", "spi_master", "apb_regs"]
    dirs = [p for p in results_dir.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: (order.index(p.name) if p.name in order else len(order), p.name))
    for ddir in dirs:
        v = _load(ddir / "agent" / "verify.json")
        ev = _load(ddir / "eval.json")
        if not v or not ev:
            continue
        dbg = _load(ddir / "debug.json") or []
        dj = _load(Path(__file__).resolve().parent.parent / "bench" / "designs" / ddir.name / "design.json") or {}
        snaps = ev["snapshots"]
        n_mut = len(ev["mutants"])
        row = {
            "design": ddir.name, "difficulty": dj.get("difficulty", ""), "mutants": n_mut,
            "llm_calls": v["usage"].get("calls", 0),
            "tokens": v["usage"].get("prompt_tokens", 0) + v["usage"].get("completion_tokens", 0),
            "false_alarms": v.get("false_alarms", 0), "steps": len(v["steps"]),
        }
        for s in SNAPSHOTS:
            r = snaps[s]
            row[f"{s}_pass"] = r["golden_status"] == "pass"
            row[f"{s}_tests"] = f"{r['tests_passing']}/{r['tests_total']}"
            row[f"{s}_cov"] = r["coverage"]
            row[f"{s}_killed"] = len(r["killed"])
            row[f"{s}_score"] = r["mutation_score"]
        row["debug_n"] = len(dbg)
        row["debug_loc1"] = sum(d["localized_first"] for d in dbg)
        row["debug_fix1"] = sum(d["fixed_first"] for d in dbg)
        row["debug_fix"] = sum(d["fixed"] for d in dbg)
        row["debug_cases"] = dbg
        dbg_calls = sum(d["attempts"] for d in dbg)
        row["debug_calls"] = dbg_calls
        rows.append(row)

    tot_mut = sum(r["mutants"] for r in rows) or 1
    overall = {
        "designs": len(rows),
        "mutants": sum(r["mutants"] for r in rows),
        "llm_calls": sum(r["llm_calls"] + r["debug_calls"] for r in rows),
        "tokens": sum(r["tokens"] for r in rows),
        "false_alarms": sum(r["false_alarms"] for r in rows),
    }
    for s in SNAPSHOTS:
        overall[f"{s}_pass"] = sum(r[f"{s}_pass"] for r in rows)
        overall[f"{s}_killed"] = sum(r[f"{s}_killed"] for r in rows)
        overall[f"{s}_score"] = round(100.0 * overall[f"{s}_killed"] / tot_mut, 1)
        covs = [r[f"{s}_cov"] for r in rows if r[f"{s}_cov"] is not None]
        overall[f"{s}_cov"] = round(sum(covs) / len(covs), 1) if covs else None
    dn = sum(r["debug_n"] for r in rows)
    overall["debug_n"] = dn
    for k in ("debug_loc1", "debug_fix1", "debug_fix"):
        overall[k] = sum(r[k] for r in rows)
        overall[k + "_pct"] = round(100.0 * overall[k] / dn, 1) if dn else None
    return {"meta": meta, "rows": rows, "overall": overall}


def _pct(x):
    return "n/a" if x is None else f"{x:.1f}%"


def markdown(summary: dict) -> str:
    m, o, rows = summary["meta"], summary["overall"], summary["rows"]
    out = ["# DVAgent benchmark results\n",
           f"Model: `{m.get('model', '?')}` via {m.get('provider', '?')}, run {m.get('started', '?')}. "
           f"{o['designs']} designs, {o['mutants']} injected bugs, {o['llm_calls']} LLM calls.\n",
           "## Headline\n",
           "| Stage | Testbenches passing on the correct design | Bugs caught | Mean line/branch coverage |",
           "|---|---|---|---|"]
    for s in SNAPSHOTS:
        out.append(f"| {STAGE_LABEL[s]} | {o[f'{s}_pass']}/{o['designs']} | "
                   f"{o[f'{s}_killed']}/{o['mutants']} ({o[f'{s}_score']:.1f}%) | {_pct(o[f'{s}_cov'])} |")
    if o["debug_n"]:
        out += ["", "| Debugging (bugs caught by the final testbench) | Result |", "|---|---|",
                f"| Bug cases debugged | {o['debug_n']} |",
                f"| Faulty line found on the first try | {o['debug_loc1']}/{o['debug_n']} ({_pct(o['debug_loc1_pct'])}) |",
                f"| Correct fix on the first try | {o['debug_fix1']}/{o['debug_n']} ({_pct(o['debug_fix1_pct'])}) |",
                f"| Correct fix with verify-and-retry (up to 3 tries) | {o['debug_fix']}/{o['debug_n']} ({_pct(o['debug_fix_pct'])}) |"]
    out += ["", f"False design-bug reports on correct designs: {o['false_alarms']}.", "",
            "## Per design\n",
            "| Design | Level | Passes (1-shot / final) | Coverage (1-shot / final) | Bugs caught: 1-shot / +feedback / final | Debug: line found / fixed | LLM calls |",
            "|---|---|---|---|---|---|---|"]
    for r in rows:
        yn = lambda b: "yes" if b else "no"   # noqa: E731
        out.append(
            f"| {r['design']} | {r['difficulty']} | {yn(r['single_pass'])} ({r['single_tests']}) / "
            f"{yn(r['final_pass'])} ({r['final_tests']}) | {_pct(r['single_cov'])} / {_pct(r['final_cov'])} | "
            f"{r['single_killed']} / {r['feedback_killed']} / {r['final_killed']} of {r['mutants']} | "
            f"{r['debug_loc1']}/{r['debug_n']} / {r['debug_fix']}/{r['debug_n']} | "
            f"{r['llm_calls'] + r['debug_calls']} |")
    out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------ chart
THEMES = {
    "light": {"surface": "#fcfcfb", "primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "baseline": "#c3c2b7",
              "stages": ["#86b6ef", "#2a78d6", "#104281"]},
    "dark": {"surface": "#1a1a19", "primary": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "baseline": "#383835",
             "stages": ["#184f95", "#3987e5", "#9ec5f4"]},
}


def chart(summary: dict, out_png: Path, theme: str = "light"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Patch

    t = THEMES[theme]
    rows = summary["rows"]
    o = summary["overall"]
    names = [r["design"] for r in rows] + ["all designs"]
    scores = {s: [r[f"{s}_score"] or 0 for r in rows] + [o[f"{s}_score"]] for s in SNAPSHOTS}

    fig, ax = plt.subplots(figsize=(11, 4.4), dpi=200)
    fig.patch.set_facecolor(t["surface"])
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["baseline"])
    ax.tick_params(axis="both", colors=t["muted"], labelsize=8.5, length=0)
    ax.tick_params(axis="x", labelcolor=t["secondary"], pad=6)
    ax.grid(axis="y", color=t["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_ylim(0, 106)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    n = len(names)
    w = 0.26
    gap = 0.02
    for k, s in enumerate(SNAPSHOTS):
        for i, v in enumerate(scores[s]):
            x = i + (k - 1) * (w + gap) + (0.35 if i == n - 1 else 0)
            if v > 0:
                ax.add_patch(FancyBboxPatch((x - w / 2, 0), w, v, boxstyle="round,pad=0,rounding_size=0.06",
                                            mutation_aspect=40, facecolor=t["stages"][k], edgecolor="none",
                                            zorder=3))
                ax.add_patch(plt.Rectangle((x - w / 2, 0), w, min(v, 3), facecolor=t["stages"][k],
                                           edgecolor="none", zorder=3))
            if i == n - 1:
                ax.annotate(f"{v:.0f}%", (x, v), xytext=(0, 3), textcoords="offset points", ha="center",
                            va="bottom", fontsize=8.5, color=t["primary"])
            elif v == 0:
                ax.annotate("0", (x, 0), xytext=(0, 2), textcoords="offset points", ha="center",
                            va="bottom", fontsize=7.5, color=t["muted"])
    ax.axvline(n - 1.5 + 0.17, color=t["grid"], linewidth=1)
    ax.set_xlim(-0.6, n - 1 + 0.35 + 0.6)
    ax.set_xticks([i + (0.35 if i == n - 1 else 0) for i in range(n)])
    ax.set_xticklabels([x.replace("_", " _ ") if False else x for x in names], rotation=0)
    for lbl in ax.get_xticklabels()[-1:]:
        lbl.set_color(t["primary"])
        lbl.set_fontweight("bold")
    fig.text(0.05, 0.95, "Injected bugs caught by the agent's testbench", fontsize=11.5,
             color=t["primary"], va="top")
    fig.text(0.05, 0.895, f"mutation score: share of {o['mutants']} single-line RTL bugs "
                          f"({o['mutants'] // max(1, o['designs'])} per design) that make at least one test fail; "
                          f"model {summary['meta'].get('model', '?')}",
             fontsize=8.5, color=t["secondary"], va="top")
    handles = [Patch(facecolor=t["stages"][k], label=STAGE_LABEL[s]) for k, s in enumerate(SNAPSHOTS)]
    leg = ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(-0.005, 1.01), ncol=3, frameon=False,
                    fontsize=8.5, handlelength=1.2, columnspacing=1.4, borderaxespad=0)
    for txt in leg.get_texts():
        txt.set_color(t["secondary"])
    plt.setp(ax.get_xticklabels(), fontsize=8)
    fig.subplots_adjust(left=0.05, right=0.99, top=0.78, bottom=0.11)
    fig.savefig(out_png, dpi=200, facecolor=t["surface"])
    plt.close(fig)


# ------------------------------------------------------------------------------------------- html
CSS = """
:root{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;
--accent:#2a78d6;--good:#006300;--bad:#d03b3b;--code:#f3f2ee}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0d0d0d;--surface:#1a1a19;
--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--accent:#3987e5;--good:#0ca30c;--bad:#e66767;--code:#232321}}
:root[data-theme="dark"]{--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;
--line:#2c2c2a;--accent:#3987e5;--good:#0ca30c;--bad:#e66767;--code:#232321}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px}h3{font-size:16px;margin:20px 0 6px}
.sub{color:var(--ink2);margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:26px;font-weight:600}.tile span{color:var(--ink2);font-size:13px}
table{border-collapse:collapse;width:100%;background:var(--surface);font-size:13.5px;
font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600}.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
.ok{color:var(--good);font-weight:600}.no{color:var(--bad);font-weight:600}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:10px 0;padding:10px 14px}
summary{cursor:pointer;font-weight:600}
pre{background:var(--code);padding:10px;border-radius:8px;overflow-x:auto;font-size:12.5px;line-height:1.45}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
img{max-width:100%;border-radius:10px;border:1px solid var(--line)}
.muted{color:var(--muted)}
"""


def _e(x) -> str:
    return html.escape(str(x))


def html_report(summary: dict, results_dir: Path) -> str:
    m, o, rows = summary["meta"], summary["overall"], summary["rows"]
    tiles = [
        (f"{o['single_score']:.0f}% → {o['final_score']:.0f}%", "bugs caught: one-shot LLM → full agent"),
        (f"{o['single_pass']}/{o['designs']} → {o['final_pass']}/{o['designs']}", "testbenches that run clean on the correct design"),
        (_pct(o.get("debug_fix_pct")), f"of {o['debug_n']} caught bugs fixed (verified by hidden tests)"),
        (str(o["llm_calls"]), f"LLM calls in total ({m.get('model', '?')})"),
    ]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>DVAgent report</title><style>{CSS}</style></head>"
             f"<body><main><h1>DVAgent benchmark report</h1><p class='sub'>Model <code>{_e(m.get('model'))}</code> via "
             f"{_e(m.get('provider'))} · started {_e(m.get('started'))} · {o['designs']} designs · {o['mutants']} injected bugs</p>",
             "<div class='tiles'>" + "".join(f"<div class='tile'><b>{_e(a)}</b><span>{_e(b)}</span></div>" for a, b in tiles)
             + "</div>"]
    if (results_dir / "chart_light.png").exists():
        parts.append("<picture><source media='(prefers-color-scheme: dark)' srcset='chart_dark.png'>"
                     "<img src='chart_light.png' alt='Bugs caught per design at each agent stage'></picture>")
    parts.append("<h2>Per design</h2><div class='wrap'><table><tr><th>Design</th><th>Level</th>"
                 "<th>Passes on correct RTL<br>1-shot / final</th><th>Coverage<br>1-shot / final</th>"
                 "<th>Bugs caught<br>1-shot / +feedback / final</th><th>Debug<br>line found / fixed</th>"
                 "<th>LLM calls</th><th>False alarms</th></tr>")
    for r in rows:
        mark = lambda b: "<span class='ok'>yes</span>" if b else "<span class='no'>no</span>"   # noqa: E731
        parts.append(
            f"<tr><td><a href='#{_e(r['design'])}'>{_e(r['design'])}</a></td><td>{_e(r['difficulty'])}</td>"
            f"<td>{mark(r['single_pass'])} {_e(r['single_tests'])} / {mark(r['final_pass'])} {_e(r['final_tests'])}</td>"
            f"<td>{_pct(r['single_cov'])} / {_pct(r['final_cov'])}</td>"
            f"<td>{r['single_killed']} / {r['feedback_killed']} / {r['final_killed']} of {r['mutants']}</td>"
            f"<td>{r['debug_loc1']}/{r['debug_n']} / {r['debug_fix']}/{r['debug_n']}</td>"
            f"<td>{r['llm_calls'] + r['debug_calls']}</td><td>{r['false_alarms']}</td></tr>")
    parts.append("</table></div>")

    for r in rows:
        ddir = results_dir / r["design"]
        v = _load(ddir / "agent" / "verify.json")
        parts.append(f"<h2 id='{_e(r['design'])}'>{_e(r['design'])}</h2>")
        parts.append("<div class='wrap'><table><tr><th>Step</th><th>Action</th><th>Result on the correct design</th>"
                     "<th>Coverage</th><th>Agent's diagnosis</th></tr>")
        for st in v["steps"]:
            sim = st.get("sim") or {}
            res = sim.get("status", "—")
            ntests = len(sim.get("tests", []))
            npass = sum(t["passed"] for t in sim.get("tests", []))
            cov = st.get("coverage") or {}
            diag = st.get("root_cause") or st.get("note") or ""
            if st.get("blame"):
                diag = f"[{st['blame']}] {diag}"
            parts.append(f"<tr><td>{st['index']}</td><td>{_e(st['kind'])}</td>"
                         f"<td>{_e(res)} {f'({npass}/{ntests} tests)' if ntests else ''}</td>"
                         f"<td>{_pct(cov.get('percent')) if cov else ''}</td><td>{_e(diag)}</td></tr>")
        parts.append("</table></div>")
        final_tb = ddir / "agent" / v["snapshots"]["final"]
        if final_tb.exists():
            parts.append(f"<details><summary>Final testbench ({_e(final_tb.name)})</summary><pre><code>"
                         f"{_e(final_tb.read_text())}</code></pre></details>")
        for c in r["debug_cases"]:
            verdict = "<span class='ok'>fixed</span>" if c["fixed"] else "<span class='no'>not fixed</span>"
            parts.append(
                f"<details><summary>Bug {_e(c['mutant'])}: {_e(c['description'])} (line {c['bug_line']}) — {verdict}"
                f"</summary><p>Injected: <code>{_e(c['original'])}</code> → <code>{_e(c['mutated'])}</code></p>"
                f"<p>Agent's guesses for the faulty line: {_e(c['predicted_lines'])} · attempts: {c['attempts']}</p>"
                + "".join(f"<p><b>Attempt {i + 1}:</b> {_e(ex)}<br><code>{_e('; '.join(fx))}</code></p>"
                          for i, (ex, fx) in enumerate(zip(c["explanations"], c["fixes"])))
                + "</details>")
    parts.append("<p class='muted'>Generated by DVAgent.</p></main></body></html>")
    return "\n".join(parts)


def write_report(results_dir: Path) -> dict:
    results_dir = Path(results_dir)
    summary = collect(results_dir)
    slim = {"meta": summary["meta"], "overall": summary["overall"],
            "rows": [{k: v for k, v in r.items() if k != "debug_cases"} for r in summary["rows"]]}
    (results_dir / "summary.json").write_text(json.dumps(slim, indent=1))
    (results_dir / "summary.md").write_text(markdown(summary))
    if summary["rows"]:
        for theme in THEMES:
            chart(summary, results_dir / f"chart_{theme}.png", theme)
    (results_dir / "report.html").write_text(html_report(summary, results_dir))
    return summary


def readme_section(results_dir: Path, repo_root: Path) -> str:
    """The README's results section, written from a finished benchmark run."""
    summary = collect(Path(results_dir))
    rel = Path(os.path.relpath(Path(results_dir).resolve(), Path(repo_root).resolve())).as_posix()
    md = markdown(summary).split("\n", 2)[2]           # drop the "# DVAgent benchmark results" title
    md = md.replace("## Headline\n", "").replace("## Per design\n", "### Per design\n")
    pic = (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="{rel}/chart_dark.png">\n'
           f'  <img alt="Share of injected bugs caught at each agent stage, per design" src="{rel}/chart_light.png">\n'
           f"</picture>\n")
    return (pic + "\n" + md.strip() + "\n\n"
            f"Full data: [`{rel}/`]({rel}) (per-step agent log, every testbench it wrote, every debug attempt, "
            f"and the complete LLM transcript). The workflow run's artifact holds `report.html`, "
            f"a browsable report of every step.\n")


def update_readme(readme: Path, results_dir: Path) -> bool:
    text = Path(readme).read_text()
    start, end = "<!-- results:start -->", "<!-- results:end -->"
    if start not in text or end not in text:
        return False
    a = text.index(start) + len(start)
    b = text.index(end)
    new = text[:a] + "\n" + readme_section(results_dir, Path(readme).parent) + text[b:]
    Path(readme).write_text(new)
    return True
