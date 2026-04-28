"""Quick sanity check that the San Jose home-location anchoring took effect.
Prints router decisions only — no LLM answer call, so it's cheap."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from config import MODELS                   # noqa: E402
from agent.pipeline import route_query      # noqa: E402

PROMPTS = [
    "Suggest a weekend trip",
    "Where should I go this weekend?",
    "Plan a 3 day trip",
    "Recommend a city I can visit under a $150 daily budget",
    "Travel destinations within the United States",
    "Nature destinations suitable for summer travel",
    "Suggest a weekend trip from San Francisco",  # explicit origin - should override
    "Plan a 3 day trip to seattle",               # explicit destination - should override
]

model_id = MODELS["Fast"]
for p in PROMPTS:
    calls = route_query(model_id, p, history=[])
    print(f"\n{p!r}")
    for c in calls:
        print(f"  -> {c.get('tool')}({c.get('args')})")
