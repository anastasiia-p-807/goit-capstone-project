import argparse
from collections import Counter
import gc
import json
import math
import os
from pathlib import Path
import random
import unicodedata

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
from sklearn.metrics import (
    accuracy_score, average_precision_score, classification_report,
    hamming_loss, jaccard_score, precision_recall_fscore_support, roc_auc_score,
)
from sklearn.model_selection import train_test_split

LABELS = (
    "neutral", "positive_mood", "situational_sadness", "anxiety",
    "stress_overload", "irritability", "loneliness", "fatigue",
    "sleep_disturbance", "appetite_change", "concentration_difficulty",
    "low_motivation", "anhedonia", "social_withdrawal", "persistent_low_mood",
    "hopelessness", "passive_death_wish", "suicidal_ideation",
)
LABEL2ID = {label: index for index, label in enumerate(LABELS)}


def text_key(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def load_and_split(directory, seed=42, test_size=0.2, validation_size=0.1):
    directory = Path(directory).resolve()
    files = sorted(directory.rglob("*.jsonl"))
    if not files:
        raise ValueError(f"Немає JSONL у {directory}")
    merged, seen_ids, seen_texts = [], set(), {}
    duplicates = 0
    total_records = 0
    print(f"Джерело корпусу: {directory}; знайдено JSONL: {len(files)}", flush=True)
    for path in files:
        file_records, file_duplicates = 0, 0
        with path.open(encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    primary = row["primary_marker"]
                    secondary = row["secondary_markers"]
                    signature = (primary, tuple(sorted(secondary)))
                    key = text_key(row["text"])
                    if key in seen_texts:
                        if seen_texts[key] != signature:
                            raise ValueError("Конфліктні мітки")
                        duplicates += 1
                        file_duplicates += 1
                    else:
                        seen_texts[key] = signature
                        merged.append(row)
                    seen_ids.add(row["id"])
                    file_records += 1
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{path.relative_to(directory)}:{line_no}: {exc}") from exc
        total_records += file_records
    train_pool, test = train_test_split(
        merged, test_size=test_size, random_state=seed,
        stratify=[row["primary_marker"] for row in merged],
    )
    train, validation = train_test_split(
        train_pool, test_size=validation_size, random_state=seed,
        stratify=[row["primary_marker"] for row in train_pool],
    )
    for left, right in ((train, validation), (train, test), (validation, test)):
        if {text_key(r["text"]) for r in left} & {text_key(r["text"]) for r in right}:
            raise RuntimeError("Перетин текстів між колекціями")
    for name, rows in (("train", train), ("validation", validation), ("test", test)):
        print(f"{name}: {len(rows)}; primary: {dict(sorted(Counter(r['primary_marker'] for r in rows).items()))}")
    return merged, train, validation, test


def targets(rows):
    result = np.zeros((len(rows), len(LABELS)), dtype=np.float32)
    for i, row in enumerate(rows):
        for label in [row["primary_marker"], *row["secondary_markers"]]:
            result[i, LABEL2ID[label]] = 1
    return result


def metrics(y_true, scores):
    predicted = scores >= 0.5
    result = {
        "exact_match_accuracy": accuracy_score(y_true, predicted),
        "label_accuracy": 1.0 - hamming_loss(y_true, predicted),
        "hamming_loss": hamming_loss(y_true, predicted),
        "jaccard_samples": jaccard_score(y_true, predicted, average="samples", zero_division=0),
    }
    for average in ("micro", "macro", "weighted", "samples"):
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, predicted, average=average, zero_division=0,
        )
        result.update({f"precision_{average}": precision, f"recall_{average}": recall, f"f1_{average}": f1})
    valid = (y_true.sum(axis=0) > 0) & (y_true.sum(axis=0) < len(y_true))
    result["auc_valid_labels"] = int(valid.sum())
    result["ap_valid_labels"] = int(valid.sum())
    result["roc_auc_macro"] = float(np.mean([
        roc_auc_score(y_true[:, i], scores[:, i]) for i in np.flatnonzero(valid)
    ])) if valid.any() else float("nan")
    result["average_precision_macro"] = float(np.mean([
        average_precision_score(y_true[:, i], scores[:, i]) for i in np.flatnonzero(valid)
    ])) if valid.any() else float("nan")
    return result


def print_metrics(title, values):
    print(f"\n{title}")
    print(" | ".join(f"{key}={value:.4f}" for key, value in values.items()))


def train_model(name, source, train, validation, test, args):
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from transformers import DataCollatorWithPadding, get_linear_schedule_with_warmup

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    device = torch.device(args.device)
    use_bf16 = getattr(args, "bf16", False)
    if use_bf16 and (device.type != "cuda" or not torch.cuda.is_bf16_supported()):
        raise ValueError("--bf16 потребує CUDA GPU з підтримкою bfloat16")
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=args.offline)
    model = AutoModelForSequenceClassification.from_pretrained(
        source, num_labels=len(LABELS), problem_type="multi_label_classification",
        id2label=dict(enumerate(LABELS)), label2id=LABEL2ID,
        local_files_only=args.offline,
    ).float().to(device)
    padding = DataCollatorWithPadding(tokenizer, return_tensors="pt")

    def make_loader(rows, shuffle=False):
        texts = [row["text"] for row in rows]
        encoded = tokenizer(texts, truncation=True, max_length=args.max_length)
        y = targets(rows)
        items = [({key: value[i] for key, value in encoded.items()}, y[i]) for i in range(len(rows))]

        def collate(batch):
            inputs, labels = zip(*batch)
            return padding(list(inputs)), torch.tensor(np.stack(labels), dtype=torch.float32)

        return DataLoader(items, batch_size=args.batch_size, shuffle=shuffle,
                          collate_fn=collate, num_workers=0,
                          generator=torch.Generator().manual_seed(args.seed))

    train_loader = make_loader(train, shuffle=True)
    train_eval_loader = make_loader(train)
    val_loader = make_loader(validation)
    y_train = targets(train)
    positive = y_train.sum(axis=0)
    if np.any(positive == 0):
        raise ValueError("У train відсутня позитивна мітка")
    weights = np.clip(np.sqrt((len(train) - positive) / positive), 1, 5)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(weights, device=device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
    total_steps = math.ceil(len(train_loader) / args.accumulation) * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.1 * total_steps), total_steps)

    def evaluate(loader):
        model.eval()
        all_y, all_scores, total_loss, count = [], [], 0.0, 0
        with torch.inference_mode():
            for inputs, y in loader:
                y = y.to(device)
                with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
                    logits = model(**{k: v.to(device) for k, v in inputs.items()}).logits
                    loss = criterion(logits, y)
                if not torch.isfinite(loss):
                    raise FloatingPointError("Non-finite evaluation loss")
                total_loss += loss.item() * len(y)
                count += len(y)
                all_y.append(y.cpu().numpy())
                all_scores.append(logits.float().sigmoid().cpu().numpy())
        y, scores = np.concatenate(all_y), np.concatenate(all_scores)
        values = metrics(y, scores)
        values["weighted_bce_loss"] = total_loss / count
        return values, y, scores

    history = []
    print(f"\n{name}: {source}; device={device}; epochs={args.epochs}; bf16={use_bf16}", flush=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        for step, (inputs, y) in enumerate(train_loader):
            y = y.to(device)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
                logits = model(**{k: v.to(device) for k, v in inputs.items()}).logits
                loss = criterion(logits, y)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"Non-finite loss: {name}, epoch={epoch}, step={step}")
            # Масштабування за кількістю записів навіть в останньому неповному вікні.
            window_start = (step // args.accumulation) * args.accumulation * args.batch_size
            window_samples = min(args.accumulation * args.batch_size, len(train) - window_start)
            (loss * len(y) / window_samples).backward()
            if (step + 1) % args.accumulation == 0 or step + 1 == len(train_loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            if (step + 1) % 100 == 0:
                print(f"{name}: epoch {epoch}, batch {step + 1}/{len(train_loader)}", flush=True)
        train_values, _, _ = evaluate(train_eval_loader)
        val_values, _, _ = evaluate(val_loader)
        history.append({"train": train_values, "validation": val_values})
        print_metrics(f"{name}: epoch {epoch}, train", train_values)
        print_metrics(f"{name}: epoch {epoch}, validation", val_values)

    test_values, y_test, test_scores = evaluate(make_loader(test))
    print_metrics(f"{name}: FINAL TEST (epoch {args.epochs}, threshold=0.5)", test_values)
    print(classification_report(y_test, test_scores >= 0.5, target_names=LABELS, digits=4, zero_division=0))
    if args.save_models:
        destination = args.save_models / name
        destination.mkdir(parents=True, exist_ok=False)
        model.config.multilabel_threshold = 0.5
        model.save_pretrained(destination)
        tokenizer.save_pretrained(destination)
    del model, optimizer, scheduler
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return history, test_values


def plot_history(name, history):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    epochs = range(1, len(history) + 1)
    for split, color in (("train", "tab:blue"), ("validation", "tab:orange")):
        ax.plot(epochs, [row[split]["exact_match_accuracy"] for row in history],
                "o-", color=color, label=f"{split}: exact match")
        ax.plot(epochs, [row[split]["label_accuracy"] for row in history],
                "--", color=color, label=f"{split}: per-label accuracy")
    ax.set(title=f"{name}: accuracy by epoch", xlabel="Epoch", ylabel="Accuracy", ylim=(0, 1.02))
    ax.set_xticks(list(epochs))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.text(0.5, 0.01, "Exact match = all labels correct; per-label accuracy includes true negatives.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "UA_data_set")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--accumulation", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--validation-size", type=float, default=0.1, help="Частка всередині train pool")
    local_xlm = ROOT / "artifacts" / "pretrained" / "xlm-roberta-base"
    parser.add_argument("--first-model", default=str(local_xlm) if local_xlm.is_dir() else "FacebookAI/xlm-roberta-base")
    parser.add_argument("--second-model", default="youscan/ukr-roberta-base")
    parser.add_argument("--device", choices=("cpu", "cuda"), default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--save-models", type=Path)
    parser.add_argument("--save-plots", type=Path)
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--bf16", action="store_true")
    args = parser.parse_args()
    if min(args.epochs, args.batch_size, args.accumulation, args.max_length) < 1:
        parser.error("epochs/batch-size/accumulation/max-length мають бути додатними")
    if not 0 < args.test_size < 1 or not 0 < args.validation_size < 1:
        parser.error("Частки split мають бути між 0 і 1")
    if not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
        parser.error("learning-rate має бути скінченним додатним числом")
    merged, train, validation, test = load_and_split(args.data_dir, args.seed, args.test_size, args.validation_size)
    if args.prepare_only:
        return
    import torch
    if args.no_show:
        import matplotlib
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    args.device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    for name in ("xlm_roberta", "ukr_roberta"):
        if args.save_models and (args.save_models / name).exists():
            parser.error(f"Папка вже існує: {args.save_models / name}")
    results = {}
    for name, source in (("xlm_roberta", args.first_model), ("ukr_roberta", args.second_model)):
        history, test_values = train_model(name, source, train, validation, test, args)
        results[name] = test_values
        figure = plot_history(f"{name} ({Path(source).name})", history)
        if args.save_plots:
            args.save_plots.mkdir(parents=True, exist_ok=True)
            figure.savefig(args.save_plots / f"{name}_accuracy.png", dpi=160)
    print("\nПідсумок на спільному test:")
    for name, values in results.items():
        print_metrics(name, values)
    if not args.no_show:
        plt.show()
    else:
        plt.close("all")


if __name__ == "__main__":
    main()
