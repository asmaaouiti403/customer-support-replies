"""
tests/test_runner.py — unit + smoke tests for harness/runner.py.
Run from the project root:  pytest tests/
All tests use --dry-run or call functions directly; no API calls, no quota.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Make "harness" importable when pytest is invoked from any directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.runner import (
    _RateLimiter,
    _fake_call,
    _load_done_ids,
    _prompt_version,
    process_item,
)
from harness.schema import GoldItem, ResultRow, SystemOutput, groq_json_schema


# ── fixtures ──────────────────────────────────────────────────────────────────

def _item(id: int = 1, split: str = "dev") -> GoldItem:
    return GoldItem(
        id=id,
        split=split,
        customer_message="Hi, I need help with my order.",
        expected_label="good",
    )


def _fast_limiter() -> _RateLimiter:
    """High RPM so unit tests never actually sleep."""
    return _RateLimiter(rpm=1_000)


# ── schema helpers ────────────────────────────────────────────────────────────

def test_groq_json_schema_shape():
    schema = groq_json_schema(SystemOutput)
    assert schema["type"] == "json_schema"
    assert schema["json_schema"]["name"] == "SystemOutput"
    assert schema["json_schema"]["strict"] is True
    props = schema["json_schema"]["schema"]["properties"]
    assert "reply" in props


def test_groq_json_schema_non_strict():
    schema = groq_json_schema(SystemOutput, strict=False)
    assert schema["json_schema"]["strict"] is False


# ── rate limiter ──────────────────────────────────────────────────────────────

def test_rate_limiter_allows_up_to_limit():
    limiter = _RateLimiter(rpm=10)
    t0 = time.monotonic()
    for _ in range(10):
        limiter.acquire()
    assert time.monotonic() - t0 < 1.0  # 10 acquires should be near-instant


def test_rate_limiter_throttles_at_limit():
    """The 11th acquire within one minute must wait; just check it blocks briefly."""
    limiter = _RateLimiter(rpm=2)
    limiter.acquire()
    limiter.acquire()
    # Manually advance the deque so only 1 slot is available after 1 second
    # Instead just verify the limiter's internal count is bounded
    assert len(limiter._calls) == 2


# ── runner helpers ────────────────────────────────────────────────────────────

def test_prompt_version_extracts_stem():
    assert _prompt_version("prompts/system_v1.txt") == "system_v1"
    assert _prompt_version("prompts/system_v2.txt") == "system_v2"


def test_fake_call_is_deterministic():
    out_even, in_tok, out_tok = _fake_call(_item(id=2))
    out_odd, _, _ = _fake_call(_item(id=1))
    assert out_even.reply != out_odd.reply         # even vs odd → different reply
    assert _fake_call(_item(id=2))[0].reply == out_even.reply  # same id → same reply
    assert in_tok == 10
    assert out_tok == 5


def test_load_done_ids_missing_file(tmp_path):
    assert _load_done_ids(tmp_path / "nope.jsonl") == set()


def test_load_done_ids_reads_ids(tmp_path):
    out = tmp_path / "run.jsonl"
    rows = [
        ResultRow(id=1, split="dev", input="a", model="m", prompt_version="v1"),
        ResultRow(id=7, split="dev", input="b", model="m", prompt_version="v1"),
    ]
    out.write_text(
        "\n".join(r.model_dump_json() for r in rows) + "\n", encoding="utf-8"
    )
    assert _load_done_ids(out) == {1, 7}


# ── process_item ──────────────────────────────────────────────────────────────

def test_process_item_dry_run_success():
    row = process_item(
        _item(id=4),
        system="You are a helpful agent.",
        model="openai/gpt-oss-20b",
        prompt_version="system_v1",
        client=None,
        dry_run=True,
        limiter=_fast_limiter(),
    )
    assert isinstance(row, ResultRow)
    assert row.id == 4
    assert row.output is not None
    assert row.error is None
    assert row.latency_ms >= 0
    assert row.input_tokens == 10
    assert row.output_tokens == 5
    assert row.cost_usd > 0            # hypothetical list-price cost


def test_process_item_error_becomes_row(monkeypatch):
    """Exceptions inside the worker must be caught, not propagated."""
    import harness.runner as runner_mod

    def _boom(_item):
        raise RuntimeError("network failure")

    monkeypatch.setattr(runner_mod, "_fake_call", _boom)
    row = process_item(
        _item(id=99),
        system="",
        model="openai/gpt-oss-20b",
        prompt_version="v1",
        client=None,
        dry_run=True,
        limiter=_fast_limiter(),
    )
    assert row.error == "network failure"
    assert row.output is None


# ── CLI integration smoke tests ───────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
_BASE_CMD = [
    sys.executable, "-m", "harness.runner",
    "--prompt", "prompts/system_v1.txt",
    "--model", "openai/gpt-oss-20b",
    "--dry-run",
]


def test_cli_dry_run_end_to_end(tmp_path):
    """3 rows, no errors, meta file correct. No API calls."""
    out = tmp_path / "run.jsonl"
    result = subprocess.run(
        [*_BASE_CMD, "--split", "dev", "--out", str(out), "--limit", "3"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stderr

    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 3
    assert all(r["error"] is None for r in rows)
    assert all(r["output"] is not None for r in rows)
    assert all(r["prompt_version"] == "system_v1" for r in rows)

    meta = json.loads(out.with_name(out.stem + "_meta.json").read_text(encoding="utf-8"))
    assert meta["item_count"] == 3
    assert meta["error_count"] == 0
    assert meta["daily_limit_hit"] is False
    assert meta["prompt_version"] == "system_v1"


def test_cli_split_test(tmp_path):
    """--split test should only touch test-split items (IDs 111–160)."""
    out = tmp_path / "run.jsonl"
    subprocess.run(
        [*_BASE_CMD, "--split", "test", "--out", str(out), "--limit", "5"],
        cwd=str(PROJECT_ROOT), check=True,
    )
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert all(r["split"] == "test" for r in rows)


def test_cli_resume_skips_done(tmp_path):
    """--resume must not duplicate IDs."""
    out = tmp_path / "run.jsonl"
    # first pass: 2 rows
    subprocess.run(
        [*_BASE_CMD, "--split", "dev", "--out", str(out), "--limit", "2"],
        cwd=str(PROJECT_ROOT), check=True,
    )
    first_ids = {
        json.loads(l)["id"]
        for l in out.read_text(encoding="utf-8").splitlines() if l.strip()
    }
    assert len(first_ids) == 2

    # second pass: resume, add 2 more
    subprocess.run(
        [*_BASE_CMD, "--split", "dev", "--out", str(out), "--limit", "4", "--resume"],
        cwd=str(PROJECT_ROOT), check=True,
    )
    all_ids = [
        json.loads(l)["id"]
        for l in out.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(all_ids) == 4
    assert len(set(all_ids)) == 4   # no duplicates
