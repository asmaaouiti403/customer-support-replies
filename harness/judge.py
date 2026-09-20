"""
harness/judge.py — LLM judge for customer-support replies (Teammate 3).

Two judging modes, one class:
  Judge.grade(message, reply)            -> JudgeResult   ("good" / "bad" + reason)
  Judge.compare(message, reply_a, reply_b) -> PairwiseResult ("A" / "B" / "tie" + reason)

`grade` is what the scorer uses to score system runs.
`compare` exists so bias_checks.py can test position bias (a pointwise judge has
no "position" to be biased about).

It also measures judge-vs-human agreement on the golden set:

    python -m harness.judge --split dev --reference human
    python -m harness.judge --split dev --reference expected      # provisional, see below
    python -m harness.judge --dry-run --reference expected        # no API calls

Run from the project root.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Literal, Optional

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError
from pydantic import BaseModel

from harness.config import BASE_BACKOFF_S, GROQ_BASE_URL, JUDGE_MODEL, MAX_RETRIES
from harness.schema import JudgeResult, groq_json_schema, load_jsonl

DEFAULT_GRADE_PROMPT = "prompts/judge_v1.txt"
DEFAULT_COMPARE_PROMPT = "prompts/judge_pairwise_v1.txt"

# Pairwise prompts are longer than the ~380-token calls config.py budgets for, so the
# default is lower than the runner's 25 RPM to stay under the free-tier 8 000 TPM cap.
JUDGE_RPM = 12
JUDGE_MAX_TOKENS = 400  # headroom in case the judge model emits some reasoning text

LABELS = ("good", "bad")


class PairwiseResult(BaseModel):
    """Verdict of a pairwise comparison. Kept here so schema.py stays untouched."""

    winner: Literal["A", "B", "tie"]
    reason: str


class DailyLimitReached(Exception):
    """Raised when Groq reports the per-day quota is used up."""


# ── the judge ────────────────────────────────────────────────────────────────

class Judge:
    def __init__(
        self,
        client: Optional[OpenAI] = None,
        *,
        model: str = JUDGE_MODEL,
        grade_prompt: str = DEFAULT_GRADE_PROMPT,
        compare_prompt: str = DEFAULT_COMPARE_PROMPT,
        rpm: int = JUDGE_RPM,
        dry_run: bool = False,
    ) -> None:
        self.client = client
        self.model = model
        self.grade_prompt_path = grade_prompt
        self.compare_prompt_path = compare_prompt
        self.dry_run = dry_run
        self._min_interval = 60.0 / rpm
        self._last_call = 0.0
        # Prompt files are read lazily, on first real call: dry-run needs no files, and
        # the bias checks never need the pointwise prompt (or vice versa).
        self._grade_system: Optional[str] = None
        self._compare_system: Optional[str] = None

    # -- public API

    def grade(self, customer_message: str, reply: str) -> JudgeResult:
        if self.dry_run:
            return _fake_grade(reply)
        if self._grade_system is None:
            self._grade_system = Path(self.grade_prompt_path).read_text(encoding="utf-8")
        user = f"Customer message:\n{customer_message}\n\nAssistant reply:\n{reply}"
        return self._call(self._grade_system, user, JudgeResult)

    def compare(self, customer_message: str, reply_a: str, reply_b: str) -> PairwiseResult:
        if self.dry_run:
            return _fake_compare(reply_a, reply_b)
        if self._compare_system is None:
            self._compare_system = Path(self.compare_prompt_path).read_text(encoding="utf-8")
        user = (
            f"Customer message:\n{customer_message}\n\n"
            f"Reply A:\n{reply_a}\n\n"
            f"Reply B:\n{reply_b}"
        )
        return self._call(self._compare_system, user, PairwiseResult)

    # -- internals

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call(self, system: str, user: str, result_model: type[BaseModel]):
        fmt = groq_json_schema(result_model)
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=JUDGE_MAX_TOKENS,
                    temperature=0,  # a judge should be as repeatable as possible
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format=fmt,
                )
                content = resp.choices[0].message.content
                try:
                    return result_model.model_validate_json(content)
                except ValueError:  # pydantic ValidationError and JSONDecodeError both subclass it
                    if attempt < MAX_RETRIES - 1:
                        continue
                    raise ValueError(f"invalid judge output after {MAX_RETRIES} attempts: {content!r}")

            except RateLimitError as e:
                if "day" in str(e).lower():
                    raise DailyLimitReached(str(e))
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = BASE_BACKOFF_S * 2 ** attempt
                try:
                    wait = float(e.response.headers["retry-after"])
                except (AttributeError, KeyError, TypeError, ValueError):
                    pass
                time.sleep(wait)

            except (InternalServerError, APIConnectionError):
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(BASE_BACKOFF_S * 2 ** attempt)

        raise RuntimeError("unreachable: retry loop exited without result")


# ── dry-run stand-ins (no API, no quota) ─────────────────────────────────────
# Deliberately length-driven: a "judge" that likes long replies should be caught by
# bias_checks.py. If the verbosity check does NOT flag the dry-run judge, the check is broken.

def _fake_grade(reply: str) -> JudgeResult:
    return JudgeResult(grade="good" if len(reply) >= 120 else "bad", reason="dry-run length heuristic")


def _fake_compare(a: str, b: str) -> PairwiseResult:
    winner = "A" if len(a) > len(b) else "B" if len(b) > len(a) else "tie"
    return PairwiseResult(winner=winner, reason="dry-run: longer reply wins")


# ── agreement with humans ────────────────────────────────────────────────────

def reference_label(item: dict, mode: str) -> Optional[str]:
    """
    mode="human":    the label both humans agree on, else None (unlabelled or disagreed;
                     the labelling guide says disagreements are resolved/excluded first).
    mode="expected": the generator's `expected_label`. NOT a human label — provisional only.
    """
    if mode == "expected":
        return item.get("expected_label") or None
    l1 = (item.get("label_1") or "").strip()
    l2 = (item.get("label_2") or "").strip()
    return l1 if l1 and l1 == l2 else None


def cohens_kappa(ref: list[str], pred: list[str]) -> float:
    """Chance-corrected agreement for two raters over {good, bad}."""
    n = len(ref)
    if n == 0:
        return float("nan")
    po = sum(r == p for r, p in zip(ref, pred)) / n
    pe = sum((ref.count(c) / n) * (pred.count(c) / n) for c in LABELS)
    if pe == 1:
        return 1.0 if po == 1 else float("nan")
    return (po - pe) / (1 - pe)


def evaluate_agreement(judge: Judge, items: list[dict], reference: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    stopped_early = False
    todo = [(it, reference_label(it, reference)) for it in items]
    todo = [(it, ref) for it, ref in todo if ref in LABELS]

    for n, (item, ref) in enumerate(todo, 1):
        row = {
            "id": item["id"],
            "customer_message": item["customer_message"],
            "reply": item["reply"],
            "reference": ref,
            "judge_grade": None,
            "reason": None,
            "error": None,
        }
        try:
            res = judge.grade(item["customer_message"], item["reply"])
            row["judge_grade"], row["reason"] = res.grade, res.reason
        except DailyLimitReached as e:
            print(f"[STOP] daily quota reached: {e}")
            stopped_early = True
            rows.append(row)
            break
        except Exception as exc:  # one bad call shouldn't lose the rest of the run
            row["error"] = str(exc)
        rows.append(row)
        print(f"[{'ERR' if row['error'] else ' ok'}] id={item['id']:>4}  ref={ref:<4} judge={row['judge_grade']}  ({n}/{len(todo)})")

    return rows, summarise_agreement(rows, stopped_early)


def summarise_agreement(rows: list[dict], stopped_early: bool = False) -> dict:
    scored = [r for r in rows if r["judge_grade"] in LABELS]
    ref = [r["reference"] for r in scored]
    pred = [r["judge_grade"] for r in scored]
    n = len(scored)
    agree = sum(r == p for r, p in zip(ref, pred))
    confusion = {f"ref_{a}__judge_{b}": sum(1 for r, p in zip(ref, pred) if r == a and p == b)
                 for a in LABELS for b in LABELS}
    return {
        "n_scored": n,
        "n_errors": sum(1 for r in rows if r["error"]),
        "stopped_early": stopped_early,
        "accuracy": agree / n if n else float("nan"),
        "kappa": cohens_kappa(ref, pred),
        "confusion": confusion,
        "judge_good_rate": pred.count("good") / n if n else float("nan"),
        "reference_good_rate": ref.count("good") / n if n else float("nan"),
        "disagreement_ids": [r["id"] for r in scored if r["reference"] != r["judge_grade"]],
    }


def print_agreement(summary: dict, reference: str) -> None:
    c = summary["confusion"]
    print("\n" + "=" * 60)
    if reference == "expected":
        print("PROVISIONAL: reference = generator's expected_label, NOT human labels.")
    print(f"Scored items      : {summary['n_scored']}  (errors: {summary['n_errors']})")
    print(f"Agreement         : {summary['accuracy']:.1%}")
    print(f"Cohen's kappa     : {summary['kappa']:.2f}   (>0.6 substantial, >0.8 near-perfect)")
    print(f"Judge says 'good' : {summary['judge_good_rate']:.1%}   (reference: {summary['reference_good_rate']:.1%})")
    print("Confusion (rows = reference, cols = judge):")
    print(f"              judge=good  judge=bad")
    print(f"  ref=good    {c['ref_good__judge_good']:>10}  {c['ref_good__judge_bad']:>9}")
    print(f"  ref=bad     {c['ref_bad__judge_good']:>10}  {c['ref_bad__judge_bad']:>9}")
    print(f"Disagreement ids  : {summary['disagreement_ids']}")
    if summary["stopped_early"]:
        print("!! Stopped early: daily quota reached. Results are partial.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Measure LLM-judge agreement with the golden set.")
    p.add_argument("--data", default="data/golden_set.jsonl")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--reference", choices=["human", "expected"], default="human",
                   help="human = items where label_1 == label_2; expected = generator label (provisional)")
    p.add_argument("--prompt", default=DEFAULT_GRADE_PROMPT, help="Judge prompt file")
    p.add_argument("--model", default=JUDGE_MODEL)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--rpm", type=int, default=JUDGE_RPM)
    p.add_argument("--out", default=None, help="Per-item results .jsonl (default results/judge_agreement_<prompt>_<split>.jsonl)")
    p.add_argument("--dry-run", action="store_true", help="Fake judge — no API calls, no quota")
    args = p.parse_args()

    items = load_jsonl(args.data)  # raw dicts: the golden set has a `reply` field GoldItem doesn't declare
    if args.split != "all":
        items = [i for i in items if i["split"] == args.split]

    usable = [i for i in items if reference_label(i, args.reference) in LABELS]
    if not usable:
        print(f"No usable items for --reference {args.reference} in split '{args.split}'.")
        if args.reference == "human":
            print("Both label_1 and label_2 must be filled in and agree (see labelling_guide.md).")
            print("Until then you can smoke-test with:  --reference expected   (provisional, not human).")
        raise SystemExit(1)
    print(f"{len(usable)} usable items ({len(items) - len(usable)} excluded: unlabelled or humans disagree).")
    if args.limit:
        usable = usable[: args.limit]

    client = None if args.dry_run else OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)
    judge = Judge(client, model=args.model, grade_prompt=args.prompt, rpm=args.rpm, dry_run=args.dry_run)

    rows, summary = evaluate_agreement(judge, usable, args.reference)
    print_agreement(summary, args.reference)

    out = Path(args.out or f"results/judge_agreement_{Path(args.prompt).stem}_{args.split}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary_path = out.with_name(out.stem + "_summary.json")
    summary_path.write_text(json.dumps({**summary, "reference": args.reference, "prompt": args.prompt,
                                        "model": args.model, "dry_run": args.dry_run}, indent=2), encoding="utf-8")
    print(f"\n→ {out}\n→ {summary_path}")


if __name__ == "__main__":
    main()