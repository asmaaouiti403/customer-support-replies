import json
import random

random.seed(42)

# Each topic now maps to its own set of solutions, so a "good" reply always
# resolves the problem the customer actually raised. Previously `solution`
# was chosen independently of `topic`, which produced replies like "your
# plan has been upgraded" for a password-reset request — factually
# unrelated to the request, but still labelled "good". That mismatch
# violates the Completeness criterion in labelling_guide.md and would have
# caused human labellers to disagree with the generator's expected_label.
TOPIC_SOLUTIONS = {
    "a refund for a damaged item": [
        "we've processed a full refund, it will appear in 3-5 business days",
        "we've issued a replacement, shipped today",
    ],
    "a late delivery": [
        "we've expedited a replacement shipment, it will arrive within 2 business days",
        "we've issued a refund for the delivery delay",
    ],
    "cancelling a subscription": [
        "your subscription has been cancelled, no further charges will apply",
    ],
    "resetting a password": [
        "I've sent a password reset link to your registered email",
    ],
    "a billing error / double charge": [
        "we've refunded the duplicate charge",
    ],
    "how to return a product": [
        "you can return the item using the prepaid label attached",
    ],
    "a discount code not working": [
        "I've applied a new working discount code: SAVE10",
    ],
    "changing a shipping address": [
        "your shipping address has been updated for future orders",
    ],
    "a missing item in an order": [
        "we're shipping the missing item at no extra cost",
    ],
    "upgrading a plan": [
        "your plan has been upgraded effective immediately",
    ],
    "downgrading a plan": [
        "your plan has been downgraded effective immediately, and your next invoice will reflect the new rate",
    ],
    "a warranty claim": [
        "we've approved your warranty claim and a replacement is on its way",
    ],
    "requesting an invoice": [
        "I've attached a copy of your invoice to this email",
    ],
    "a product defect": [
        "we've issued a replacement, shipped today",
    ],
    "closing an account": [
        "your account has been closed and no further charges will apply",
    ],
}

topics = list(TOPIC_SOLUTIONS.keys())

customer_templates = [
    "Hi, I have an issue with {topic}. Can you help me?",
    "Hello, I need help regarding {topic}. This is urgent.",
    "I'm writing about {topic}. What are my options?",
    "Can someone assist me with {topic}? I've been waiting for days.",
    "I'm frustrated about {topic}. Please fix this.",
]

good_reply_templates = [
    "Hi, thank you for reaching out about {topic}. I've checked your account and here's what we can do: {solution}. Let me know if you need anything else!",
    "Hello! I'm sorry for the trouble with {topic}. Here's the solution: {solution}. Feel free to reach out again if you have questions.",
]

bad_incomplete_templates = [
    "Hi, regarding {topic}, we can help.",  # missing actual solution
]

bad_rude_templates = [
    "That's not our problem. You should have read the terms about {topic}.",
]

bad_incorrect_templates = [
    "For {topic}, unfortunately we don't offer any support, you're on your own.",  # false — policy actually allows it
]

# Extra "good-looking but wrong" category: a fluent, polite reply that
# resolves a DIFFERENT problem than the one raised. This is the exact
# failure mode the old generator produced by accident; keeping it here
# on purpose (clearly labelled "bad") gives the judge and the labellers
# real mismatched-topic cases to catch, instead of hiding the bug.
def _mismatched_solution(topic: str, rng: random.Random) -> str:
    other_topics = [t for t in topics if t != topic]
    wrong_topic = rng.choice(other_topics)
    return rng.choice(TOPIC_SOLUTIONS[wrong_topic])


def make_item(item_id, split, rng):
    topic = rng.choice(topics)
    customer_message = rng.choice(customer_templates).format(topic=topic)

    kind = rng.choices(
        ["good", "bad_incomplete", "bad_rude", "bad_incorrect", "bad_mismatched"],
        weights=[0.5, 0.15, 0.12, 0.13, 0.10],
    )[0]

    if kind == "good":
        solution = rng.choice(TOPIC_SOLUTIONS[topic])
        reply = rng.choice(good_reply_templates).format(topic=topic, solution=solution)
        expected_label = "good"
    elif kind == "bad_incomplete":
        reply = rng.choice(bad_incomplete_templates).format(topic=topic)
        expected_label = "bad"
    elif kind == "bad_rude":
        reply = rng.choice(bad_rude_templates).format(topic=topic)
        expected_label = "bad"
    elif kind == "bad_incorrect":
        reply = rng.choice(bad_incorrect_templates).format(topic=topic)
        expected_label = "bad"
    else:  # bad_mismatched
        solution = _mismatched_solution(topic, rng)
        reply = rng.choice(good_reply_templates).format(topic=topic, solution=solution)
        expected_label = "bad"

    return {
        "id": item_id,
        "customer_message": customer_message,
        "reply": reply,
        "label_1": "",       # fill in manually while labelling
        "label_2": "",       # fill in manually while labelling
        "expected_label": expected_label,  # generator's own reference, provisional
        "split": split,
    }


def main():
    rng = random.Random(42)
    n_total = 160
    n_dev = 110
    items = []
    for i in range(1, n_total + 1):
        split = "dev" if i <= n_dev else "test"
        items.append(make_item(i, split, rng))

    with open("data/golden_set.jsonl", "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Generated {n_total} items -> data/golden_set.jsonl")
    print(f"Dev: {n_dev}, Test: {n_total - n_dev}")


if __name__ == "__main__":
    main()
