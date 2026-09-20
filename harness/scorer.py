from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError
from pydantic import ValidationError

from harness.config import (
    BASE_BACKOFF_S,
    GROQ_BASE_URL,
    JUDGE_MODEL,
    MAX_RETRIES,
)
from harness.schema import JudgeResult, ResultRow, load_jsonl, write_jsonl
def _judge_json_schema() -> dict:
    schema = JudgeResult.model_json_schema()

    def fix_object_schema(obj: dict) -> None:
        if obj.get("type") == "object":
            obj["additionalProperties"] = False

            for value in obj.get("properties", {}).values():
                if isinstance(value, dict):
                    fix_object_schema(value)

        for value in obj.get("$defs", {}).values():
            if isinstance(value, dict):
                fix_object_schema(value)

    fix_object_schema(schema)

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "JudgeResult",
            "strict": True,
            "schema": schema,
        },
    }

def _api_call(
    client: OpenAI,
    system: str,
    user: str,
) -> JudgeResult:
    """Call the judge model and validate its JSON response."""

    fmt = _judge_json_schema()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=JUDGE_MODEL,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=fmt,
            )

            content = response.choices[0].message.content

            try:
                return JudgeResult.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError, ValueError):
                if attempt < MAX_RETRIES - 1:
                    continue
                raise ValueError(
                    f"Invalid judge output after {MAX_RETRIES} attempts: {content!r}"
                )

        except RateLimitError:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(BASE_BACKOFF_S * 2 ** attempt)

        except (InternalServerError, APIConnectionError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(BASE_BACKOFF_S * 2 ** attempt)


def _build_user_prompt(row: ResultRow) -> str:
    """Build the information given to the judge for one result row."""

    return (
        "Customer message:\n"
        f"{row.input}\n\n"
        "Assistant reply:\n"
        f"{row.output or ''}"
    )


def score_file(
    input_path: str,
    output_path: str,
    judge_prompt_path: str,
) -> None:
    """Score every result row in a JSONL file."""

    judge_prompt = Path(judge_prompt_path).read_text(encoding="utf-8")

    rows: list[ResultRow] = load_jsonl(input_path, ResultRow)

    client = OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url=GROQ_BASE_URL,
    )

    scored = 0
    errors = 0

    output_rows: list[ResultRow] = []

    for n, row in enumerate(rows, 1):
        if row.error or row.output is None:
            output_rows.append(row)
            errors += 1
            print(f"[SKIP] id={row.id:>4}  ({n}/{len(rows)})")
            continue

        try:
            judge_result = _api_call(
                client,
                judge_prompt,
                _build_user_prompt(row),
            )

            row.score = judge_result.grade
            row.reason = judge_result.reason

            # Estimate hypothetical judge cost from token usage.
            # The current ResultRow does not store judge token counts,
            # so the scorer only records the score/reason here.
            scored += 1

            print(
                f"[ ok] id={row.id:>4}  "
                f"score={row.score}  "
                f"({n}/{len(rows)})"
            )

        except Exception as exc:
            row.error = f"Judge error: {exc}"
            errors += 1

            print(
                f"[ERR] id={row.id:>4}  "
                f"{exc}"
            )

        output_rows.append(row)

    write_jsonl(output_path, output_rows)

    print()
    print(
        f"→ {output_path}  "
        f"(rows={len(output_rows)}, "
        f"scored={scored}, "
        f"errors={errors})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score generated customer-support replies with an LLM judge."
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Input system-result JSONL file",
    )

    parser.add_argument(
        "--prompt",
        default="prompts/judge_v1.txt",
        help="Judge prompt file",
    )

    parser.add_argument(
        "--out",
        required=True,
        help="Output scored JSONL file",
    )

    args = parser.parse_args()

    score_file(
        input_path=args.input,
        output_path=args.out,
        judge_prompt_path=args.prompt,
    )


if __name__ == "__main__":
    main()