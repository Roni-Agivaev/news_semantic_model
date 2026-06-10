import time
import random
from datetime import datetime, timezone, timedelta
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from live_prediction import get_morale_score


def scrape_article_ynet(url, retries=2):
    """
    Downloads a dynamically rendered news article using Playwright.
    """
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                html_content = page.content()
                browser.close()

            soup = BeautifulSoup(html_content, 'html.parser')

            # --- EXTRACT TITLE ---
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

            # --- EXTRACT CONTENT ---
            paragraphs = soup.find_all('p')
            content = " ".join([p.get_text(strip=True) for p in paragraphs])

            # Ynet specific fallback for content
            if len(content) < 50:
                spans = soup.find_all('span', {'data-text': 'true'})
                content = " ".join([span.get_text(strip=True) for span in spans])

            # --- EXTRACT DATE ---
            Date = soup.find('time')

            if len(content) >= 50:
                return title, content, Date

            print(f"Attempt {attempt + 1}: Content still too short after rendering JS.")
            time.sleep(random.uniform(3.0, 7.0))

        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            time.sleep(random.uniform(3.0, 7.0))

    return None, None, None


def get_links_ynet(category_url):
    """
    Scans a category page and extracts all relevant article links using Playwright.
    """
    print(f"Scanning category for links using Playwright: {category_url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)

            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        article_links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            # YNET Smart filtering
            if '/news/article/' in href:
                full_url = f"https://www.ynet.co.il{href}" if href.startswith('/') else href
                article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []


def ynet_daily():
    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://www.ynet.co.il/news/category/344"

    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        links_to_scrape = get_links_ynet(security_category_url)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date = scrape_article_ynet(url)

        # Safely try to parse the date, as Ynet's HTML might differ from i24
        extracted_date = None
        try:
            if date and date.has_attr('datetime'):
                timestamp_str = date['datetime']
                timestamp = datetime.fromisoformat(timestamp_str)
                extracted_date = timestamp.date()
            else:
                print("Warning: Could not find standard <time datetime=...> tag on Ynet.")
        except Exception as e:
            print(f"Date parsing error: {e}")

        # If you want to bypass the date check while testing Ynet,
        # change the next line to: if True:
        if extracted_date == yesterday_date:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

                log_filename = "predictions_log.txt"
                exact_model_input = f"{title} [SEP] {content}"
                source_website = 'Ynet'

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

    print("\nFinished analyzing Ynet security articles!")


# Execution Block

if __name__ == "__main__":
    ynet_daily()
