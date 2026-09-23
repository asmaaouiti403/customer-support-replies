"""
generate_data.py

Generates the synthetic golden set for the customer-support-replies task.

Fix vs. the original version (see postmortem.md #1): the old generator
picked a reply's resolution sentence independently of the customer's topic,
so a large fraction of "good"-labelled items actually resolved a different
problem than the one raised (e.g. a password-reset question "resolved" by
upgrading a plan). That's a Completeness failure per labelling_guide.md,
and it silently poisoned expected_label for ~90% of the "good" items.

The fix here is structural, not a random-seed tweak: every topic has
exactly one designated correct resolution (TOPIC_TO_RESOLUTION), and a
"good" item can ONLY be built using its own topic's resolution. It is no
longer possible for the generator to produce a topic/resolution mismatch.

Output: one JSON object per line, with label_1/label_2 left empty for
human labelling (per labelling_guide.md), and expected_label filled in as
a provisional reference only -- see postmortem.md re: keeping this marked
provisional until real human labels exist.
"""

import argparse
import json
import random

TOPICS = [
    "billing error / double charge",
    "discount code not working",
    "late delivery",
    "missing item in an order",
    "product defect",
    "refund for a damaged item",
    "warranty claim",
    "cancelling a subscription",
    "changing a shipping address",
    "closing an account",
    "downgrading a plan",
    "how to return a product",
    "requesting an invoice",
    "resetting a password",
    "upgrading a plan",
]

# Exactly one correct resolution per topic. Do not add a second resolution
# per topic without also updating any code that assumes this 1:1 mapping.
TOPIC_TO_RESOLUTION = {
    "billing error / double charge": "we've refunded the duplicate charge",
    "discount code not working": "I've applied a new working discount code: SAVE10",
    "late delivery": "I've expedited your shipment and it will arrive within 2 business days",
    "missing item in an order": "we're shipping the missing item at no extra cost",
    "product defect": "we've issued a replacement, shipped today",
    "refund for a damaged item": "we've processed a full refund, it will appear in 3-5 business days",
    "warranty claim": "your warranty claim has been approved and a replacement will ship today",
    "cancelling a subscription": "your subscription has been cancelled, no further charges will apply",
    "changing a shipping address": "your shipping address has been updated for future orders",
    "closing an account": "your account has been closed and no further charges will apply",
    "downgrading a plan": "your plan has been downgraded effective immediately",
    "how to return a product": "you can return the item using the prepaid label attached",
    "requesting an invoice": "I've emailed a copy of your invoice to your registered address",
    "resetting a password": "I've sent a password reset link to your registered email",
    "upgrading a plan": "your plan has been upgraded effective immediately",
}

CUSTOMER_MESSAGE_TEMPLATES = [
    "Hi, I have an issue with {topic_a}. Can you help me?",
    "Hello, I need help regarding {topic}. This is urgent.",
    "Can someone assist me with {topic}? I've been waiting for days.",
    "I'm frustrated about {topic}. Please fix this.",
    "I'm writing about {topic}. What are my options?",
]

# "a "/"an " article handling for templates that need "a/an <topic>"
TOPICS_NEED_ARTICLE = {
    "billing error / double charge",
    "discount code not working",
    "late delivery",
    "missing item in an order",
    "product defect",
    "refund for a damaged item",
    "warranty claim",
}


def article_for(topic: str) -> str:
    return "an " if topic[0] in "aeiou" else "a "


def render_customer_message(template: str, topic: str) -> str:
    if "{topic_a}" in template:
        art = article_for(topic) if topic in TOPICS_NEED_ARTICLE else ""
        return template.format(topic_a=f"{art}{topic}")
    if topic in TOPICS_NEED_ARTICLE:
        return template.format(topic=f"{article_for(topic)}{topic}")
    return template.format(topic=topic)


GOOD_REPLY_TEMPLATES = [
    "Hi, thank you for reaching out about {topic}. I've checked your account "
    "and here's what we can do: {resolution}. Let me know if you need "
    "anything else!",
    "Hello! I'm sorry for the trouble with {topic}. Here's the solution: "
    "{resolution}. Feel free to reach out again if you have questions.",
]

BAD_REPLY_TEMPLATES = {
    "impolite": "That's not our problem. You should have read the terms about {topic}.",
    "refuses_help": "For {topic}, unfortunately we don't offer any support, you're on your own.",
    "incomplete": "Hi, regarding {topic}, we can help.",
}


def make_good_reply(topic: str) -> str:
    resolution = TOPIC_TO_RESOLUTION[topic]
    template = random.choice(GOOD_REPLY_TEMPLATES)
    return template.format(topic=topic, resolution=resolution)


def make_bad_reply(topic: str) -> str:
    kind = random.choice(list(BAD_REPLY_TEMPLATES.keys()))
    return BAD_REPLY_TEMPLATES[kind].format(topic=topic)


def generate(n_items: int, dev_fraction: float, seed: int):
    random.seed(seed)
    rows = []
    n_good = n_items // 2
    n_bad = n_items - n_good
    n_dev = round(n_items * dev_fraction)

    labels = ["good"] * n_good + ["bad"] * n_bad
    random.shuffle(labels)

    for i, label in enumerate(labels, start=1):
        topic = random.choice(TOPICS)
        msg_template = random.choice(CUSTOMER_MESSAGE_TEMPLATES)
        customer_message = render_customer_message(msg_template, topic)

        if label == "good":
            reply = make_good_reply(topic)
        else:
            reply = make_bad_reply(topic)

        split = "dev" if i <= n_dev else "test"

        rows.append(
            {
                "id": i,
                "customer_message": customer_message,
                "reply": reply,
                "label_1": "",
                "label_2": "",
                "expected_label": label,  # provisional reference only
                "split": split,
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-items", type=int, default=160)
    parser.add_argument("--dev-fraction", type=float, default=0.6875)  # ~110/160
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="golden_set.jsonl")
    args = parser.parse_args()

    rows = generate(args.n_items, args.dev_fraction, args.seed)

    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(rows)} items to {args.out}")
    print("NOTE: expected_label is a provisional reference only.")
    print("Human labelling (label_1 / label_2) still needs to happen per")
    print("labelling_guide.md before this can be used for real agreement")
    print("or judge-reliability numbers.")


if __name__ == "__main__":
    main()
