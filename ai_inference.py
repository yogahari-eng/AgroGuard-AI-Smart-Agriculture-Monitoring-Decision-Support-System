"""
ai_inference.py
Loads trained Keras models from ai/models/ and runs real inference on uploaded images.
No random/mock classifier is used. If a model is missing, the web app reports that
the real model must be installed.
"""
import os
from PIL import Image

BASE_DIR = os.path.dirname(__file__)
DISEASE_MODEL_PATH = os.path.join(BASE_DIR, "ai", "models", "crop_disease_model.keras")
PEST_MODEL_PATH = os.path.join(BASE_DIR, "ai", "models", "pest_model.keras")
DISEASE_CLASSES_PATH = os.path.join(BASE_DIR, "ai", "models", "disease_class_names.txt")
PEST_CLASSES_PATH = os.path.join(BASE_DIR, "ai", "models", "pest_class_names.txt")

IMG_SIZE = (224, 224)

_disease_model = None
_pest_model = None
_tf_available = False

try:
    import tensorflow as tf  # noqa: F401
    _tf_available = True
except Exception:
    _tf_available = False


def _load_class_names(path, fallback):
    if os.path.exists(path):
        with open(path) as f:
            names = [line.strip() for line in f if line.strip()]
        if names:
            return names
    return fallback


_MOCK_DISEASE_CLASSES = [
    "Healthy", "Early Blight", "Late Blight", "Leaf Spot",
    "Powdery Mildew", "Bacterial Wilt", "Rust",
]
_MOCK_PEST_CLASSES = [
    "No Pest Detected", "Aphid", "Whitefly", "Leaf Miner",
    "Stem Borer", "Fall Armyworm", "Thrips",
]

DISEASE_CLASSES = _load_class_names(DISEASE_CLASSES_PATH, _MOCK_DISEASE_CLASSES)
PEST_CLASSES = _load_class_names(PEST_CLASSES_PATH, _MOCK_PEST_CLASSES)


def _get_model(kind):
    global _disease_model, _pest_model
    if not _tf_available:
        return None
    path = DISEASE_MODEL_PATH if kind == "disease" else PEST_MODEL_PATH
    if not os.path.exists(path):
        return None
    try:
        if kind == "disease":
            if _disease_model is None:
                _disease_model = tf.keras.models.load_model(path)
            return _disease_model
        else:
            if _pest_model is None:
                _pest_model = tf.keras.models.load_model(path)
            return _pest_model
    except Exception as exc:
        print(f"[ai_inference] Failed to load {kind} model: {exc}")
        return None


def _preprocess(image_path):
    import numpy as np
    img = Image.open(image_path).convert("RGB").resize(IMG_SIZE)
    arr = np.asarray(img, dtype="float32") / 255.0
    return np.expand_dims(arr, axis=0)


def classify(image_path, kind):
    """Run a real Keras disease/pest model. Never fabricate a random prediction."""
    classes = DISEASE_CLASSES if kind == "disease" else PEST_CLASSES
    model = _get_model(kind)

    try:
        Image.open(image_path).verify()
    except Exception:
        return {"prediction": "Invalid image", "confidence": 0.0, "is_mock": False,
                "error": True, "error_type": "invalid_image"}

    if model is None:
        return {
            "prediction": "Model unavailable", "confidence": 0.0, "is_mock": False,
            "error": True, "error_type": "model_unavailable",
            "message": (f"Real {kind} model is not installed. Add the .keras model and class-names file "
                        "under ai/models/ and install TensorFlow."),
        }

    try:
        x = _preprocess(image_path)
        preds = model.predict(x, verbose=0)[0]
        idx = int(preds.argmax())
        confidence = float(preds[idx]) * 100
        return {
            "prediction": classes[idx] if idx < len(classes) else f"Class {idx}",
            "confidence": round(confidence, 1),
            "is_mock": False,
        }
    except Exception as exc:
        print(f"[ai_inference] Inference failed: {exc}")
        return {"prediction": "Inference failed", "confidence": 0.0, "is_mock": False,
                "error": True, "error_type": "inference_failed",
                "message": "The installed AI model could not process this image. Check model input shape and preprocessing."}


def confidence_label(confidence, settings):
    if confidence >= settings["disease_conf_high"]:
        return "High-confidence prediction"
    elif confidence >= settings["disease_conf_mid"]:
        return "Possible prediction — inspect the crop"
    else:
        return "Low-confidence result — image should be reviewed"


def recommendation_for(kind, prediction, confidence, settings):
    healthy_terms = ("healthy", "no pest")
    if any(t in prediction.lower() for t in healthy_terms):
        return "No action needed — crop appears healthy. Continue routine monitoring."

    base = ("Inspect affected plants and consider appropriate treatment."
            if kind == "disease" else
            "Inspect the crop, isolate the affected area if practical, and consult "
            "an agricultural expert about approved control methods.")

    if confidence < settings["disease_conf_mid"]:
        base += " Confidence is low, so confirm visually before taking action."

    return base
