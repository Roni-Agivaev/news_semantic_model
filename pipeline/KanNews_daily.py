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

                page.goto(url, wait_until="networkidle", timeout=30000)

                html_content = page.content()
                browser.close()

            soup = BeautifulSoup(html_content, 'html.parser')

            # --- EXTRACT TITLE ---
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

            # --- EXTRACT CONTENT ---
            paragraphs = soup.find_all('p')
            content = " ".join([p.get_text(strip=True) for p in paragraphs])

            # --- EXTRACT DATE (Kan News UTC Fix) ---
            date_str = None
            # Target the specific div that contains the data-date-utc attribute
            date_div = soup.find('div', attrs={'data-date-utc': True})
            if date_div:
                date_str = date_div['data-date-utc']

            if len(content) >= 50:
                return title, content, date_str

            print(f"Attempt {attempt + 1}: Content still too short after rendering JS.")
            time.sleep(random.uniform(3.0, 7.0))

        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            time.sleep(random.uniform(3.0, 7.0))

    return None, None, None


def get_all_security_links(category_url):
    """
    Scans a category page and extracts all relevant article links using Playwright.
    """
    print(f"Scanning category for links using Playwright: {category_url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

            page.goto(category_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)  # Wait for links to render

            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        article_links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            # KAN SUPER STRICT FILTERING
            if '/content/kan-news/defense/' in href:
                # 1. Ignore pagination or tracking queries
                if '?' in href:
                    continue

                # 2. Extract the last part of the URL (ignoring trailing slashes)
                clean_href = href.rstrip('/')
                last_part = clean_href.split('/')[-1]

                # 3. Valid Kan articles end with a numeric ID (e.g., 1028560)
                if last_part.isdigit():
                    full_url = f"https://www.kan.org.il{href}" if href.startswith('/') else href
                    article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []


def KanNews_daily():
    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    # Updated to Kan News URL
    security_category_url = "https://www.kan.org.il/content/kan-news/defense/"

    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        links_to_scrape = get_all_security_links(security_category_url)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date_str = scrape_news_article(url)

        # Safely try to parse the Kan Date format
        extracted_date = None
        try:
            if date_str:
                # Parses format from your screenshot: "13.4.2026 19:25:35"
                timestamp = datetime.strptime(date_str, "%d.%m.%Y %H:%M:%S")
                extracted_date = timestamp.date()
            else:
                print("Warning: Could not find standard data-date-utc tag on Kan.")
        except Exception as e:
            print(f"Date parsing error: {e}")

        # Strict check for yesterday's date
        if extracted_date == yesterday_date:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

                log_filename = "predictions_log.txt"
                exact_model_input = f"{title} [SEP] {content}"
                source_website = 'Kan News'

                with open(log_filename, "a", encoding="utf-8") as log_file:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_file.write(f"\n--- {current_time} ---\n")
                    log_file.write(f"Source: {source_website}\n")
                    log_file.write(f"URL: {url}\n")
                    log_file.write(f"Title: {title}\n")
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
        else:
            print(f"Article is not on the requested date (Found: {extracted_date}), skipping.")

        print("-" * 40)

        # Wait between articles to avoid getting blocked by the website
        time.sleep(2)

    print("\nFinished analyzing Kan News security articles!")


# Execution Block

if __name__ == "__main__":
    KanNews_daily()
