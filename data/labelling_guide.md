# Labelling Guide: Customer Support Replies

Hey! Before you start labelling, here's the deal: you're going to read a customer's
message and the support reply that was sent back, and decide: would a real person
be happy with this reply, or not?

There's no trick to it. Just imagine you're the customer. Read the reply the way
they would've read it. Then ask yourself three simple questions.

## The three questions

**1. Is it correct?**
Did the agent actually get the facts right? No made up refund amounts, no promises
they can't keep, no wrong information about policies.

**2. Is it polite?**
Would you feel respected reading this? No attitude, no talking down to the customer,
no "that's not my problem" energy, even if the reply is technically helpful.

**3. Is it complete?**
Did they actually answer what was asked? Not just acknowledge the problem, actually
resolve it or give clear next steps. A reply that says "we can help" and stops there
hasn't really helped anyone.

If the answer to all three is yes, label it **good**.
If it fails on even one, label it **bad**.

Don't overthink borderline cases too much. Go with your gut reaction as the customer.
That's honestly the whole point of this exercise.

## A few examples to calibrate your gut

**Good**
Customer: "Hi, I have an issue with a refund for a damaged item."
Reply: "Hi, thank you for reaching out. I've checked your account and we've
processed a full refund. It'll appear in 3 to 5 business days. Let me know if you
need anything else!"

This one just works. It's warm, it tells you exactly what happened, and it closes
the loop.

**Bad, incomplete**
Customer: "Hi, I have an issue with a refund for a damaged item."
Reply: "Hi, regarding your refund, we can help."

Polite enough, but help how? When? This leaves the customer hanging.

**Bad, rude**
Customer: "I have an issue with a late delivery."
Reply: "That's not our problem. You should have read the terms."

Even if this were technically accurate, nobody wants to be talked to like this.

**Bad, incorrect**
Customer: "Can I get a refund for a damaged item?"
Reply: "Unfortunately we don't offer any support, you're on your own."

This is just false. The company does offer refunds for damaged items. A confident,
polite, wrong answer is still wrong.

## How we're doing this together

Label on your own first, and don't peek at your teammate's labels before you're
done. The whole point is to see where we naturally agree and where we don't.

Fill in your labels (good or bad) in the label_1 or label_2 column of
golden_set.jsonl, whichever one is yours.

Once we're both done, we'll run check_agreement.py to see how often we matched.

If we disagree on something, no big deal. We'll talk it through together, or if
it's genuinely ambiguous, we'll just drop it and note why.

That's it. Thanks for helping label. This dataset is the foundation everything
else in the project builds on, so take your time and trust your instincts.