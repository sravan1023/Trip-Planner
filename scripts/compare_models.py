"""Run the same 5 prompts on the small (Llama 3.1 8B) and large
(Llama 3.3 70B) Groq models, then compare latency, citation count, answer
length, and qualitative behavior. Output: docs/model_comparison.md."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from config import MODELS                                    # noqa: E402
from agent.pipeline import (                                 # noqa: E402
    route_query, execute_tools, generate_response, generate, cache_clear,
)
from agent.prompts import RESPONSE_SYSTEM_PROMPT             # noqa: E402

# Five prompts spanning RAG-only, RAG-with-filter, multi-tool, live tools.
PROMPTS = [
    "Best ramen in San Francisco",
    "Suggest a weekend trip from San Francisco",
    "What will the weather be like in Honolulu tomorrow?",
    "Are there any travel advisories for Mexico right now?",
    "Plan a 5-day trip within a $1200 total budget",
]


def count_citations(text: str) -> int:
    return len(set(re.findall(r"\[(\d+)\]", text or "")))


def run(model_id: str, prompt: str) -> dict:
    t0 = time.time()
    calls = route_query(model_id, prompt, history=[])
    t_router = time.time() - t0

    tool_results, rag_chunks = execute_tools(calls)

    t1 = time.time()
    if not tool_results:
        answer = generate(
            model_id,
            [{"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            max_new_tokens=500,
            use_cache=False,
        )
    else:
        answer = generate_response(
            model_id, prompt, tool_results,
            rag_chunks=rag_chunks, history=[], stream=False,
        )
    t_answer = time.time() - t1

    return {
        "prompt": prompt,
        "calls": calls,
        "rag_chunks": len(rag_chunks),
        "answer": answer,
        "answer_len": len(answer or ""),
        "citations": count_citations(answer),
        "t_router": round(t_router, 2),
        "t_answer": round(t_answer, 2),
        "t_total": round(t_router + t_answer, 2),
    }


def fmt_calls(calls: list[dict]) -> str:
    if not calls:
        return "(none)"
    return ", ".join(f"{c.get('tool')}({c.get('args')})" for c in calls)


def main() -> None:
    fast_id = MODELS["Fast"]
    deep_id = MODELS["Thinking"]
    print(f"Fast = {fast_id}\nDeep = {deep_id}")

    cache_clear()  # ensure cold runs for both models
    fast_rows: list[dict] = []
    deep_rows: list[dict] = []

    def _safe_run(model_id: str, prompt: str) -> dict:
        try:
            return run(model_id, prompt)
        except Exception as e:
            print(f"    ERROR: {type(e).__name__}: {e}")
            return {"prompt": prompt, "calls": [], "rag_chunks": 0,
                    "answer": f"[error: {e}]",
                    "answer_len": 0, "citations": 0,
                    "t_router": 0.0, "t_answer": 0.0, "t_total": 0.0}

    for i, p in enumerate(PROMPTS, 1):
        print(f"\n[{i}/{len(PROMPTS)}] {p}")
        print("  fast…")
        fast_rows.append(_safe_run(fast_id, p))
        print(f"    {fast_rows[-1]['t_total']}s, {fast_rows[-1]['citations']} citations, "
              f"{fast_rows[-1]['answer_len']} chars")
        # Cool-down between models so we don't burn the 8B TPM budget.
        time.sleep(3.0)
        print("  deep…")
        deep_rows.append(_safe_run(deep_id, p))
        print(f"    {deep_rows[-1]['t_total']}s, {deep_rows[-1]['citations']} citations, "
              f"{deep_rows[-1]['answer_len']} chars")
        time.sleep(3.0)

    out = ROOT / "docs" / "model_comparison.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Two-Model Comparison — Llama 3.1 8B vs Llama 3.3 70B\n")
    lines.append(f"Fast model: `{fast_id}` (8B parameters, instant tier)")
    lines.append(f"Deep model: `{deep_id}` (70B parameters, versatile tier)")
    lines.append("")
    lines.append(
        "Both models run the same router prompt, hit the same RAG/live tools, "
        "and use the same response prompt. Differences below are purely "
        "model-quality differences."
    )
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| Metric | 8B (Fast) | 70B (Deep) |")
    lines.append("|---|---|---|")
    fast_tot = sum(r["t_total"] for r in fast_rows)
    deep_tot = sum(r["t_total"] for r in deep_rows)
    fast_ans = sum(r["answer_len"] for r in fast_rows)
    deep_ans = sum(r["answer_len"] for r in deep_rows)
    fast_cit = sum(r["citations"] for r in fast_rows)
    deep_cit = sum(r["citations"] for r in deep_rows)
    lines.append(f"| Total wall time (5 prompts) | {fast_tot:.1f}s | {deep_tot:.1f}s |")
    lines.append(f"| Avg per prompt | {fast_tot/len(PROMPTS):.1f}s | {deep_tot/len(PROMPTS):.1f}s |")
    lines.append(f"| Total answer chars | {fast_ans} | {deep_ans} |")
    lines.append(f"| Total citations emitted | {fast_cit} | {deep_cit} |")
    lines.append("")
    lines.append("## Per-prompt detail")
    lines.append("")
    lines.append("| # | Prompt | 8B time | 70B time | 8B cites | 70B cites | 8B chars | 70B chars |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, p in enumerate(PROMPTS, 1):
        f = fast_rows[i-1]; d = deep_rows[i-1]
        lines.append(
            f"| {i} | {p[:55]} "
            f"| {f['t_total']:.1f}s | {d['t_total']:.1f}s "
            f"| {f['citations']} | {d['citations']} "
            f"| {f['answer_len']} | {d['answer_len']} |"
        )
    lines.append("")

    for i, p in enumerate(PROMPTS, 1):
        f = fast_rows[i-1]; d = deep_rows[i-1]
        lines.append("---")
        lines.append("")
        lines.append(f"## {i}. {p}")
        lines.append("")
        lines.append(f"**Routing (same for both):** {fmt_calls(f['calls'])}")
        lines.append(f"**RAG chunks retrieved:** {f['rag_chunks']}")
        lines.append("")
        lines.append("### 8B (Fast)")
        lines.append(f"_t={f['t_total']}s · citations={f['citations']} · chars={f['answer_len']}_")
        lines.append("")
        ans_f = f["answer"]
        if len(ans_f) > 1200:
            ans_f = ans_f[:1200] + "…"
        lines.append(ans_f)
        lines.append("")
        lines.append("### 70B (Deep)")
        lines.append(f"_t={d['t_total']}s · citations={d['citations']} · chars={d['answer_len']}_")
        lines.append("")
        ans_d = d["answer"]
        if len(ans_d) > 1200:
            ans_d = ans_d[:1200] + "…"
        lines.append(ans_d)
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
