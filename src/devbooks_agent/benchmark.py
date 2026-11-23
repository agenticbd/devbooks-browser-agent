"""Repeatable benchmark comparing Pure Playwright, Standalone Browser Use 1.0, and Hybrid CDP."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from demo_site.server import DevBooksServer, ground_truth_matches
from devbooks_agent.browser_use_agent import DEFAULT_MODEL, run_browser_use_agent
from devbooks_agent.hybrid_cdp_agent import run_hybrid_cdp_agent
from devbooks_agent.models import reports_match_ground_truth
from devbooks_agent.playwright_scraper import run_playwright_scraper


def summarize_group(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [r["duration_seconds"] for r in rows]
    passes = sum(1 for r in rows if r["exact_match"])
    steps = [r["steps"] for r in rows if r.get("steps") is not None]
    in_toks = [r["input_tokens"] for r in rows if r.get("input_tokens") is not None]
    out_toks = [r["output_tokens"] for r in rows if r.get("output_tokens") is not None]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    return {
        "group": name,
        "runs": len(rows),
        "exact_matches": passes,
        "median_s": round(statistics.median(durations), 2),
        "min_s": round(min(durations), 2),
        "max_s": round(max(durations), 2),
        "median_steps": statistics.median(steps) if steps else 0,
        "median_input_tokens": int(statistics.median(in_toks)) if in_toks else 0,
        "median_output_tokens": int(statistics.median(out_toks)) if out_toks else 0,
        "median_cost_usd": round(statistics.median(costs), 6) if costs else None,
        "trials": rows,
    }


ALL_GROUPS = ("playwright_v1", "playwright_v2", "browser_use_v1", "browser_use_v2", "hybrid_cdp_v2")


async def run_benchmark(
    runs: int,
    model: str,
    run_judge_demo: bool,
    output_path: Path,
    selected_groups: tuple[str, ...] = ALL_GROUPS,
) -> dict[str, Any]:
    expected = ground_truth_matches()
    groups: list[dict[str, Any]] = []

    # 1. Pure Playwright on v1 and v2
    for layout in ("v1", "v2"):
        gname = f"playwright_{layout}"
        if gname not in selected_groups:
            continue
        trials: list[dict[str, Any]] = []
        for idx in range(1, runs + 1):
            with DevBooksServer(layout=layout) as srv:
                res = await run_playwright_scraper(srv.base_url)
            matched = reports_match_ground_truth(res.report, expected)
            trials.append(
                {
                    "trial": idx,
                    "duration_seconds": round(res.duration_seconds, 3),
                    "exact_match": matched,
                    "steps": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "error": res.error,
                    "report": res.report.model_dump() if res.report else None,
                }
            )
            print(
                f"[{gname}] run {idx}/{runs}: "
                f"{res.duration_seconds:.2f}s | match={matched}"
                + (f" | error={res.error.splitlines()[0]}" if res.error else ""),
                flush=True,
            )
        groups.append(summarize_group(gname, trials))

    # 2. Standalone Browser Use 1.0 on v1 and v2
    for layout in ("v1", "v2"):
        gname = f"browser_use_{layout}"
        if gname not in selected_groups:
            continue
        trials = []
        for idx in range(1, runs + 1):
            with DevBooksServer(layout=layout) as srv:
                res = await run_browser_use_agent(srv.base_url, layout=layout, model=model, judge=False)
            matched = reports_match_ground_truth(res.report, expected)
            trials.append(
                {
                    "trial": idx,
                    "status": res.status,
                    "duration_seconds": round(res.duration_seconds, 3),
                    "exact_match": matched,
                    "steps": res.steps,
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "cost_usd": res.cost_usd,
                    "error": res.error,
                    "report": res.report.model_dump() if res.report else None,
                }
            )
            print(
                f"[{gname}] run {idx}/{runs}: "
                f"{res.duration_seconds:.2f}s | steps={res.steps} | "
                f"tokens={res.input_tokens}in/{res.output_tokens}out | cost={res.cost_usd} | match={matched}"
                + (f" | err={res.error}" if res.error else ""),
                flush=True,
            )
        groups.append(summarize_group(gname, trials))

    # 3. Hybrid Playwright + Browser Use (CDP) on v2
    if "hybrid_cdp_v2" in selected_groups:
        hybrid_trials: list[dict[str, Any]] = []
        for idx in range(1, runs + 1):
            shot = Path("artifacts") / f"hybrid_v2_run{idx}.png"
            with DevBooksServer(layout="v2") as srv:
                res = await run_hybrid_cdp_agent(
                    srv.base_url,
                    layout="v2",
                    model=model,
                    judge=False,
                    screenshot_path=shot,
                )
            matched = reports_match_ground_truth(res.report, expected)
            hybrid_trials.append(
                {
                    "trial": idx,
                    "status": res.status,
                    "duration_seconds": round(res.duration_seconds, 3),
                    "exact_match": matched,
                    "steps": res.steps,
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "cost_usd": res.cost_usd,
                    "error": res.error,
                    "final_url": res.final_url,
                    "screenshot_bytes": res.screenshot_bytes,
                    "report": res.report.model_dump() if res.report else None,
                }
            )
            print(
                f"[hybrid_cdp_v2] run {idx}/{runs}: "
                f"{res.duration_seconds:.2f}s | steps={res.steps} | "
                f"tokens={res.input_tokens}in/{res.output_tokens}out | cost={res.cost_usd} | "
                f"shot={res.screenshot_bytes}B | match={matched}"
                + (f" | err={res.error}" if res.error else ""),
                flush=True,
            )
        groups.append(summarize_group("hybrid_cdp_v2", hybrid_trials))

    judge_demo: dict[str, Any] | None = None
    if run_judge_demo:
        with DevBooksServer(layout="v2") as srv:
            jres = await run_hybrid_cdp_agent(
                srv.base_url,
                layout="v2",
                model=model,
                judge=True,
                screenshot_path=Path("artifacts") / "hybrid_v2_judge.png",
            )
        judge_demo = {
            "duration_seconds": round(jres.duration_seconds, 3),
            "steps": jres.steps,
            "input_tokens": jres.input_tokens,
            "output_tokens": jres.output_tokens,
            "cost_usd": jres.cost_usd,
            "exact_match": reports_match_ground_truth(jres.report, expected),
            "judgement": jres.judgement,
        }
        print(
            f"[hybrid_cdp_v2_judge] {jres.duration_seconds:.2f}s | steps={jres.steps} | "
            f"match={judge_demo['exact_match']} | judgement={jres.judgement}",
            flush=True,
        )

    payload = {
        "model": model,
        "runs_per_group": runs,
        "ground_truth": expected,
        "summary": groups,
        "judge_demo": judge_demo,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n=== Summary Table ===")
    print(f"{'Configuration':<18} {'Pass':<6} {'Median(s)':<10} {'Range(s)':<14} {'Steps':<7} {'Tokens (in/out)'}")
    for g in groups:
        rng = f"{g['min_s']:.2f}-{g['max_s']:.2f}"
        tok = f"{g['median_input_tokens']}/{g['median_output_tokens']}"
        print(
            f"{g['group']:<18} {g['exact_matches']}/{g['runs']:<4} "
            f"{g['median_s']:<10.2f} {rng:<14} {g['median_steps']:<7} {tok}"
        )
    return payload


def main() -> None:
    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="Benchmark Playwright vs Browser Use 1.0 vs Hybrid CDP.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--no-judge-demo", action="store_true")
    parser.add_argument(
        "--groups",
        nargs="+",
        choices=ALL_GROUPS,
        default=list(ALL_GROUPS),
        help="Subset of benchmark groups to run.",
    )
    parser.add_argument("--output", type=Path, default=Path("benchmark_results.json"))
    args = parser.parse_args()

    needs_llm = any(g.startswith(("browser_use", "hybrid_cdp")) for g in args.groups) or not args.no_judge_demo
    if needs_llm and not os.environ.get("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is not set. Export it or place it in .env before running benchmarks.")

    asyncio.run(run_benchmark(args.runs, args.model, not args.no_judge_demo, args.output, tuple(args.groups)))


if __name__ == "__main__":
    main()
