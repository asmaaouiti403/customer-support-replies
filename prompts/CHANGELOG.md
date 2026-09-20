# Prompt Changelog

All prompt changes are logged here with the measured score before and after,
so every change is tied to a number, not just an intuition.

## System prompt

### system_v1 -> system_v2 (2026-09-20)

**Why:** Scored system_v1 on the dev split via harness/scorer.py using
judge_v1.txt. Of 24 items attempted (run stopped early - daily quota hit,
see system_v1_dev_meta.json), 23 were scored and 22 were "good" (95.7%).
The two failures were:
- id 12 (bad, judge-flagged): reply invented a specific support email
  address and phone number that were never given as context - an
  unsupported-claims violation.
- id 18 (hard error, not judge-scored): the model's raw JSON failed strict
  schema validation (json_validate_failed) because its reply text used
  curly quotes, which broke JSON parsing under Groq's strict mode.

**Change:** Added an explicit rule against inventing contact details not
provided as context, and a formatting rule requiring plain quotes/hyphens
and no markdown, to reduce both failure modes.

**Score before -> after:**
- system_v1 (dev, n=23 scored / 24 attempted): 22/23 good = 95.7%,
  1 hard error / 24 = 4.2%
- system_v2 (dev, n=TODO): TODO - run:
  python -m harness.runner --split dev --prompt prompts/system_v2.txt --out results/system_v2_dev.jsonl
  python -m harness.scorer --input results/system_v2_dev.jsonl --prompt prompts/judge_v2.txt --out results/system_v2_dev_scored.jsonl
  then compare good-rate and error-rate against the numbers above.

**Note:** the system_v1 run above only covers 24/110 dev items (daily rate
limit), so 95.7% is a partial-sample number, not the full dev score. Re-run
system_v1 on the full split with --resume once quota resets if a clean
full-split baseline is needed for the report.

## Judge prompt

### judge_v1 -> judge_v2 (dated: TODO - fill in when this change was actually made)

**Why:** judge_v1 used five loosely-defined criteria (Relevance,
Helpfulness, Professionalism, Completeness, No unsupported claims) with no
explicit pass/fail rule, which left room for the judge to call a reply
"good" despite one serious flaw as long as it was decent overall.

**Change:**
- Reduced to three criteria (Correctness, Politeness, Completeness) with an
  explicit rule: a reply is good only if it passes all three, bad if it
  fails any one.
- Added a concrete company-policy baseline ("refunds, replacements and
  returns ARE available for damaged, defective or missing items") so the
  judge stops rewarding a reply that refuses help the company actually
  provides.
- Added: "A resolution for a different problem than the one raised does not
  count" - this directly targets a bug found in data/generate_data.py,
  where solution text was originally chosen independently of topic,
  producing fluent replies that resolved the wrong problem but were still
  scored good. See data/labelling_guide.md for the human-labelling side of
  the same fix.
- Added an explicit anti-verbosity instruction ("do not prefer a reply
  because it is longer... polite filler that adds no information does not
  make a reply complete").

**Score before -> after:** TODO - run harness/judge.py --reference human
(or --reference expected as a provisional check) with judge_v1.txt vs
judge_v2.txt on the same dev items and record accuracy/kappa for each, once
human labels exist in golden_set.jsonl.
