import time
import random
from datetime import datetime, timezone, timedelta
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from live_prediction import get_morale_score


def scrape_news_article(url, retries=2):
    """
    Downloads a dynamically rendered news article using Playwright.
    """
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # Using domcontentloaded to avoid waiting for endless ad trackers
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                html_content = page.content()
                browser.close()

            soup = BeautifulSoup(html_content, 'html.parser')

            # --- EXTRACT TITLE ---
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

            # --- EXTRACT CONTENT ---
            p_tags = soup.find_all('p')
            # Using your specific logic: only grab paragraphs longer than 15 chars
            content = " ".join([p.text.strip() for p in p_tags if len(p.text.strip()) > 15])

            if not content:
                content = "No content found. Might be a video-only article."

            # --- EXTRACT DATE ---
            # Channel 14 uses either <time> or <meta property="article:published_time">
            date_str = ""
            # Scan paragraphs for the short date/time text
            for p in soup.find_all('p'):
                text = p.get_text(strip=True)
                # The date text in the screenshot is short, has numbers, and a colon for the time
                if len(text) < 25 and ":" in text and any(char.isdigit() for char in text):
                    date_str = text
                    # If we find one that specifically says "אתמול", we can stop looking!
                    if "אתמול" in text:
                        break

            today_date = datetime.now(timezone.utc).date()
            yesterday_date = today_date - timedelta(days=1)

            if len(content) >= 50 and "אתמול" in date_str:
                return title, content, yesterday_date

            if len(content) >= 50 and "אתמול" not in date_str:
                return None, None, None


            print(f"Attempt {attempt + 1}: Content still too short after rendering JS.")
            time.sleep(random.uniform(3.0, 7.0))

        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            time.sleep(random.uniform(3.0, 7.0))

    return None, None, None


def get_all_security_links(category_url, max_scrolls=30):
    """
    Scans a category page, scrolls slowly to the bottom to trigger lazy loading, and extracts links.
    """
    print(f"Scanning category with slow auto-scroll: {category_url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)  # Give initial page time to settle

            # --- Slow Scroll to Bottom Logic ---
            print("Scrolling down slowly to load articles...")
            last_height = page.evaluate("document.body.scrollHeight")
            scroll_count = 0

            # Keep scrolling until we hit the bottom or reach max_scrolls
            while scroll_count < max_scrolls:
                # Scroll down by a chunk (800 pixels)
                page.mouse.wheel(0, 800)
                page.wait_for_timeout(800)  # Short pause to simulate human reading/scrolling

                # Check if we have hit the bottom of the current page
                at_bottom = page.evaluate("window.innerHeight + window.scrollY >= document.body.scrollHeight - 100")

                if at_bottom:
                    # We hit the bottom. Wait 2 seconds to let the website load more articles.
                    page.wait_for_timeout(2000)
                    new_height = page.evaluate("document.body.scrollHeight")

                    if new_height == last_height:
                        # The height didn't change, meaning no new articles loaded. We are truly done.
                        print("Reached the absolute bottom of the page.")
                        break
                    else:
                        # The page expanded! Update the height and keep scrolling.
                        last_height = new_height

                scroll_count += 1

            print("Finished scrolling. Extracting links...")

            # Final wait to ensure the very last batch of images/links is fully rendered
            page.wait_for_timeout(2000)
            html_content = page.content()
            browser.close()

        # Parse the fully rendered HTML with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        article_links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            # Channel 14 Smart filtering
            if '/article/' in href:
                full_url = f"https://www.c14.co.il{href}" if href.startswith('/') else href
                article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []

def now14_daily_check():
    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://www.c14.co.il/archive/990"

    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        # Passing clicks=5 to simulate the Load More button
        links_to_scrape = get_all_security_links(security_category_url, max_scrolls=30)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date = scrape_news_article(url)

        # Strict check for yesterday's date
        if date == yesterday_date:
            if title and content and len(content) > 50 and "forbidden" not in title.lower():
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short, scraping failed, or article is invalid, skipping.")
        else:
            print(f"Article is not on the requested date (Found: {date}), skipping.")

        print("-" * 40)

        # Wait between articles to avoid getting blocked by the website
        time.sleep(2)

    print("\nFinished analyzing Channel 14 security articles!")

# ---------------------------------------------------------
# Execution Block
# ---------------------------------------------------------
if __name__ == "__main__":

    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://www.c14.co.il/archive/990"

    for attempt in range(1, 6):
        print(f"Attempt {attempt}")
        # Passing clicks=5 to simulate the Load More button
        links_to_scrape = get_all_security_links(security_category_url, max_scrolls=30)
        time.sleep(2)

        if links_to_scrape:
            break

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date = scrape_news_article(url)

        # Strict check for yesterday's date
        if date == yesterday_date:
            if title and content and len(content) > 50 and "forbidden" not in title.lower():
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short, scraping failed, or article is invalid, skipping.")
        else:
            print(f"Article is not on the requested date (Found: {date}), skipping.")

        print("-" * 40)

        # Wait between articles to avoid getting blocked by the website
        time.sleep(2)

    print("\nFinished analyzing Channel 14 security articles!")