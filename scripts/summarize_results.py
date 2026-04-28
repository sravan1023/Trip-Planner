"""Print a per-prompt status table from docs/test_prompts_results.md."""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "docs" / "test_prompts_results.md").read_text(encoding="utf-8")
sections = re.split(r"^## ", text, flags=re.M)[1:]

for i, s in enumerate(sections, 1):
    title = s.splitlines()[0]
    status = "ERR" if "**ERROR" in s else "OK "
    elapsed = ""
    m = re.search(r"_elapsed: ([\d.]+)s_", s)
    if m:
        elapsed = m.group(1) + "s"
    chunks_match = re.search(r"RAG chunks \((\d+)\)", s)
    chunks = chunks_match.group(1) if chunks_match else "-"
    tools = re.findall(r"^- `([a-z_]+)\(", s, re.M)
    tool_str = ",".join(sorted(set(tools))) if tools else "(none)"
    print(f"{i:2d} {status} chunks={chunks:>2} {elapsed:>6}  {tool_str:<35}  {title[:55]}")
