"""Small, editorial reading catalog; no generated titles or clinical matching."""

import json
from pathlib import Path

TOPICS = ["stress", "self-compassion", "worry", "sleep"]

RESOURCES = json.loads(Path(__file__).with_name("resources.json").read_text(encoding="utf-8"))


def recommend(topic: str | None, emotions: list[dict]) -> list[dict]:
    """Prefer the reader's explicit interest; otherwise offer a tentative topic."""
    selected = topic
    reason = f"Matches your chosen reading topic: {topic}." if topic else None
    if not selected:
        mapping = {
            "fear": "worry", "nervousness": "worry", "anger": "stress",
            "annoyance": "stress", "sadness": "self-compassion",
            "disappointment": "self-compassion", "remorse": "self-compassion",
            "embarrassment": "self-compassion",
        }
        for emotion in emotions:
            if emotion["label"] in mapping:
                selected = mapping[emotion["label"]]
                reason = (
                    f"An optional reading direction related to the possible {emotion['label']} "
                    "in this text. Choose another topic if this does not fit."
                )
                break
    if not selected:
        return []
    return [{**item, "reason": reason} for item in RESOURCES if selected in item["topics"]][:2]

