import json

def main():
    path = "data/golden_set.jsonl"
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            items.append(json.loads(line))

    total = 0
    agree = 0
    disagreements = []
    dropped = 0

    for item in items:
        l1 = item.get("label_1", "").strip()
        l2 = item.get("label_2", "").strip()

        if not l1 or not l2:
            dropped += 1
            continue

        total += 1
        if l1 == l2:
            agree += 1
        else:
            disagreements.append(item["id"])

    pct = (agree / total * 100) if total else 0

    print(f"Total labelled items: {total}")
    print(f"Agreement: {agree}/{total} ({pct:.1f}%)")
    print(f"Disagreements: {len(disagreements)} -> ids: {disagreements}")
    print(f"Dropped (missing labels): {dropped}")

if __name__ == "__main__":
    main()