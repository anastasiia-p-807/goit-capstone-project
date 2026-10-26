"""Read-only fixtures: never infer emotions or write these examples to a journal."""
from .catalog import recommend

SCENARIOS = [
    {"id": "small-win", "title": "A small win", "content": "I finally finished the project I had been putting off. I feel proud of the effort, and grateful for my friend's encouragement.", "emotions": [{"label": "pride", "score": 0.86}, {"label": "gratitude", "score": 0.78}]},
    {"id": "busy-day", "title": "A lot on my mind", "content": "Tomorrow's presentation has been on my mind all evening. I keep thinking about what might go wrong, even though I have prepared.", "emotions": [{"label": "nervousness", "score": 0.81}, {"label": "fear", "score": 0.62}]},
    {"id": "hard-day", "title": "Making room for a hard day", "content": "Today did not go as I hoped. I felt disappointed after our conversation and needed some quiet time to myself.", "emotions": [{"label": "disappointment", "score": 0.84}, {"label": "sadness", "score": 0.71}]},
]


def examples():
    return {"items": [{"id": item["id"], "title": item["title"], "content": item["content"],
        "analysis": {"status": "demo", "emotions": item["emotions"], "model_version": "handwritten-example-v1"},
        "recommendations": recommend(None, item["emotions"])} for item in SCENARIOS],
        "notice": "Illustrative, hardcoded outputs. No model was run. These examples are never saved to your journal or included in your insights."}
