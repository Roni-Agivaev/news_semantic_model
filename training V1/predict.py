import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# ---------------------------------------------------------
# Step 1: Load the local model and tokenizer
# ---------------------------------------------------------
model_path = "../dictabert_morale_scorer"

print("Loading the trained model...")
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForSequenceClassification.from_pretrained(model_path)

# Move the model to the GPU if available
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)

# Set the model to evaluation mode (turns off training V1-specific layers like Dropout)
model.eval()


# ---------------------------------------------------------
# Step 2: Define the prediction function
# ---------------------------------------------------------
def get_morale_score(title, content):
    # Combine title and content EXACTLY as we did during training V1
    text = f"{title} [SEP] {content}"

    # Tokenize the text
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=512
    )

    # Move the inputs to the same device as the model (GPU)
    inputs = {key: val.to(device) for key, val in inputs.items()}

    # Run the model without calculating gradients (saves memory and runs much faster)
    with torch.no_grad():
        outputs = model(**inputs)

    # The output is a tensor containing a single number (our regression score)
    # We use .item() to pull that number out of the tensor into a standard Python float
    score = outputs.logits[0][0].item()

    return score


# ---------------------------------------------------------
# Step 3: Test the model on new, unseen articles
# ---------------------------------------------------------

print("\n--- Testing Predictions ---")

# Example 1: A potentially positive/optimistic article
title_1 = "ביבי מבטיח שנצחון קרוב, איראן חלשה"
content_1 = "לאחר שישה שבועות לחימה עצימה ראש הממשלה מבטיח בנאומו כי הניצחון קרוב ואנחנו נשיג את יעדינו בהסכמה או בלחימה."
score_1 = get_morale_score(title_1, content_1)
print(f"Article 1 Score: {score_1:.2f}")

# Example 2: A potentially negative/pessimistic article
title_2 = "הפקקים מחמירים: עיכובים משמעותיים בכביש החוף"
content_2 = "תאונת שרשרת קשה גרמה לחסימת צירים מרכזיים. נהגים מדווחים על המתנה של שעות בכבישים ללא צפי לפינוי, והזעם הציבורי על התשתיות גובר."
score_2 = get_morale_score(title_2, content_2)
print(f"Article 2 Score: {score_2:.2f}")