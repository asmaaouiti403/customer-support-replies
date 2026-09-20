"""
tests/test_judge.py — unit tests for harness/judge.py and harness/bias_checks.py.
Run from the project root:  pytest tests/
No API calls, no quota: a fake client / scripted judge stands in for Groq.
"""
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import judge as judge_mod
from harness.bias_checks import (
    binom_two_sided_p,
    build_position_pairs,
    length_confound,
    pad_reply,
    run_position_check,
    run_verbosity_check,
    summarise_position,
    summarise_verbosity,
)
from harness.judge import (
    Judge,
    PairwiseResult,
    cohens_kappa,
    reference_label,
    summarise_agreement,
)


# ── helpers ───────────────────────────────────────────────────────────────────

class FakeClient:
    """Returns scripted message contents, one per call."""

    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        content = self.contents.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _judge(client, tmp_path):
    (tmp_path / "g.txt").write_text("grade prompt")
    (tmp_path / "c.txt").write_text("compare prompt")
    return Judge(client, grade_prompt=str(tmp_path / "g.txt"), compare_prompt=str(tmp_path / "c.txt"), rpm=100_000)


class ScriptedJudge:
    """compare() decided by a function of (a, b) — lets us simulate biased judges."""

    def __init__(self, fn):
        self.fn = fn

    def compare(self, msg, a, b):
        return PairwiseResult(winner=self.fn(a, b), reason="scripted")


# ── grade(): parsing + retry ──────────────────────────────────────────────────

def test_grade_parses_valid_json(tmp_path):
    j = _judge(FakeClient(['{"grade": "good", "reason": "ok"}']), tmp_path)
    res = j.grade("hi", "hello")
    assert res.grade == "good" and res.reason == "ok"


def test_grade_retries_on_invalid_json_then_succeeds(tmp_path):
    client = FakeClient(["not json", '{"grade": "bad", "reason": "rude"}'])
    res = _judge(client, tmp_path).grade("hi", "hello")
    assert res.grade == "bad"
    assert client.calls == 2


def test_grade_raises_after_max_retries(tmp_path):
    client = FakeClient(["nope"] * judge_mod.MAX_RETRIES)
    try:
        _judge(client, tmp_path).grade("hi", "hello")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "invalid judge output" in str(e)


def test_compare_parses_winner(tmp_path):
    j = _judge(FakeClient(['{"winner": "B", "reason": "complete"}']), tmp_path)
    assert j.compare("hi", "a", "b").winner == "B"


def test_dry_run_needs_no_files_or_client():
    j = Judge(None, dry_run=True, grade_prompt="does/not/exist.txt")
    assert j.grade("m", "x" * 200).grade == "good"
    assert j.grade("m", "short").grade == "bad"
    assert j.compare("m", "aa", "aaaa").winner == "B"


# ── agreement maths ───────────────────────────────────────────────────────────

def test_reference_label_human_requires_agreement():
    assert reference_label({"label_1": "good", "label_2": "good"}, "human") == "good"
    assert reference_label({"label_1": "good", "label_2": "bad"}, "human") is None
    assert reference_label({"label_1": "", "label_2": ""}, "human") is None
    assert reference_label({"expected_label": "bad", "label_1": "", "label_2": ""}, "expected") == "bad"


def test_kappa_perfect_and_chance():
    assert cohens_kappa(["good", "bad", "good", "bad"], ["good", "bad", "good", "bad"]) == 1.0
    # judge says "good" for everything: raw agreement 50% but kappa 0
    assert abs(cohens_kappa(["good", "bad", "good", "bad"], ["good"] * 4)) < 1e-9
    assert math.isnan(cohens_kappa([], []))


def test_summarise_agreement_counts():
    rows = [
        {"id": 1, "reference": "good", "judge_grade": "good", "error": None},
        {"id": 2, "reference": "bad", "judge_grade": "good", "error": None},
        {"id": 3, "reference": "bad", "judge_grade": "bad", "error": None},
        {"id": 4, "reference": "good", "judge_grade": None, "error": "boom"},
    ]
    s = summarise_agreement(rows)
    assert s["n_scored"] == 3 and s["n_errors"] == 1
    assert abs(s["accuracy"] - 2 / 3) < 1e-9
    assert s["disagreement_ids"] == [2]
    assert s["confusion"]["ref_bad__judge_good"] == 1


# ── bias helpers ──────────────────────────────────────────────────────────────

def test_binom_p_values():
    assert binom_two_sided_p(0, 0) == 1.0
    assert abs(binom_two_sided_p(5, 10) - 1.0) < 1e-9
    assert binom_two_sided_p(10, 10) < 0.01


def test_pad_reply_adds_length_only():
    r = "We can help."
    p = pad_reply(r)
    assert p.startswith(r) and len(p) > 3 * len(r)


def _items():
    return [
        {"id": 1, "customer_message": "m1", "reply": "good one " * 20, "expected_label": "good"},
        {"id": 2, "customer_message": "m1", "reply": "bad", "expected_label": "bad"},
        {"id": 3, "customer_message": "m2", "reply": "good two " * 20, "expected_label": "good"},
        {"id": 4, "customer_message": "m3", "reply": "bad alone", "expected_label": "bad"},
    ]


def test_build_position_pairs_only_same_message_mixed():
    pairs = build_position_pairs(_items(), "expected", 10, random.Random(0))
    assert len(pairs) == 1
    assert pairs[0]["good"]["id"] == 1 and pairs[0]["bad"]["id"] == 2


def test_length_confound_detects_separable():
    lc = length_confound(_items(), "expected")
    assert lc["perfectly_separable_by_length"] is True


# ── the bias checks must actually catch bias ─────────────────────────────────

def _pairs():
    return build_position_pairs(_items() * 1, "expected", 10, random.Random(0)) * 12  # 12 identical pairs


def test_position_check_flags_always_A_judge():
    rep = run_position_check(ScriptedJudge(lambda a, b: "A"), _pairs())
    assert rep["flip_rate"] == 1.0
    assert rep["pick_A"] == 24 and rep["pick_B"] == 0
    assert "FIRST" in rep["verdict"]


def test_position_check_flags_always_B_judge():
    rep = run_position_check(ScriptedJudge(lambda a, b: "B"), _pairs())
    assert "SECOND" in rep["verdict"]


def test_position_check_passes_fair_judge():
    good_wins = lambda a, b: "A" if len(a) > len(b) else "B"   # picks the (longer) good reply either way
    rep = run_position_check(ScriptedJudge(good_wins), _pairs())
    assert rep["flip_rate"] == 0.0
    assert rep["accuracy_both_orders"] == 1.0
    assert "no significant" in rep["verdict"]


def test_verbosity_check_flags_length_lover():
    longer = lambda a, b: "A" if len(a) > len(b) else "B"
    rep = run_verbosity_check(ScriptedJudge(longer), _items() * 5, 20, random.Random(0))
    assert rep["padded_wins"] == 2 * rep["n_replies"]
    assert "VERBOSITY BIAS" in rep["verdict"]


def test_verbosity_check_passes_tie_judge():
    rep = run_verbosity_check(ScriptedJudge(lambda a, b: "tie"), _items() * 5, 20, random.Random(0))
    assert rep["ties"] == 2 * rep["n_replies"]
    assert "no significant" in rep["verdict"]


def test_summaries_handle_empty():
    assert summarise_position([]) == {"n_pairs": 0}
    assert summarise_verbosity([]) == {"n_replies": 0}
