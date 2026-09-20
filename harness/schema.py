
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

# ── canonical value sets 

Label = Literal["good", "bad"]
Split = Literal["dev", "test"]

# ── models


class GoldItem(BaseModel):
    """One row from data/golden_set.jsonl."""

    id: int
    split: Split
    customer_message: str   # input fed to the system model
    expected_label: Label   # generator reference (see data-quality notes)
    label_1: str = ""       # human labeller 1; "" until filled
    label_2: str = ""       # human labeller 2; "" until filled

    @field_validator("label_1", "label_2")
    @classmethod
    def _valid_human_label(cls, v: str) -> str:
        if v not in {"good", "bad", ""}:
            raise ValueError(f"human label must be 'good', 'bad', or '' — got {v!r}")
        return v


class SystemOutput(BaseModel):
    """
    JSON schema the system model must return.
    Use groq_json_schema(SystemOutput) to build the response_format= argument
    for client.chat.completions.create() — no free-text parsing anywhere.
    """

    reply: str


class JudgeResult(BaseModel):
    """LLM-judge verdict for one system reply."""

    grade: Label  # "good" | "bad" — the labelling guide's binary scale
    reason: str   # one sentence citing which criterion passed or failed


class ResultRow(BaseModel):
    """
    One row written to results/<run>.jsonl by the runner.
    score and reason are left None; the scorer fills them in.
    cost_usd is a hypothetical list-price cost (free tier costs $0).
    """

    id: int
    split: str
    input: str                    # customer_message passed to the system model
    output: Optional[str] = None  # reply produced by the model; None on error
    score: Optional[Label] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0         # hypothetical; actual spend is $0 on free tier
    prompt_version: str = ""
    model: str = ""
    timestamp: str = ""


# ── Groq response_format helper 


def groq_json_schema(model: type[BaseModel], strict: bool = True) -> dict:
    """
    Build the response_format dict for Groq's json_schema mode.

        response_format=groq_json_schema(SystemOutput)

    Works for any Pydantic model; used for both SystemOutput and JudgeResult.
    Set strict=False for models that don't support constrained decoding.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "strict": strict,
            "schema": model.model_json_schema(),
        },
    }


# ── I/O helpers


def load_jsonl(path: str | Path, model: type[BaseModel] | None = None) -> list:
    """
    Read a .jsonl file. If model is given, each line is validated into that
    Pydantic model; otherwise raw dicts are returned.
    """
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            rows.append(model(**data) if model else data)
    return rows


def write_jsonl(path: str | Path, rows: list[BaseModel]) -> None:
    """Overwrite path with one JSON object per line; creates parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(row.model_dump_json() + "\n")
