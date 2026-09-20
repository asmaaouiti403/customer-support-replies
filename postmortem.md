# Postmortem

## What went wrong

**1. The synthetic golden set had a latent labelling bug.**
`generate_data.py` picked reply `solution` text independently of `topic`,
so some "good"-labelled replies resolved the wrong problem (e.g. a
password-reset question answered with "your plan has been upgraded"). This
means the generator's `expected_label` was wrong for some items — any
agreement number based on it wasn't purely measuring quality. Fixed by
making solutions topic-aware and adding a "wrong-problem resolution
doesn't count" rule to `judge_v2.txt` and the labelling guide.

**2. Human labelling was never started.**
`label_1`/`label_2` are still empty on all 160 items. This blocks the two
most heavily weighted "Measured" deliverables: inter-rater agreement and
judge-vs-human agreement. Everything reported so far uses the provisional
`expected_label`, not real human labels.

**3. The system model failed silently on formatting, not content.**
On our one real run (24/110 dev items), 1 item hard-errored:
`json_validate_failed`, because the reply used curly quotes inside a JSON
string. The judge never even saw this item — it's a failure mode error
counts catch and quality scores completely miss. Fixed with a plain-quotes,
no-markdown rule in `system_v2.txt`.

**4. The one real quality failure was a hallucinated contact detail.**
The single "bad" grade (id 12) invented a support email and phone number
never given as context. `system_v1.txt` said "avoid inventing policies,
actions, refunds..." but never mentioned contact info specifically — a gap
we only found by reading real judged output.

**5. Free-tier rate limits weren't budgeted for.**
The one system run is partial because it hit the daily quota mid-run.
`--resume` exists for this, but we hadn't planned calendar time around
quota resets for runs *and* judge/bias-check calls.

## What we learned

- A generator needs to be checked against the labelling guide itself, not
  just for valid JSON output — logically consistent code can still produce
  semantically wrong ground truth.
- Provisional reference labels are fine for early smoke-testing, but every
  number derived from them needs to stay clearly marked "provisional,"
  including in the final report.
- Reading raw errors and raw judge output (not just summary %) is what
  caught both real bugs here — aggregates alone hid them.
- Rate limits should be in the timeline from the start, not discovered
  mid-run.

## What's still open

- Human labelling hasn't started — the biggest blocker before the demo.
- Only a partial `system_v1` sample is scored; no `system_v2` run yet.
- Bias-check results exist but only against the provisional reference and
  only n=10 pairs each — low power, worth re-running with more pairs and
  real human labels once available.
