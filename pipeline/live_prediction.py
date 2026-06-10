import os
import requests
from bs4 import BeautifulSoup
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import datetime
from urllib.parse import urlparse
import pandas as pd

# Setup the Model (Run once)
print("Loading the model and preparing environment...")

# Path to the saved model directory, resolved relative to the project root (one level up from this file)
model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dictabert_morale_scorer")

# Load the tokenizer and the model
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForSequenceClassification.from_pretrained(model_path)

# Move the model to the GPU if available
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
model.eval()  # Set to evaluation mode


# Web Scraper Function
def scrape_news_article(url):
    """
    Downloads a news article and extracts its title and content.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # --- EXTRACT TITLE ---
        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

        # --- EXTRACT CONTENT ---
        # For general sites and Ynet text paragraphs
        paragraphs = soup.find_all('p')
        content = " ".join([p.get_text(strip=True) for p in paragraphs])

        # --- EXTRACT DATE ---
        Date = soup.find('time')

        # Ynet specific fallback: sometimes they use spans with data-text
        if len(content) < 50:
            spans = soup.find_all('span', {'data-text': 'true'})
            content = " ".join([span.get_text(strip=True) for span in spans])

        if len(content) < 50:
            print("Warning: Extracted content is unusually short. Check website structure.")

        return title, content, Date

    except Exception as e:
        print(f"Error scraping the article: {e}")
        return None, None


# Prediction Function
def get_morale_score(title, content):
    """
    Takes the extracted title and content, formats them, and returns a predicted score.
    """
    if not title or not content:
        return "Cannot predict without title and content."

    # Combine EXACTLY as trained (Title [SEP] Content)
    text = f"{title} [SEP] {content}"

    # Prepare the text for the model
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    inputs = {key: val.to(device) for key, val in inputs.items()}

    # Run the model without saving gradients
    with torch.no_grad():
        outputs = model(**inputs)

    # Extract the actual number
    score = outputs.logits[0][0].item()
    return round(score, 2)


# Extract website
def extract_website_name(url):
    """
    Extracts the clean domain name from a full URL.
    Example: https://www.ynet.co.il/news/... -> ynet.co.il
    """
    domain = urlparse(url).netloc
    if domain.startswith("www."):
        domain = domain[4:]

    clean_name = domain.split('.')[0]

    return clean_name.capitalize()


# Execution and documenting

if __name__ == "__main__":
    # Your target article
    target_url = "https://www.i24news.tv/he/news/news/defense-news/artc-fc6a6d55"

    print(f"\nScraping article from: {target_url}")
    live_title, live_content = scrape_news_article(target_url)

    if live_title and live_content:
        print("\n--- Article Successfully Scraped ---")
        print(f"Title: {live_title}")
        print(f"Content Length: {len(live_content)} characters")

        print("\nAnalyzing morale score...")
        predicted_score = get_morale_score(live_title, live_content)

        print(f"\n==============================")
        print(f"PREDICTED MORALE SCORE: {predicted_score}")
        print(f"==============================")

        # --- Save to log file ---
        log_filename = "predictions_log.txt"
        exact_model_input = f"{live_title} [SEP] {live_content}"
        source_website = extract_website_name(target_url)

        with open(log_filename, "a", encoding="utf-8") as log_file:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"\n--- {current_time} ---\n")
            log_file.write(f"Source: {source_website}\n")
            log_file.write(f"URL: {target_url}\n")
            log_file.write(f"Title: {live_title}\n")
            log_file.write(f"Score: {predicted_score}\n")
            log_file.write(f"Exact Input ({len(live_content)} chars):\n{exact_model_input}\n")
            log_file.write("--------------------------------------------------\n")

        try:
            log_csv_df = pd.read_csv('log_csv.csv')
            log_csv_df.loc[len(log_csv_df)] = [current_time, source_website, live_title, live_content, predicted_score,
                                               exact_model_input]

        except Exception as e:
            log_csv_df = pd.DataFrame(columns=['Time', 'Source', 'Title', 'Content', 'Predicted Score', 'Exact Input'])
            log_csv_df.loc[len(log_csv_df)] = [current_time, source_website, live_title, live_content, predicted_score,
                                               exact_model_input]

        log_csv_df.to_csv('log_csv.csv', index=False, encoding='utf-8-sig')

        print(f"\n Input text and score successfully saved to '{log_filename}'")

#deactivate
#.\env\Scripts\activate

# python live_prediction.py


