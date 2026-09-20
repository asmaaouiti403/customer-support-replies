import json
import random

random.seed(42)

topics = [
    "a refund for a damaged item",
    "a late delivery",
    "cancelling a subscription",
    "resetting a password",
    "a billing error / double charge",
    "how to return a product",
    "a discount code not working",
    "changing a shipping address",
    "a missing item in an order",
    "upgrading a plan",
    "downgrading a plan",
    "a warranty claim",
    "requesting an invoice",
    "a product defect",
    "closing an account",
]

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
    "For {topic}, unfortunately we don't offer any support, you're on your own.",  # false — pretend policy actually allows it
]

solutions = [
    "we've processed a full refund, it will appear in 3-5 business days",
    "we've issued a replacement, shipped today",
    "your subscription has been cancelled, no further charges will apply",
    "I've sent a password reset link to your registered email",
    "we've refunded the duplicate charge",
    "you can return the item using the prepaid label attached",
    "I've applied a new working discount code: SAVE10",
    "your shipping address has been updated for future orders",
    "we're shipping the missing item at no extra cost",
    "your plan has been upgraded effective immediately",
]

def make_item(item_id, split):
    topic = random.choice(topics)
    customer_message = random.choice(customer_templates).format(topic=topic)
    solution = random.choice(solutions)

    kind = random.choices(
        ["good", "bad_incomplete", "bad_rude", "bad_incorrect"],
        weights=[0.5, 0.2, 0.15, 0.15],
    )[0]

    if kind == "good":
        reply = random.choice(good_reply_templates).format(topic=topic, solution=solution)
        expected_label = "good"
    elif kind == "bad_incomplete":
        reply = random.choice(bad_incomplete_templates).format(topic=topic)
        expected_label = "bad"
    elif kind == "bad_rude":
        reply = random.choice(bad_rude_templates).format(topic=topic)
        expected_label = "bad"
    else:
        reply = random.choice(bad_incorrect_templates).format(topic=topic)
        expected_label = "bad"

    return {
        "id": item_id,
        "customer_message": customer_message,
        "reply": reply,
        "label_1": "",       # fill in manually while labelling
        "label_2": "",       # fill in manually while labelling
        "expected_label": expected_label,  # your own reference, optional
        "split": split,
    }

def main():
    n_total = 160
    n_dev = 110
    items = []
    for i in range(1, n_total + 1):
        split = "dev" if i <= n_dev else "test"
        items.append(make_item(i, split))

    with open("data/golden_set.jsonl", "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Generated {n_total} items -> data/golden_set.jsonl")
    print(f"Dev: {n_dev}, Test: {n_total - n_dev}")

if __name__ == "__main__":
    main()