"""Measure prompt-cache effect: run a fixed set of prompts twice with the
cache disabled (cold) and twice with it enabled (cold then warm), and emit
docs/prompt_cache_results.md with per-prompt latency and totals."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from config import MODELS                            # noqa: E402
from agent.pipeline import (                         # noqa: E402
    route_query, execute_tools, generate_response,
    cache_clear, cache_stats, cache_set_default,
)

# Subset that exercises router + RAG + live tools + multi-tool routing.
PROMPTS = [
    "Recommend a city I can visit under a $150 daily budget",
    "Suggest a weekend trip from San Francisco",
    "Best ramen in San Francisco",
    "What will the weather be like in Honolulu tomorrow?",
    "Are there any travel advisories for Mexico right now?",
]


def run_prompt(model_id: str, prompt: str) -> dict:
    t0 = time.time()
    calls = route_query(model_id, prompt, history=[])
    t_router = time.time() - t0

    t1 = time.time()
    tool_results, rag_chunks = execute_tools(calls)
    t_tools = time.time() - t1

    t2 = time.time()
    if not tool_results:
        from agent.pipeline import generate
        from agent.prompts import RESPONSE_SYSTEM_PROMPT
        _ = generate(
            model_id,
            [{"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            max_new_tokens=500,
        )
    else:
        _ = generate_response(
            model_id, prompt, tool_results,
            rag_chunks=rag_chunks, history=[], stream=False,
        )
    t_answer = time.time() - t2

    return {
        "router": round(t_router, 2),
        "tools": round(t_tools, 2),
        "answer": round(t_answer, 2),
        "total": round(t_router + t_tools + t_answer, 2),
    }


def run_pass(model_id: str, *, label: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    print(f"\n[{label}]")
    for i, p in enumerate(PROMPTS, 1):
        t = run_prompt(model_id, p)
        rows.append(t)
        print(f"  [{i}/{len(PROMPTS)}] router={t['router']:5.2f}s  "
              f"answer={t['answer']:5.2f}s  total={t['total']:5.2f}s  | {p[:50]}")
    return rows, cache_stats()


def main() -> None:
    model_id = MODELS["Fast"]
    print(f"model: {model_id}")

    # Pass A — cache disabled globally, both runs go to the LLM.
    cache_set_default(False)
    cache_clear()
    a1, _   = run_pass(model_id, label="A1 cold (cache off)")
    a2, _   = run_pass(model_id, label="A2 repeat (cache off)")

    # Pass B — cache enabled, cold pass populates, warm pass should hit.
    cache_set_default(True)
    cache_clear()
    b1, _   = run_pass(model_id, label="B1 cold (cache on)")
    b2, st  = run_pass(model_id, label="B2 warm (cache on)")
    print(f"\nfinal cache stats: {st}")

    # Markdown report.
    out = ROOT / "docs" / "prompt_cache_results.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Prompt Cache — Latency Measurement\n")
    lines.append(f"Model: `{model_id}`")
    lines.append("")
    lines.append("Each prompt runs four times in two passes:")
    lines.append("- **Pass A** keeps the cache OFF for both runs (control).")
    lines.append("- **Pass B** turns the cache ON: B1 populates, B2 should hit.")
    lines.append("")
    lines.append(
        "Only the **answer-generation step is cached**. The router still runs "
        "every time so chat history can change the routing decision; cache "
        "key includes the full message list, model id, max_tokens, and "
        "temperature."
    )
    lines.append("")

    headers = ["#", "Prompt",
               "A1 total (s)", "A2 total (s)",
               "B1 total (s)", "B2 total (s)", "Speedup B2/B1"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    a1_sum = a2_sum = b1_sum = b2_sum = 0.0
    for i, p in enumerate(PROMPTS, 1):
        speedup = b1[i-1]['total'] / b2[i-1]['total'] if b2[i-1]['total'] > 0 else 0
        lines.append(
            f"| {i} | {p[:55]} "
            f"| {a1[i-1]['total']:.2f} "
            f"| {a2[i-1]['total']:.2f} "
            f"| {b1[i-1]['total']:.2f} "
            f"| {b2[i-1]['total']:.2f} "
            f"| {speedup:.1f}× |"
        )
        a1_sum += a1[i-1]['total']
        a2_sum += a2[i-1]['total']
        b1_sum += b1[i-1]['total']
        b2_sum += b2[i-1]['total']
    lines.append(
        f"| **Σ** | **total** "
        f"| **{a1_sum:.2f}** | **{a2_sum:.2f}** "
        f"| **{b1_sum:.2f}** | **{b2_sum:.2f}** "
        f"| **{(b1_sum/b2_sum if b2_sum>0 else 0):.1f}×** |"
    )
    lines.append("")
    lines.append("## Takeaways")
    lines.append("")
    lines.append(
        f"- Pass A is the baseline — the same prompt re-issued without the cache "
        f"pays full LLM latency every time ({a1_sum:.1f}s + {a2_sum:.1f}s = "
        f"{a1_sum+a2_sum:.1f}s)."
    )
    lines.append(
        f"- Pass B with the cache on collapses the second pass to "
        f"{b2_sum:.2f}s (cache hits return in microseconds), so the "
        f"effective combined cost is {b1_sum + b2_sum:.1f}s vs "
        f"{a1_sum + a2_sum:.1f}s without — "
        f"**~{((a1_sum+a2_sum)/(b1_sum+b2_sum)) if (b1_sum+b2_sum) > 0 else 0:.1f}× "
        f"end-to-end speedup** when users re-issue similar queries."
    )
    lines.append(
        "- The cache is bounded (LRU, 256 entries) and keyed on the full "
        "message payload, so a follow-up that adds chat history is treated "
        "as a fresh prompt — no risk of stale answers."
    )
    lines.append("")
    lines.append(f"Final cache stats: `{st}`")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
