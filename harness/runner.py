
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError
from pydantic import ValidationError

from harness.config import (
    BASE_BACKOFF_S,
    DEFAULT_CONCURRENCY,
    GROQ_BASE_URL,
    MAX_RETRIES,
    PRICES,
    SYSTEM_MODEL,
    _DEFAULT_PRICE,
)
from harness.schema import GoldItem, ResultRow, SystemOutput, groq_json_schema, load_jsonl


# Others fall back to json_object mode + pydantic validation.
_JSON_SCHEMA_MODELS = frozenset({
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
})


# ── daily-limit sentinel

class _DailyLimitReached(Exception):
    pass


# ── rate limiter

class _RateLimiter:
    """Thread-safe sliding-window RPM limiter."""

    def __init__(self, rpm: int) -> None:
        self._limit = rpm
        self._calls: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0
                while self._calls and self._calls[0] < cutoff:
                    self._calls.popleft()
                if len(self._calls) < self._limit:
                    self._calls.append(now)
                    return
                wait = 60.0 - (now - self._calls[0]) + 0.05
            time.sleep(wait)  # release lock before sleeping


# ── API call

def _api_call(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    limiter: _RateLimiter,
) -> tuple[SystemOutput, int, int]:
    """One Groq call with backoff. Returns (output, input_tokens, output_tokens)."""
    use_schema = model in _JSON_SCHEMA_MODELS
    fmt = groq_json_schema(SystemOutput) if use_schema else {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        limiter.acquire()
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=512,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                response_format=fmt,
            )
            content = resp.choices[0].message.content
            try:
                output = SystemOutput.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError, ValueError):
                # json_object mode has no schema guarantee; retry without sleeping
                if attempt < MAX_RETRIES - 1:
                    continue
                raise ValueError(f"invalid output after {MAX_RETRIES} attempts: {content!r}")
            return output, resp.usage.prompt_tokens, resp.usage.completion_tokens

        except RateLimitError as e:
            if "day" in str(e).lower():
                raise _DailyLimitReached(str(e))
            wait = BASE_BACKOFF_S * 2 ** attempt
            try:
                wait = float(e.response.headers["retry-after"])
            except (AttributeError, KeyError, ValueError):
                pass
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(wait)

        except (InternalServerError, APIConnectionError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(BASE_BACKOFF_S * 2 ** attempt)


def _fake_call(item: GoldItem) -> tuple[SystemOutput, int, int]:
    """Deterministic stand-in for --dry-run; uses no quota."""
    reply = (
        "Thank you for reaching out. We will resolve this shortly."
        if item.id % 2 == 0
        else "We are unable to assist with that request."
    )
    return SystemOutput(reply=reply), 10, 5


# ── per-item worker

def process_item(
    item: GoldItem,
    system: str,
    model: str,
    prompt_version: str,
    client: OpenAI | None,
    dry_run: bool,
    limiter: _RateLimiter,
) -> ResultRow:
    """Call model for one item. _DailyLimitReached propagates; all other exceptions become error rows."""
    t0 = time.perf_counter()
    try:
        if dry_run:
            out, in_tok, out_tok = _fake_call(item)
        else:
            out, in_tok, out_tok = _api_call(client, model, system, item.customer_message, limiter)

        in_p, out_p = PRICES.get(model, _DEFAULT_PRICE)
        return ResultRow(
            id=item.id,
            split=item.split,
            input=item.customer_message,
            output=out.reply,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round((in_tok * in_p + out_tok * out_p) / 1_000_000, 6),
            prompt_version=prompt_version,
            model=model,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except _DailyLimitReached:
        raise
    except Exception as exc:
        return ResultRow(
            id=item.id,
            split=item.split,
            input=item.customer_message,
            error=str(exc),
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            prompt_version=prompt_version,
            model=model,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ── small helpers 

def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _prompt_version(path: str) -> str:
    return Path(path).stem


def _load_done_ids(out_path: Path) -> set[int]:
    """Return IDs already written to out_path (used by --resume)."""
    if not out_path.exists():
        return set()
    done: set[int] = set()
    with open(out_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["id"])
                except (KeyError, json.JSONDecodeError):
                    pass
    return done


# ── CLI

def main() -> None:
    p = argparse.ArgumentParser(description="Run the system model over the golden set.")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--prompt", required=True, help="Path to system prompt .txt file")
    p.add_argument("--model", default=SYSTEM_MODEL)
    p.add_argument("--out", required=True, help="Output .jsonl path")
    p.add_argument("--limit", type=int, default=None, help="Cap number of items processed")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                   help=f"Parallel API threads (default {DEFAULT_CONCURRENCY}; keep low for free-tier TPM)")
    p.add_argument("--resume", action="store_true", help="Skip IDs already present in --out")
    p.add_argument("--dry-run", action="store_true", help="Fake model — no API calls, no quota")
    args = p.parse_args()

    system = Path(args.prompt).read_text(encoding="utf-8")
    prompt_version = _prompt_version(args.prompt)

    items: list[GoldItem] = load_jsonl("data/golden_set.jsonl", GoldItem)
    if args.split != "all":
        items = [i for i in items if i.split == args.split]

    out_path = Path(args.out)
    if args.resume:
        done = _load_done_ids(out_path)
        items = [i for i in items if i.id not in done]
        print(f"resume: {len(done)} already done, {len(items)} remaining")

    if args.limit:
        items = items[: args.limit]

    client = (
        None if args.dry_run
        else OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)
    )
    # 25 RPM < free-tier 30 RPM cap; also keeps TPM well under 8 000 at concurrency=2
    limiter = _RateLimiter(rpm=25)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_start = time.perf_counter()
    total_cost = 0.0
    total_in = total_out = error_count = written = 0
    daily_limit_hit = False

    with open(out_path, "a" if args.resume else "w", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {
                pool.submit(
                    process_item,
                    item, system, args.model, prompt_version, client, args.dry_run, limiter,
                ): item
                for item in items
            }
            for n, future in enumerate(as_completed(futures), 1):
                try:
                    row = future.result()
                except _DailyLimitReached as e:
                    print(f"\n[STOP] Daily quota reached: {e}")
                    print(f"       Run again tomorrow with:  --resume --out {args.out}")
                    daily_limit_hit = True
                    break

                fh.write(row.model_dump_json() + "\n")
                fh.flush()
                written += 1
                total_cost  += row.cost_usd
                total_in    += row.input_tokens
                total_out   += row.output_tokens
                error_count += bool(row.error)
                tag = "ERR" if row.error else " ok"
                print(f"[{tag}] id={row.id:>4}  ${total_cost:.4f}  {n}/{len(items)}")

    meta = {
        "model":                  args.model,
        "prompt_version":         prompt_version,
        "git_commit":             _git_commit(),
        "split":                  args.split,
        "item_count":             written,
        "error_count":            error_count,
        "input_tokens":           total_in,
        "output_tokens":          total_out,
        "hypothetical_cost_usd":  round(total_cost, 6),
        "total_time_s":           round(time.perf_counter() - run_start, 2),
        "daily_limit_hit":        daily_limit_hit,
        "timestamp":              datetime.now(timezone.utc).isoformat(),
    }
    meta_path = out_path.with_name(out_path.stem + "_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\n→ {out_path}  (rows={written}, errors={error_count}, "
          f"tokens={total_in + total_out}, cost=${total_cost:.4f})")
    print(f"→ {meta_path}")


if __name__ == "__main__":
    main()
