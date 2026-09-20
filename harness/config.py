

# ── model selection

SYSTEM_MODEL = "openai/gpt-oss-20b"
# 20 B params, ~1 000 t/s, json_schema strict-mode supported.
# Weakest of the three json_schema-capable Groq models → prompt changes
# move the score meaningfully instead of near-ceiling on every version.

JUDGE_MODEL = "qwen/qwen3.8-27b"
# Qwen/Alibaba family — different architecture from gpt-oss reduces
# self-preference bias (same-family judges inflate scores for that model's
# typical phrasing). Costs ~10× more per token, signalling stronger capability.

# ── list prices: USD per 1 M tokens (input, output)
# Free tier costs $0. These numbers go into ResultRow.cost_usd so runs are
# comparable to a paid-service baseline and costs across prompt versions can
# be compared even at zero actual spend.
# Source: console.groq.com/docs/models, checked 2026-09-20.
PRICES: dict[str, tuple[float, float]] = {
    #                               input    output  (per 1 M tokens)
    "openai/gpt-oss-20b":  (  0.075,   0.30),
    "openai/gpt-oss-120b": (  0.90,    3.50),  # not published; estimated from scale
    "qwen/qwen3.8-27b":    (  0.80,    4.00),
}
_DEFAULT_PRICE: tuple[float, float] = (0.90, 3.50)

# ── free-tier rate limits 
# All three json_schema-capable models share these limits on the free plan.
# Source: console.groq.com/docs/rate-limits, checked 2026-09-20.
FREE_RPM = 30        # requests / minute
FREE_RPD = 1_000     # requests / day
FREE_TPM = 8_000     # tokens   / minute
FREE_TPD = 200_000   # tokens   / day

# ── runner defaults
# 8 000 TPM ÷ ~380 tokens/call ≈ 21 safe calls/min; concurrency=2 leaves
# headroom so bursty calls don't trip the per-minute token limit.
DEFAULT_CONCURRENCY = 2
MAX_RETRIES         = 3
BASE_BACKOFF_S      = 2.0

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
