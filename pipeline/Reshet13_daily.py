import time
import random
from datetime import datetime, timezone, timedelta
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Assuming your ML model function is still here
from live_prediction import get_morale_score


def scrape_news_article(url, retries=2):
    """
    Downloads a dynamically rendered news article using Playwright.
    """
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )

                # domcontentloaded + timeout to bypass ad trackers
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                html_content = page.content()
                browser.close()

            soup = BeautifulSoup(html_content, 'html.parser')

            # --- EXTRACT TITLE ---
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

            # --- EXTRACT CONTENT ---
            paragraphs = soup.find_all('p')
            content = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 15])

            # --- EXTRACT DATE (Visual Text Method via Span) ---
            date_str = ""
            # Scan spans for the short date/time text shown in your screenshot
            for span in soup.find_all('span'):
                text = span.get_text(strip=True)
                if len(text) < 30 and ":" in text and any(char.isdigit() for char in text):
                    date_str = text
                    if "אתמול" in text:
                        break

            # Fallback: If it couldn't find the span, check the meta tag
            if not date_str:
                meta_date = soup.find('meta', property='article:published_time')
                if meta_date and meta_date.get('content'):
                    date_str = meta_date['content']

            if len(content) >= 50:
                return title, content, date_str

            print(f"Attempt {attempt + 1}: Content still too short after rendering JS.")
            time.sleep(random.uniform(3.0, 7.0))

        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            time.sleep(random.uniform(3.0, 7.0))

    return None, None, None


def get_all_security_links(category_url, max_scrolls=8):
    """
    Scans a category page, scrolls to trigger lazy loading, and extracts valid article links.
    """
    print(f"Scanning category for links using Playwright: {category_url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Spoof User-Agent
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

            # domcontentloaded + timeout
            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        article_links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            # --- CHANNEL 13 SUPER STRICT FILTERING ---
            # Only grab links that are strictly inside the security category
            if '/news/politics/security/' in href:
                # Ignore ad tracking or pagination
                if '/page/' in href:
                    continue

                full_url = f"https://13tv.co.il{href}" if href.startswith('/') else href
                article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []


def Reshet13_daily():
    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://13tv.co.il/news/politics/security/"

    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        links_to_scrape = get_all_security_links(security_category_url, max_scrolls=10)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date_str = scrape_news_article(url)

        # Smart Date Checking (Handles both visual "אתמול" text and ISO fallbacks)
        is_yesterday = False
        if date_str:
            if "אתמול" in date_str:
                is_yesterday = True
            elif "T" in date_str:
                # If it fell back to the Meta tag, parse the ISO date
                try:
                    clean_date_str = date_str.replace('Z', '+00:00')
                    timestamp = datetime.fromisoformat(clean_date_str)
                    if timestamp.date() == yesterday_date:
                        is_yesterday = True
                except Exception as e:
                    print(f"Date parsing error on fallback string '{date_str}': {e}")
            else:
                print(f"Article is not from yesterday (Found text: '{date_str}'), skipping.")
        else:
            print("Warning: Could not extract any date information.")

        # Strict check for yesterday
        if is_yesterday:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

                log_filename = "predictions_log.txt"
                exact_model_input = f"{title} [SEP] {content}"
                source_website = 'Channel 13'

                with open(log_filename, "a", encoding="utf-8") as log_file:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_file.write(f"\n--- {current_time} ---\n")
                    log_file.write(f"Source: {source_website}\n")
                    log_file.write(f"URL: {url}\n")
                    log_file.write(f"Title: {title}\n")
                    log_file.write(f"Date String: {date_str}\n")
                    log_file.write(f"Score: {score}\n")
                    log_file.write(f"Exact Input ({len(content)} chars):\n{exact_model_input}\n")
                    log_file.write("--------------------------------------------------\n")
                    print(f"\n Input text and score successfully saved to '{log_filename}'")

                try:
                    log_csv_df = pd.read_csv('log_csv.csv')
                    log_csv_df.loc[len(log_csv_df)] = [current_time, source_website, title, content, score,
                                                       exact_model_input]
                except Exception as e:
                    log_csv_df = pd.DataFrame(
                        columns=['Time', 'Source', 'Title', 'Content', 'Predicted Score', 'Exact Input'])
                    log_csv_df.loc[len(log_csv_df)] = [current_time, source_website, title, content, score,
                                                       exact_model_input]

                log_csv_df.to_csv('log_csv.csv', index=False, encoding='utf-8-sig')
                print(f" Successfully saved to 'log_csv.csv'")

            else:
                print("Article is too short or scraping failed, skipping.")

        print("-" * 40)

        # Wait between articles to avoid getting blocked by the website
        time.sleep(2)

    print("\nFinished analyzing Channel 13 security articles!")


# Execution Block

if __name__ == "__main__":
    Reshet13_daily()
