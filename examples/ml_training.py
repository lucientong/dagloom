#!/usr/bin/env python3
"""ML Training Pipeline Example — Dagloom

Demonstrates an ML training workflow:
  load_data >> preprocess >> train >> evaluate

Run with:
    python examples/ml_training.py
"""

import random

from dagloom import node


@node(retry=2, timeout=60.0)
def load_data(dataset: str) -> dict:
    """Load training and test data from a dataset source."""
    print(f"  Loading dataset: {dataset}")
    # Simulated data — in production, load from files or DB.
    n_samples = 1000
    data = {
        "X_train": [[random.gauss(0, 1) for _ in range(10)] for _ in range(n_samples)],
        "y_train": [random.choice([0, 1]) for _ in range(n_samples)],
        "X_test": [[random.gauss(0, 1) for _ in range(10)] for _ in range(200)],
        "y_test": [random.choice([0, 1]) for _ in range(200)],
    }
    print(f"  Loaded {n_samples} training samples, 200 test samples")
    return data


@node(cache=True)
def preprocess(data: dict) -> dict:
    """Preprocess data: normalize features."""
    print("  Normalizing features ...")
    for key in ("X_train", "X_test"):
        for row in data[key]:
            row_max = max(abs(v) for v in row) or 1.0
            for i in range(len(row)):
                row[i] = row[i] / row_max
    print("  Preprocessing complete")
    return data


@node(retry=1, timeout=120.0)
def train(data: dict) -> dict:
    """Train a simple model (simulated)."""
    print("  Training model ...")
    n_features = len(data["X_train"][0])
    # Simulated weights.
    weights = [random.gauss(0, 0.1) for _ in range(n_features)]
    bias = random.gauss(0, 0.1)
    print(f"  Model trained with {n_features} features")
    return {
        "weights": weights,
        "bias": bias,
        "X_test": data["X_test"],
        "y_test": data["y_test"],
    }


@node
def evaluate(model_data: dict) -> dict:
    """Evaluate the model on test data."""
    print("  Evaluating model ...")
    weights = model_data["weights"]
    bias = model_data["bias"]
    X_test = model_data["X_test"]
    y_test = model_data["y_test"]

    # Simple prediction: sign(dot(w, x) + b).
    correct = 0
    for x, y in zip(X_test, y_test):
        score = sum(w * xi for w, xi in zip(weights, x)) + bias
        pred = 1 if score > 0 else 0
        if pred == y:
            correct += 1

    accuracy = correct / len(y_test)
    metrics = {
        "accuracy": round(accuracy, 4),
        "test_samples": len(y_test),
        "correct": correct,
    }
    print(f"  Accuracy: {metrics['accuracy']:.2%} ({correct}/{len(y_test)})")
    return metrics


# Build the ML pipeline.
pipeline = load_data >> preprocess >> train >> evaluate

if __name__ == "__main__":
    print("=" * 50)
    print("  Dagloom ML Training Pipeline Example")
    print("=" * 50)
    print()

    result = pipeline.run(dataset="iris-synthetic")
    print()
    print(f"Evaluation metrics: {result}")

    print()
    print("Pipeline structure:")
    print(pipeline.visualize())
