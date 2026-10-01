import torch
import os
from transformers import AutoTokenizer, AutoModelForSequenceClassification

class LocalNLPClassifier:
    def __init__(self):
        # Pre-trained sequence classification model with fine-tuned sentiment weights
        self.model_name = "distilbert-base-uncased-finetuned-sst-2-english"

        # Dynamically allocate weights cache directory depending on host OS target environment
        if os.path.exists("/app"):
            cache_dir = "/app/models/hf_cache"
        else:
            # Fallback pathing structure targets native user space on local macOS environments smoothly
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")

        os.makedirs(cache_dir, exist_ok=True)

        # Enforce local weight loading fallback contexts securely
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, cache_dir=cache_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name, cache_dir=cache_dir)

        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")

        self.model.to(self.device)
        self.model.eval()

    def analyze_sentiment_tone(self, text: str) -> dict:
        """Executes high-speed token matrix classification over incoming text blocks."""
        with torch.no_grad():
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            token_length = inputs['input_ids'].shape[1]

            outputs = self.model(**inputs)
            probabilities = torch.softmax(outputs.logits, dim=-1)
            prediction = torch.argmax(probabilities, dim=-1).item()

            # Map SST-2 labels (0: NEGATIVE, 1: POSITIVE)
            sentiment_label = "POSITIVE" if prediction == 1 else "NEGATIVE"
            confidence = probabilities[0][prediction].item()

        return {
            "token_length": token_length,
            "raw_class_prediction": prediction,
            "estimated_sentiment": sentiment_label,
            "confidence_score": round(confidence, 4),
            "device_allocated": str(self.device).upper()
        }

if __name__ == "__main__":
    classifier = LocalNLPClassifier()
    print("Local PyTorch NLP Pipeline Test:", classifier.analyze_sentiment_tone("Check system safety metrics."))
