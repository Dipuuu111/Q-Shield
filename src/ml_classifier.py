
import csv
from pathlib import Path

import joblib
import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.ensemble import (
    RandomForestClassifier,
    HistGradientBoostingClassifier
)
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    classification_report,
    confusion_matrix
)


# Find the main project folder
BASE_DIR = Path(__file__).resolve().parent.parent

# Dataset and saved model locations
DATA_FILE = BASE_DIR / "data" / "qshield_telemetry.csv"
MODEL_DIR = BASE_DIR / "models"
MODEL_FILE = MODEL_DIR / "qshield_classifier.joblib"


# Six input features used by the ML models
FEATURE_COLUMNS = [
    "e_z",
    "e_x",
    "e_y",
    "basis_asymmetry",
    "window_20_peak",
    "bloch_coherence"
]


# Names of the five channel states
LABEL_NAMES = {
    0: "Clean_Channel",
    1: "Weather_Phase_Drift",
    2: "Naive_Eve_Intercept",
    3: "Smart_Mimicry_Or_MicroBurst_Eve",
    4: "Spy_BitFlip_Sabotage"
}


# Recommended response for each channel state
ACTIONS = {
    0: "Use standard Hybrid QKD + ML-KEM-768.",
    1: "Avoid false abort and increase Cascade parity passes.",
    2: "Quarantine QKD and fail over to ML-KEM-1024.",
    3: "Quarantine QKD and fail over to ML-KEM-1024.",
    4: "Drop the poisoned key and hot-swap to ML-KEM-1024."
}


def load_dataset():

    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_FILE}"
        )

    with open(DATA_FILE, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    if not rows:
        raise ValueError("The dataset is empty.")

    # Convert feature values into numbers
    X = np.array(
        [
            [float(row[column]) for column in FEATURE_COLUMNS]
            for row in rows
        ],
        dtype=float
    )

    # Extract target labels
    y = np.array(
        [int(row["label"]) for row in rows],
        dtype=int
    )

    if set(np.unique(y)) != set(LABEL_NAMES.keys()):
        raise ValueError("Dataset must contain all five classes.")

    return X, y


def train_models():

    print("\nLoading Q-Shield telemetry dataset...")

    X, y = load_dataset()

    print("Dataset loaded successfully!")
    print("Total samples:", len(X))

    # Split data into training and testing sets
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=42,
        stratify=y
    )

    print("\nTraining samples:", len(X_train))
    print("Testing samples:", len(X_test))

    # Define the three required ML models
    models = {
        "Random Forest": RandomForestClassifier(
            n_estimators=200,
            random_state=42,
            class_weight="balanced"
        ),

        "Decision Tree": DecisionTreeClassifier(
            random_state=42,
            class_weight="balanced"
        ),

        "Histogram Gradient Boosting": HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.1,
            random_state=42
        )
    }

    results = {}
    best_model = None
    best_model_name = None
    best_score = -1

    print("\n========== MODEL TRAINING ==========")

    for name, model in models.items():

        print(f"\nTraining {name}...")

        model.fit(X_train, y_train)

        predictions = model.predict(X_test)

        accuracy = accuracy_score(y_test, predictions)
        weighted_f1 = f1_score(
            y_test,
            predictions,
            average="weighted"
        )

        results[name] = {
            "accuracy": accuracy,
            "weighted_f1": weighted_f1
        }

        print("Accuracy:", round(accuracy * 100, 2), "%")
        print("Weighted F1:", round(weighted_f1, 4))

        # Select the model with the best weighted F1 score
        if weighted_f1 > best_score:
            best_score = weighted_f1
            best_model = model
            best_model_name = name

    print("\n========== MODEL COMPARISON ==========")

    for name, result in results.items():
        print(
            f"{name}: "
            f"Accuracy = {result['accuracy'] * 100:.2f}%, "
            f"Weighted F1 = {result['weighted_f1']:.4f}"
        )

    # Create models folder if it doesn't exist
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Save the best model and its information
    joblib.dump(
        {
            "model": best_model,
            "model_name": best_model_name,
            "features": FEATURE_COLUMNS,
            "label_names": LABEL_NAMES
        },
        MODEL_FILE
    )

    print("\n========== BEST MODEL ==========")
    print("Best model:", best_model_name)
    print("Best weighted F1:", round(best_score, 4))
    print("Saved at:", MODEL_FILE)

    # Display detailed classification results
    predictions = best_model.predict(X_test)

    print("\n========== CLASSIFICATION REPORT ==========")

    print(
        classification_report(
            y_test,
            predictions,
            labels=list(LABEL_NAMES.keys()),
            target_names=list(LABEL_NAMES.values()),
            zero_division=0
        )
    )

    print("========== CONFUSION MATRIX ==========")

    print(
        confusion_matrix(
            y_test,
            predictions,
            labels=list(LABEL_NAMES.keys())
        )
    )


def predict_channel(features):

    # Load the previously trained model
    saved_data = joblib.load(MODEL_FILE)

    model = saved_data["model"]

    # Prepare feature values in the correct order
    feature_values = np.array(
        [[float(features[column]) for column in FEATURE_COLUMNS]]
    )

    predicted_label = int(model.predict(feature_values)[0])

    return {
        "label": predicted_label,
        "channel_state": LABEL_NAMES[predicted_label],
        "recommended_action": ACTIONS[predicted_label]
    }


# Run training only when this file is executed directly
if __name__ == "__main__":
    train_models()
