from bs4 import BeautifulSoup
import time
from datetime import datetime, timezone, timedelta
import pandas as pd
from live_prediction import get_morale_score
from playwright.sync_api import sync_playwright
import random

def scrape_news_article(url, retries=2):
    """
    Downloads a dynamically rendered news article using Playwright.
    """
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                # Launch a hidden (headless) Chromium browser
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # Go to the URL and wait until the network is quiet (JS has finished loading)
                page.goto(url, wait_until="networkidle", timeout=15000)

                # Grab the fully rendered HTML
                html_content = page.content()
                browser.close()

            # Now parse with BeautifulSoup just like you did before!
            soup = BeautifulSoup(html_content, 'html.parser')

            # --- EXTRACT TITLE ---
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

            # --- EXTRACT CONTENT ---
            paragraphs = soup.find_all('p')
            content = " ".join([p.get_text(strip=True) for p in paragraphs])

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


def get_all_security_links(category_url):
    """
    Scans a category page and extracts all relevant article links using Playwright.
    """
    print(f"Scanning category for links using Playwright: {category_url}")

    try:
        with sync_playwright() as p:
            # Launch a hidden (headless) Chromium browser
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Go to the URL and wait until the network is quiet (JS has loaded the links)
            page.goto(category_url, wait_until="networkidle", timeout=15000)

            # Grab the fully rendered HTML
            html_content = page.content()
            browser.close()

        # Parse the fully rendered HTML with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        article_links = set()

        # Find all link tags
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']

            # Filter for defense news
            if '/he/news/news/defense-news' in href:
                # Convert relative URLs to absolute
                full_url = f"https://www.i24news.tv{href}" if href.startswith('/') else href
                article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []

def I24_daily_check():
    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://www.i24news.tv/he/news/news/defense-news"

    # links_to_scrape = get_security_links(security_category_url, max_articles=5)
    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        links_to_scrape = get_all_security_links(security_category_url)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    # Loop through the links and run our model on each one
    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date = scrape_news_article(url)

        timestamp_str = date['datetime']
        timestamp = datetime.fromisoformat(timestamp_str)
        extracted_date = timestamp.date()

        if extracted_date == yesterday_date:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short or scraping failed, skipping.")



# Execution Block

if __name__ == "__main__":

    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://www.i24news.tv/he/news/news/defense-news"

    # links_to_scrape = get_security_links(security_category_url, max_articles=5)
    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        links_to_scrape = get_all_security_links(security_category_url)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    # Loop through the links and run our model on each one
    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date = scrape_news_article(url)

        timestamp_str = date['datetime']
        timestamp = datetime.fromisoformat(timestamp_str)
        extracted_date = timestamp.date()

        if extracted_date == yesterday_date:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short or scraping failed, skipping.")

        else:
            print("Article is not on the requested date, skipping.")

        print("-" * 40)

        # Wait 2 seconds between articles to avoid getting blocked by the website
        time.sleep(2)

    print("\nFinished analyzing all security articles!")
