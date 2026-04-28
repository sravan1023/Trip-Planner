from __future__ import annotations
import hashlib
import inspect
import json
import os
import re
import time
from collections import OrderedDict

from groq import Groq, RateLimitError

from config import GROQ_API_KEY
from agent.tools import TOOLS, TOOL_DESCRIPTIONS
from agent.prompts import build_router_prompt, RESPONSE_SYSTEM_PROMPT

_client: Groq | None = None


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


# ── Prompt cache ──────────────────────────────────────────────────────────────
# Bounded LRU keyed on (model_id, messages, max_tokens, temperature). Skipped
# for streaming (no value in caching a generator) and for temperature > 0.0
# (a non-zero temperature is by definition asking for sampling diversity, so
# returning a cached response would defeat the user's intent — except in our
# router/grading path where temperature=0.1 is effectively deterministic, in
# which case the cache is still useful).

_CACHE_MAX = 256
_cache: "OrderedDict[str, str]" = OrderedDict()
_cache_stats = {"hits": 0, "misses": 0, "skips": 0}


def _cache_key(model_id: str, messages: list[dict], max_new_tokens: int, temperature: float) -> str:
    payload = json.dumps(
        {"m": model_id, "msgs": messages, "n": max_new_tokens, "t": round(temperature, 3)},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_clear() -> None:
    _cache.clear()
    _cache_stats.update(hits=0, misses=0, skips=0)


def cache_stats() -> dict:
    return {**_cache_stats, "size": len(_cache)}


def cache_set_default(enabled: bool) -> None:
    """Flip the cache default at runtime. Affects all `generate()` calls that
    don't pass an explicit `use_cache` argument — including indirect calls
    via `route_query()` and `generate_response()`."""
    global _CACHE_DEFAULT
    _CACHE_DEFAULT = bool(enabled)


# Default cache state can be flipped via env var so timing scripts can run
# A/B comparisons without editing source.
_CACHE_DEFAULT = os.environ.get("PROMPT_CACHE", "1") not in ("0", "false", "False", "")


# Groq's free tier enforces tokens-per-minute limits (e.g. 6000 TPM on the
# 8B model). The API tells us how long to wait — honor that instead of
# crashing the caller.
_RETRY_WAIT_RE = re.compile(r"try again in ([\d.]+)s", re.I)
_MAX_RETRIES = 5


def _create_with_retry(client: Groq, model_id: str, messages: list[dict],
                       max_new_tokens: int, temperature: float):
    delay = 2.0
    for attempt in range(_MAX_RETRIES):
        try:
            return client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_new_tokens,
                temperature=temperature,
            )
        except RateLimitError as e:
            msg = str(e)
            m = _RETRY_WAIT_RE.search(msg)
            wait = float(m.group(1)) + 0.5 if m else delay
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(wait)
            delay = min(delay * 2, 30.0)


def generate(
    model_id: str,
    messages: list[dict],
    max_new_tokens: int = 512,
    temperature: float = 0.7,
    stream: bool = False,
    use_cache: bool | None = None,
):
    client = get_client()
    if stream:
        _cache_stats["skips"] += 1
        response_stream = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_new_tokens,
            temperature=temperature,
            stream=True,
        )

        def _delta_gen():
            for chunk in response_stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        return _delta_gen()

    cache_on = _CACHE_DEFAULT if use_cache is None else use_cache
    key = _cache_key(model_id, messages, max_new_tokens, temperature) if cache_on else None
    if key is not None and key in _cache:
        _cache.move_to_end(key)
        _cache_stats["hits"] += 1
        return _cache[key]

    response = _create_with_retry(
        client, model_id, messages, max_new_tokens, temperature,
    )
    text = response.choices[0].message.content.strip()

    if key is not None:
        _cache[key] = text
        _cache.move_to_end(key)
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
        _cache_stats["misses"] += 1
    else:
        _cache_stats["skips"] += 1
    return text


def route_query(model_id: str, user_query: str, history: list[dict] | None = None) -> list[dict]:
    router_prompt = build_router_prompt(TOOL_DESCRIPTIONS)
    contextual_query = user_query
    if history:
        recent = history[-6:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        contextual_query = (
            f"Conversation so far:\n{history_text}\n\n"
            f"Latest user message: {user_query}\n\n"
            "Decide tool calls based on the FULL conversation context, not just the latest message."
        )
    messages = [
        {"role": "system", "content": router_prompt},
        {"role": "user", "content": contextual_query},
    ]
    raw = generate(model_id, messages, max_new_tokens=300, temperature=0.1)
    try:
        start = raw.index("[")
        end = raw.rindex("]") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return []


def _filter_args(fn, args: dict) -> tuple[dict, list[str]]:
    """Keep only args the function accepts; report dropped ones."""
    if not isinstance(args, dict):
        return {}, []
    accepted = set(inspect.signature(fn).parameters.keys())
    safe = {k: v for k, v in args.items() if k in accepted}
    dropped = [k for k in args if k not in accepted]
    return safe, dropped


def execute_tools(tool_calls: list[dict]) -> tuple[dict, list[dict]]:
    tool_results = {}
    rag_chunks = []
    for call in tool_calls:
        name = call.get("tool", "")
        args = call.get("args", {})
        if name not in TOOLS:
            tool_results[name] = {"error": f"Unknown tool: {name}"}
            continue
        fn = TOOLS[name]["fn"]
        safe_args, dropped = _filter_args(fn, args)
        try:
            result = fn(**safe_args)
        except Exception as exc:
            tool_results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        tool_results[name] = result
        if dropped:
            tool_results.setdefault("_warnings", []).append(
                f"{name}: dropped unsupported args {dropped}"
            )
        if name == "semantic_search" and isinstance(result, list):
            rag_chunks.extend(result)
    return tool_results, rag_chunks


def _format_rag_chunks(chunks: list[dict]) -> str:
    """Render RAG hits as a numbered list. Indices match the [N] citation
    labels shown in the UI so the model's `[1]` / `[2]` references resolve."""
    lines = []
    for i, c in enumerate(chunks, 1):
        source = c.get("source", "unknown")
        text = (c.get("text") or "").strip()
        score = c.get("score", "")
        lines.append(f"[{i}] {source}  (score={score})\n{text}")
    return "\n\n".join(lines)


def generate_response(
    model_id: str,
    user_query: str,
    tool_results: dict,
    rag_chunks: list[dict] | None = None,
    history: list[dict] | None = None,
    stream: bool = False,
):
    rag_chunks = rag_chunks or []
    # Pull RAG chunks out of the JSON dump so they get presented as a numbered
    # list the model can cite. Other tool results stay as JSON.
    other = {k: v for k, v in tool_results.items() if k != "semantic_search"}
    context_blocks: list[str] = []
    if rag_chunks:
        context_blocks.append(
            "Knowledge base passages (cite inline as [1], [2], etc. matching the "
            "indices below):\n\n" + _format_rag_chunks(rag_chunks)
        )
    else:
        context_blocks.append("Knowledge base passages: NONE — no relevant chunks were retrieved.")
    if other:
        context_blocks.append("Other tool results:\n" + json.dumps(other, indent=2, default=str))
    context = "\n\n".join(context_blocks)

    messages = [{"role": "system", "content": RESPONSE_SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-6:])
    messages.append({
        "role": "user",
        "content": (
            f"{user_query}\n\n"
            f"{context}\n\n"
            "Use the passages above to answer. Cite specific facts inline with their "
            "[N] index. If the passages do NOT cover what the user asked for "
            "(e.g. they asked about California but passages are about Bali), say so "
            "explicitly before falling back to general knowledge."
        ),
    })
    return generate(model_id, messages, max_new_tokens=700, stream=stream)


def run_agent(
    user_query: str,
    model_id: str,
    history: list[dict] | None = None,
    stream: bool = False,
) -> tuple:
    history = history or []
    tool_calls = route_query(model_id, user_query, history=history)
    tool_results, rag_chunks = execute_tools(tool_calls)

    if not tool_results:
        messages = [{"role": "system", "content": RESPONSE_SYSTEM_PROMPT}]
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": user_query})
        response = generate(model_id, messages, max_new_tokens=500, stream=stream)
    else:
        response = generate_response(
            model_id, user_query, tool_results,
            rag_chunks=rag_chunks, history=history, stream=stream,
        )

    return response, rag_chunks
