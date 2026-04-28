"""Run a fixed list of test prompts through the agent and dump results to
docs/test_prompts_results.md. Each prompt gets its own section with the
router's tool-call decision, the RAG chunks surfaced, and the final answer."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Quiet TensorFlow / oneDNN noise that the chromadb stack pulls in.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

from config import MODELS                       # noqa: E402
from rag.ingest import run_full_ingest          # noqa: E402
from rag.vector_store import collection_count   # noqa: E402
from agent.pipeline import route_query, execute_tools, generate_response  # noqa: E402
from agent.tools import TOOLS                   # noqa: E402

PROMPTS = [
    "Recommend a city I can visit under a $150 daily budget",
    "Suggest a weekend trip from San Francisco",
    "Nature destinations suitable for summer travel",
    "Plan a 3 day trip to seattle",
    "Travel destinations within the United States",
    "Find hotels in Tokyo under $200 per night",
    "Best rated hotels in New York under $100",
    "Cheapest flights from SFO to Las Vegas",
    "Compare hotels available in Las Vegas",
    "What attractions are available in Barcelona?",
    "Shortest flights from San Francisco to New York",
    "Cheapest attractions to visit in London",
    "How long does a typical visit to the Louvre Museum take?",
    "Create a one-day itinerary for New York City.",
    "What will the weather be like in Hawaii tomorrow?",
    "Do U.S citizens need a visa to travel to Europe?",
    "Are there any travel advisories for Mexico right now?",
    "Best time of year to visit Iceland?",
    "Plan a 5-day trip within a $1200 total budget",
    "Build a complete itinerary for hotel and attractions for a 5-day trip to Tokyo",
]


# Allow running a subset via env var, e.g. PROMPT_RANGE=10-20
def _slice_prompts() -> list[tuple[int, str]]:
    rng = os.environ.get("PROMPT_RANGE", "")
    if "-" not in rng:
        return list(enumerate(PROMPTS, 1))
    a, b = rng.split("-", 1)
    a, b = int(a), int(b)
    return [(i, PROMPTS[i - 1]) for i in range(a, b + 1)]


def ensure_indexed() -> int:
    n = collection_count()
    if n > 0:
        return n
    print(f"[ingest] empty collection — running full ingest (this takes ~30s)")
    res = run_full_ingest()
    return res.get("total", 0)


def fmt_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "_(none)_"
    lines = []
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata") or {}
        m_bits = []
        for k in ("city", "state", "section", "type"):
            if meta.get(k):
                m_bits.append(f"{k}={meta[k]}")
        m = " | ".join(m_bits)
        text = (c.get("text") or "").replace("\n", " ").strip()
        if len(text) > 240:
            text = text[:240] + "…"
        lines.append(
            f"- **[{i}]** `{c.get('source','?')}` · score={c.get('score')}  "
            f"{('· ' + m) if m else ''}\n  > {text}"
        )
    return "\n".join(lines)


def fmt_tool_calls(calls: list[dict]) -> str:
    if not calls:
        return "_(no tools — direct LLM answer)_"
    out = []
    for c in calls:
        args = c.get("args", {})
        out.append(f"- `{c.get('tool','?')}({args})`")
    return "\n".join(out)


def run_one(model_id: str, prompt: str) -> dict:
    t0 = time.time()
    try:
        calls = route_query(model_id, prompt, history=[])
    except Exception as e:
        return {"prompt": prompt, "error": f"router: {type(e).__name__}: {e}"}

    try:
        tool_results, rag_chunks = execute_tools(calls)
    except Exception as e:
        return {"prompt": prompt, "calls": calls,
                "error": f"tools: {type(e).__name__}: {e}"}

    try:
        if not tool_results:
            from agent.pipeline import generate
            from agent.prompts import RESPONSE_SYSTEM_PROMPT
            answer = generate(
                model_id,
                [{"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
                 {"role": "user", "content": prompt}],
                max_new_tokens=500,
            )
        else:
            answer = generate_response(
                model_id, prompt, tool_results,
                rag_chunks=rag_chunks, history=[], stream=False,
            )
    except Exception as e:
        return {"prompt": prompt, "calls": calls, "rag": rag_chunks,
                "error": f"answer: {type(e).__name__}: {e}"}

    return {
        "prompt": prompt,
        "calls": calls,
        "rag": rag_chunks,
        "answer": answer,
        "elapsed": round(time.time() - t0, 1),
    }


def main() -> None:
    n = ensure_indexed()
    print(f"[index] collection size = {n}")

    model_id = MODELS["Fast"]
    print(f"[model] {model_id}")

    out = ROOT / "docs" / "test_prompts_results.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    selected = _slice_prompts()

    # If the file already has earlier sections (partial prior run), append to it
    # instead of clobbering. Otherwise write the header.
    if out.exists() and selected[0][0] > 1:
        existing = out.read_text(encoding="utf-8")
        # Strip the trailing newline so our `---` join cleanly.
        lines = [existing.rstrip()]
        lines.append("")
    else:
        lines = []
        lines.append("# Test Prompt Results")
        lines.append("")
        lines.append(f"Model: `{model_id}`  ·  Index size: **{n}** chunks  ·  "
                     f"Run: {time.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append("Each prompt is exercised end-to-end: router → tool execution "
                     "→ grounded response. RAG chunks are shown with their metadata "
                     "so you can verify filtering, citations, and grounding work.")
        lines.append("")

    for i, prompt in selected:
        print(f"\n[{i}/{len(PROMPTS)}] {prompt!r}", flush=True)
        r = run_one(model_id, prompt)
        lines.append("---")
        lines.append("")
        lines.append(f"## {i}. {prompt}")
        lines.append("")
        if "error" in r:
            print(f"   ERROR: {r['error']}", flush=True)
            lines.append(f"**ERROR:** {r['error']}")
            lines.append("")
            if r.get("calls"):
                lines.append("**Router decided:**")
                lines.append(fmt_tool_calls(r["calls"]))
                lines.append("")
        else:
            lines.append(f"_elapsed: {r['elapsed']}s_")
            lines.append("")
            lines.append("**Router decided:**")
            lines.append(fmt_tool_calls(r["calls"]))
            lines.append("")
            lines.append(f"**RAG chunks ({len(r['rag'])}):**")
            lines.append(fmt_chunks(r["rag"]))
            lines.append("")
            lines.append("**Answer:**")
            lines.append("")
            lines.append(r["answer"])
            lines.append("")

        # Always flush after every iteration so errors are preserved too.
        out.write_text("\n".join(lines), encoding="utf-8")
        # Be a polite citizen — small spacing between LLM calls.
        time.sleep(1.0)

    print(f"\nwrote {out}", flush=True)


if __name__ == "__main__":
    main()
