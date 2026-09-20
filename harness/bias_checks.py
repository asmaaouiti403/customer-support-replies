"""
harness/bias_checks.py — position and verbosity bias checks for the LLM judge (Teammate 3).

POSITION BIAS   Does the judge favour whichever reply is shown first (or second)?
  For each customer message we take one reply known to be good and one known to be bad
  and ask the judge to compare them twice: good-first, then bad-first. A fair judge picks
  the good reply both times. We report accuracy per position, how often the verdict flips
  when only the order changes, and how often "A" is picked overall (ideal: 50%).

VERBOSITY BIAS  Does the judge favour longer replies for being longer?
  For each reply we build a padded twin = the same reply + generic filler sentences that add
  no information. Then we compare original vs padded in both orders. Content is identical,
  so a fair judge should say "tie" or split ~50/50. If the padded twin keeps winning, the
  judge is rewarding length.

Run from the project root:

    python -m harness.bias_checks --check all --split dev --reference expected
    python -m harness.bias_checks --dry-run --check all --reference expected   # no API calls
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

from harness.config import GROQ_BASE_URL, JUDGE_MODEL
from harness.judge import (
    DEFAULT_COMPARE_PROMPT,
    JUDGE_RPM,
    DailyLimitReached,
    Judge,
    reference_label,
)
from harness.schema import load_jsonl

# Generic filler: polite, but carries no information, policy, or resolution.
FILLERS = (
    "We truly appreciate your patience and understanding.",
    "Your satisfaction is very important to us, and we value you as a customer.",
    "Please do not hesitate to contact us again at any time if you need anything else.",
    "Thank you once again for taking the time to get in touch with us.",
)


# ── small helpers ────────────────────────────────────────────────────────────

def pad_reply(reply: str) -> str:
    """Same content, more words."""
    return reply.rstrip() + " " + " ".join(FILLERS)


def binom_two_sided_p(k: int, n: int) -> float:
    """Exact two-sided sign-test p-value: is k out of n consistent with a fair coin?"""
    if n == 0:
        return 1.0
    pmf = [math.comb(n, i) * 0.5 ** n for i in range(n + 1)]
    return min(1.0, sum(p for p in pmf if p <= pmf[k] + 1e-12))


def length_confound(items: list[dict], reference: str) -> dict:
    """
    Descriptive check on the dataset itself: if good replies are all longer than bad ones,
    length alone predicts the label, and neither agreement nor bias numbers can separate
    'judges quality' from 'judges length'. That is why the verbosity check pads replies.
    """
    good = [len(i["reply"]) for i in items if reference_label(i, reference) == "good"]
    bad = [len(i["reply"]) for i in items if reference_label(i, reference) == "bad"]
    if not good or not bad:
        return {"available": False}
    return {
        "available": True,
        "mean_len_good": sum(good) / len(good),
        "mean_len_bad": sum(bad) / len(bad),
        "perfectly_separable_by_length": min(good) > max(bad) or min(bad) > max(good),
    }


# ── position bias ────────────────────────────────────────────────────────────

def build_position_pairs(items: list[dict], reference: str, n: int, rng: random.Random) -> list[dict]:
    """One (good, bad) reply pair per customer message that has both kinds."""
    groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"good": [], "bad": []})
    for it in items:
        lab = reference_label(it, reference)
        if lab in ("good", "bad"):
            groups[it["customer_message"]][lab].append(it)
    pairs = [
        {"customer_message": msg, "good": rng.choice(g["good"]), "bad": rng.choice(g["bad"])}
        for msg, g in groups.items() if g["good"] and g["bad"]
    ]
    rng.shuffle(pairs)
    return pairs[:n]


def run_position_check(judge: Judge, pairs: list[dict]) -> dict:
    records = []
    for k, p in enumerate(pairs, 1):
        msg, good, bad = p["customer_message"], p["good"]["reply"], p["bad"]["reply"]
        r_first = judge.compare(msg, good, bad)   # good shown as A
        r_second = judge.compare(msg, bad, good)  # good shown as B
        w1 = {"A": "good", "B": "bad", "tie": "tie"}[r_first.winner]
        w2 = {"A": "bad", "B": "good", "tie": "tie"}[r_second.winner]
        records.append({
            "good_id": p["good"]["id"], "bad_id": p["bad"]["id"],
            "raw_good_first": r_first.winner, "raw_good_second": r_second.winner,
            "winner_good_first": w1, "winner_good_second": w2,
        })
        print(f"[position {k}/{len(pairs)}] good-first→{w1:<4}  good-second→{w2:<4}")
    return {"records": records, **summarise_position(records)}


def summarise_position(records: list[dict]) -> dict:
    n = len(records)
    if n == 0:
        return {"n_pairs": 0}
    raw = [r["raw_good_first"] for r in records] + [r["raw_good_second"] for r in records]
    a, b, tie = raw.count("A"), raw.count("B"), raw.count("tie")
    p_value = binom_two_sided_p(a, a + b)
    pick_a_rate = a / (a + b) if a + b else float("nan")
    if p_value < 0.05 and pick_a_rate > 0.5:
        verdict = "POSITION BIAS: favours the FIRST reply (A)"
    elif p_value < 0.05 and pick_a_rate < 0.5:
        verdict = "POSITION BIAS: favours the SECOND reply (B)"
    else:
        verdict = "no significant position preference (small n has low power; see flip rate)"
    return {
        "n_pairs": n,
        "accuracy_good_shown_first": sum(r["winner_good_first"] == "good" for r in records) / n,
        "accuracy_good_shown_second": sum(r["winner_good_second"] == "good" for r in records) / n,
        "accuracy_both_orders": sum(r["winner_good_first"] == r["winner_good_second"] == "good" for r in records) / n,
        "flip_rate": sum(r["winner_good_first"] != r["winner_good_second"] for r in records) / n,
        "pick_A": a, "pick_B": b, "pick_tie": tie,
        "pick_A_rate_excl_ties": pick_a_rate,
        "p_value": p_value,
        "verdict": verdict,
    }


# ── verbosity bias ───────────────────────────────────────────────────────────

def run_verbosity_check(judge: Judge, items: list[dict], n: int, rng: random.Random) -> dict:
    sample = rng.sample(items, min(n, len(items)))
    records = []
    for k, it in enumerate(sample, 1):
        msg, orig = it["customer_message"], it["reply"]
        padded = pad_reply(orig)
        r_first = judge.compare(msg, orig, padded)   # padded shown as B
        r_second = judge.compare(msg, padded, orig)  # padded shown as A
        w1 = {"A": "original", "B": "padded", "tie": "tie"}[r_first.winner]
        w2 = {"A": "padded", "B": "original", "tie": "tie"}[r_second.winner]
        records.append({"id": it["id"], "winner_padded_second": w1, "winner_padded_first": w2,
                        "raw_padded_second": r_first.winner, "raw_padded_first": r_second.winner})
        print(f"[verbosity {k}/{len(sample)}] padded-second→{w1:<8}  padded-first→{w2:<8}")
    return {"records": records, **summarise_verbosity(records)}


def summarise_verbosity(records: list[dict]) -> dict:
    n = len(records)
    if n == 0:
        return {"n_replies": 0}
    verdicts = [r["winner_padded_second"] for r in records] + [r["winner_padded_first"] for r in records]
    padded, orig, tie = verdicts.count("padded"), verdicts.count("original"), verdicts.count("tie")
    p_value = binom_two_sided_p(padded, padded + orig)
    padded_rate = padded / (padded + orig) if padded + orig else float("nan")
    if p_value < 0.05 and padded_rate > 0.5:
        verdict = "VERBOSITY BIAS: prefers the padded (longer) twin of an identical reply"
    elif p_value < 0.05 and padded_rate < 0.5:
        verdict = "reverse verbosity effect: prefers the SHORTER twin (filler penalised)"
    else:
        verdict = "no significant verbosity preference (small n has low power)"
    return {
        "n_replies": n,
        "padded_wins": padded, "original_wins": orig, "ties": tie,
        "padded_win_rate_excl_ties": padded_rate,
        "tie_rate": tie / len(verdicts),
        "p_value": p_value,
        "verdict": verdict,
    }


# ── report ───────────────────────────────────────────────────────────────────

def _pct(x: float) -> str:
    return "n/a" if x != x else f"{x:.1%}"


def print_report(report: dict) -> None:
    print("\n" + "=" * 64)
    lc = report.get("length_confound", {})
    if lc.get("available"):
        print(f"Dataset check: mean length good={lc['mean_len_good']:.0f} chars, bad={lc['mean_len_bad']:.0f} chars")
        if lc["perfectly_separable_by_length"]:
            print("  !! Length alone separates good from bad in this data — agreement scores are confounded with length.")
    pos = report.get("position")
    if pos and pos.get("n_pairs"):
        print(f"\nPOSITION BIAS  ({pos['n_pairs']} pairs × 2 orders)")
        print(f"  correct when good reply is first / second : {_pct(pos['accuracy_good_shown_first'])} / {_pct(pos['accuracy_good_shown_second'])}")
        print(f"  correct in BOTH orders                    : {_pct(pos['accuracy_both_orders'])}")
        print(f"  verdict flips when only order changes     : {_pct(pos['flip_rate'])}")
        print(f"  picks A / B / tie                         : {pos['pick_A']} / {pos['pick_B']} / {pos['pick_tie']}  (A-rate excl. ties {_pct(pos['pick_A_rate_excl_ties'])}, p={pos['p_value']:.3f})")
        print(f"  → {pos['verdict']}")
    ver = report.get("verbosity")
    if ver and ver.get("n_replies"):
        print(f"\nVERBOSITY BIAS  ({ver['n_replies']} replies × 2 orders, identical content, padded twin is longer)")
        print(f"  padded wins / original wins / ties : {ver['padded_wins']} / {ver['original_wins']} / {ver['ties']}")
        print(f"  padded win-rate excl. ties         : {_pct(ver['padded_win_rate_excl_ties'])}  (fair judge ≈ 50% or mostly ties; p={ver['p_value']:.3f})")
        print(f"  → {ver['verdict']}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Position and verbosity bias checks for the LLM judge.")
    p.add_argument("--data", default="data/golden_set.jsonl")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--reference", choices=["human", "expected"], default="human",
                   help="Which label defines 'good' vs 'bad' for building pairs")
    p.add_argument("--check", choices=["position", "verbosity", "all"], default="all")
    p.add_argument("--verbosity-label", choices=["any", "good", "bad"], default="any",
                   help="Only pad replies with this reference label. 'good' avoids gluing polite filler "
                        "onto rude/incomplete replies, where it clashes with the reply itself")
    p.add_argument("--n", type=int, default=18, help="Max pairs / replies per check (each costs 2 API calls)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--prompt", default=DEFAULT_COMPARE_PROMPT, help="Pairwise judge prompt file")
    p.add_argument("--model", default=JUDGE_MODEL)
    p.add_argument("--rpm", type=int, default=JUDGE_RPM)
    p.add_argument("--out", default="results/bias_report.json")
    p.add_argument("--dry-run", action="store_true", help="Fake judge (deliberately length-biased) — no API calls")
    args = p.parse_args()

    items = load_jsonl(args.data)
    if args.split != "all":
        items = [i for i in items if i["split"] == args.split]
    items = [i for i in items if reference_label(i, args.reference) in ("good", "bad")]
    if not items:
        print(f"No items with a usable '{args.reference}' label in split '{args.split}'.")
        if args.reference == "human":
            print("Human labels are not filled in yet. Smoke-test with --reference expected (provisional).")
        raise SystemExit(1)

    rng = random.Random(args.seed)
    client = None if args.dry_run else OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)
    judge = Judge(client, model=args.model, compare_prompt=args.prompt, rpm=args.rpm, dry_run=args.dry_run)

    report: dict = {"reference": args.reference, "split": args.split, "model": args.model,
                    "prompt": args.prompt, "seed": args.seed, "dry_run": args.dry_run,
                    "length_confound": length_confound(items, args.reference)}
    try:
        if args.check in ("position", "all"):
            pairs = build_position_pairs(items, args.reference, args.n, rng)
            if len(pairs) < 10:
                print(f"Warning: only {len(pairs)} good/bad pairs share a customer message; results will be low-power.")
            report["position"] = run_position_check(judge, pairs)
        if args.check in ("verbosity", "all"):
            verb_items = items if args.verbosity_label == "any" else \
                [i for i in items if reference_label(i, args.reference) == args.verbosity_label]
            report["verbosity_label"] = args.verbosity_label
            report["verbosity"] = run_verbosity_check(judge, verb_items, args.n, rng)
    except DailyLimitReached as e:
        print(f"[STOP] daily quota reached: {e}\nPartial results below.")
        report["stopped_early"] = True

    print_report(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()