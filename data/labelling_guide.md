# Labelling Guide: Customer Support Replies

## Purpose

This guide defines the criteria for labelling customer support replies as
part of the golden dataset for this project. Each item consists of a
customer message and a corresponding support reply. Labellers must judge
whether the reply is satisfactory from the customer's perspective.

## Labelling Criteria

A reply is evaluated against three criteria:

**1. Correctness**
The reply must state accurate information. It must not invent policies,
misstate refund amounts, or make promises the company cannot fulfill.

**2. Politeness**
The reply must maintain a respectful and professional tone. Dismissive,
condescending, or blaming language toward the customer is not acceptable,
regardless of whether the reply is otherwise helpful.

**3. Completeness**
The reply must address the customer's request in full. Acknowledging the
issue is not sufficient; the reply must provide a resolution or clear next
steps.

## Labelling Rule

A reply is labelled **good** only if it satisfies all three criteria.
A reply is labelled **bad** if it fails any one criterion.

Labellers should rely on their judgment as a representative customer rather
than applying an overly strict or literal interpretation.

## Examples

**Good**
Customer: "Hi, I have an issue with a refund for a damaged item."
Reply: "Hi, thank you for reaching out. I've checked your account and we've
processed a full refund. It will appear in 3 to 5 business days. Let me know
if you need anything else."
Assessment: Correct, polite, and complete.

**Bad — Incomplete**
Customer: "Hi, I have an issue with a refund for a damaged item."
Reply: "Hi, regarding your refund, we can help."
Assessment: Polite, but does not specify a resolution or timeline.

**Bad — Impolite**
Customer: "I have an issue with a late delivery."
Reply: "That's not our problem. You should have read the terms."
Assessment: Dismissive tone, regardless of factual accuracy.

**Bad — Incorrect**
Customer: "Can I get a refund for a damaged item?"
Reply: "Unfortunately we don't offer any support, you're on your own."
Assessment: Factually false, as company policy permits refunds for damaged
items.

## Labelling Process

1. Each item is labelled independently by two labellers, without access to
   the other labeller's assessment.
2. Labels are recorded as `good` or `bad` in the `label_1` and `label_2`
   fields of `golden_set.jsonl`, corresponding to each labeller.
3. Once both labellers have completed their assessments, agreement is
   computed using `check_agreement.py`.
4. Disagreements are resolved through discussion. Items that remain
   ambiguous after discussion are excluded from the final dataset, with the
   reason documented.
