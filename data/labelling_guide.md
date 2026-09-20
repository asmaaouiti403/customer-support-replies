# Labelling Guide — Customer Support Replies

For each item, label the reply as **good** or **bad**.

A reply is **good** only if it is all three:

## 1. Correct
The reply gives accurate information. No invented policies, wrong refund amounts,
or false promises.

## 2. Polite
The tone is respectful and professional. No blame on the customer, no sarcasm,
no curtness.

## 3. Complete
The reply addresses everything the customer asked. No missing steps, no ignored
questions.

If the reply fails on **any one** of the three, label it **bad**.

## Examples

**GOOD**
Customer: "Hi, I have an issue with a refund for a damaged item."
Reply: "Hi, thank you for reaching out. I've checked your account and we've
processed a full refund, it will appear in 3-5 business days. Let me know if
you need anything else!"
→ Correct, polite, complete. Label: good

**BAD — incomplete**
Customer: "Hi, I have an issue with a refund for a damaged item."
Reply: "Hi, regarding your refund, we can help."
→ Polite, but never says what will actually happen. Label: bad

**BAD — rude**
Customer: "I have an issue with a late delivery."
Reply: "That's not our problem. You should have read the terms."
→ Rude, dismissive. Label: bad

**BAD — incorrect**
Customer: "Can I get a refund for a damaged item?"
Reply: "Unfortunately we don't offer any support, you're on your own."
→ False — company policy does allow refunds. Label: bad

## Process
1. Label independently — do not look at your teammate's labels first.
2. Fill in `label_1` (labeller 1) and `label_2` (labeller 2) in `golden_set.jsonl`.
3. Once both are done, run `check_agreement.py` to compute agreement %.
4. Any item where labellers disagree: discuss and resolve, or drop it and note why.