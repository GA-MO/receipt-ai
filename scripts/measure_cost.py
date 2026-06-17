"""Measure real per-receipt token usage + cost for gemini-3.1-flash-lite.

Calls OpenRouter directly with the production system instruction + prompt + image
so we capture exact prompt/cached/completion tokens, then apply lite pricing.

Usage: cd backend && .venv/bin/python ../scripts/measure_cost.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import llm_client  # noqa: E402
from app.services.extraction import EXTRACTION_PROMPT, build_system_instruction  # noqa: E402

settings.openrouter_model = "google/gemini-3.1-flash-lite"
llm_client.reset_openai_client()

# lite pricing $/token
P_IN, P_CACHED, P_OUT = 0.25 / 1e6, 0.025 / 1e6, 1.5 / 1e6
DATA = ROOT / "dataTest" / "demo"
IMAGES = ["25a_sudaphanij_baseline_1.jpeg", "11.jpeg", "17_multi_category_large.jpeg"]

sysi = build_system_instruction()
client = llm_client._get_openai_client()  # noqa: SLF001


def call(img: Path):
    b64 = base64.b64encode(img.read_bytes()).decode()
    messages = [
        {"role": "system", "content": [{"type": "text", "text": sysi, "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [
            {"type": "text", "text": EXTRACTION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ]
    r = client.chat.completions.create(model=settings.openrouter_model, messages=messages,
                                       temperature=0.1, response_format={"type": "json_object"})
    u = r.usage
    cached = 0
    if u.prompt_tokens_details:
        cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
    return u.prompt_tokens, cached, u.completion_tokens


def cost(prompt, cached, comp):
    return (prompt - cached) * P_IN + cached * P_CACHED + comp * P_OUT


print(f"model: {settings.openrouter_model}")
print(f"system instruction (cached prefix) ~ {len(sysi)} chars\n")
print(f"{'image':<36} {'prompt':>7} {'cached':>7} {'out':>6} {'$cold':>9} {'$warm':>9}")
print("-" * 80)
warm_costs = []
for i, name in enumerate(IMAGES):
    p, c, o = call(DATA / name)
    c_cold = cost(p, 0, o)         # no cache (first ever call)
    c_warm = cost(p, c, o)         # with reported cache hit
    print(f"{name:<36} {p:>7} {c:>7} {o:>6} ${c_cold:>8.5f} ${c_warm:>8.5f}")
    if i > 0:  # first call warms the cache; later calls are steady-state
        warm_costs.append(c_warm)
print("-" * 80)
if warm_costs:
    avg = sum(warm_costs) / len(warm_costs)
    print(f"avg steady-state cost/receipt (cache warm): ${avg:.5f}  (~{avg*36:.4f} THB @ 36)")
