# import requests
# from bs4 import BeautifulSoup
# import time # To add small delays so we don't overload the server
# import datetime
# from live_prediction import scrape_news_article, get_morale_score
# import pandas as pd
#
#
# # ---------------------------------------------------------
# # NEW FUNCTION: Scrape links from a specific category page
# # ---------------------------------------------------------
# def get_security_links(category_url, max_articles=5):
#     """
#     Scans a category page and extracts links only to relevant articles.
#     """
#     headers = {
#         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
#     }
#
#     print(f"Scanning category for links: {category_url}")
#     try:
#         response = requests.get(category_url, headers=headers)
#         response.raise_for_status()
#         soup = BeautifulSoup(response.text, 'html.parser')
#
#         article_links = set() # Using a set to prevent duplicate links
#
#         # Find all link tags (<a>) on the page
#         for a_tag in soup.find_all('a', href=True):
#             href = a_tag['href']
#
#             # Smart filtering: In Ynet, actual news articles usually contain '/news/article/'
#             if '/news/article/' in href:
#                 # Convert relative URLs to full absolute URLs
#                 if href.startswith('/'):
#                     full_url = f"https://www.ynet.co.il{href}"
#                 else:
#                     full_url = href
#
#                 article_links.add(full_url)
#
#                 # Stop when we have gathered enough article links
#                 if len(article_links) >= max_articles:
#                     break
#
#         return list(article_links)
#
#     except Exception as e:
#         print(f"Error extracting links: {e}")
#         return []
#
#
# def get_all_security_links(category_url):
#     """
#     סורק דף קטגוריה ומוציא ממנו את כל קישורי הכתבות שהוא מוצא.
#     """
#     headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
#     print(f"Scanning category for links: {category_url}")
#
#     try:
#         response = requests.get(category_url, headers=headers)
#         response.raise_for_status()
#         soup = BeautifulSoup(response.text, 'html.parser')
#
#         article_links = set()
#         for a_tag in soup.find_all('a', href=True):
#             href = a_tag['href']
#             if '/news/article/' in href:
#                 full_url = f"https://www.ynet.co.il{href}" if href.startswith('/') else href
#                 article_links.add(full_url)
#
#         return list(article_links)
#     except Exception as e:
#         print(f"Error extracting links: {e}")
#         return []
#
# # ---------------------------------------------------------
# # Execution Block
# # ---------------------------------------------------------
# if __name__ == "__main__":
#
#     security_category_url = "https://www.ynet.co.il/news/category/185"
#
#    # links_to_scrape = get_security_links(security_category_url, max_articles=5)
#     links_to_scrape = get_all_security_links(security_category_url)
#
#     print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
#     print("-" * 40)
#
#     #Loop through the links and run our model on each one
#     for url in links_to_scrape:
#         print(f"Scraping: {url}")
#
#         title, content = scrape_news_article(url)
#
#         if title and content and len(content) > 50:
#             score = get_morale_score(title, content)
#             print(f"Title: {title}")
#             print(f"Morale Score: {score}")
#
#             log_filename = "predictions_log.txt"
#             exact_model_input = f"{title} [SEP] {content}"
#             source_website = 'Ynet'
#
#             with open(log_filename, "a", encoding="utf-8") as log_file:
#                 current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#                 log_file.write(f"\n--- {current_time} ---\n")
#                 log_file.write(f"Source: {source_website}\n")
#                 log_file.write(f"URL: {url}\n")
#                 log_file.write(f"Title: {title}\n")
#                 log_file.write(f"Score: {score}\n")
#                 log_file.write(f"Exact Input ({len(content)} chars):\n{exact_model_input}\n")
#                 log_file.write("--------------------------------------------------\n")
#                 print(f"\n Input text and score successfully saved to '{log_filename}'")
#
#             try:
#                 log_csv_df = pd.read_csv('log_csv.csv')
#                 log_csv_df.loc[len(log_csv_df)] = [current_time, source_website, title, content, score,
#                                                    exact_model_input]
#
#             except Exception as e:
#                 log_csv_df = pd.DataFrame(
#                     columns=['Time', 'Source', 'Title', 'Content', 'Predicted Score', 'Exact Input'])
#                 log_csv_df.loc[len(log_csv_df)] = [current_time, source_website, title, content, score,
#                                                    exact_model_input]
#
#             log_csv_df.to_csv('log_csv.csv', index=False, encoding='utf-8-sig')
#             print(f"\n successfully saved to 'log_csv.csv'")
#
#             # log_ynet_df = pd.DataFrame(
#             #          columns=['Time', 'Source', 'Title', 'Content', 'Predicted Score', 'Exact Input'])
#             # log_ynet_df.loc[len(log_ynet_df)] = [current_time, source_website, title, content, score,
#             #                                         exact_model_input]
#             # log_ynet_df.to_csv('log_ynet.csv', index=False, encoding='utf-8-sig')
#
#
#         else:
#             print("Article is too short or scraping failed, skipping.")
#
#         print("-" * 40)
#
#         # Wait 2 seconds between articles to avoid getting blocked by the website
#         time.sleep(2)
#
#     print("\nFinished analyzing all security articles!")











import time
import random
from datetime import datetime, timezone, timedelta
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Assuming your ML model function is still here
from pipeline.live_prediction import get_morale_score


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

def ynet_daily_check():

    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)
    article_index = 0
    article_model_processed = 0
    sum_score = 0
    min_val = 0
    max_val = 0

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
        print(f"{article_index}) Scraping: {url}")
        article_index += 1

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
            article_model_processed += 1

            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                sum_score += score
                if min_val > score or min_val == 0:
                    min_val = score
                if max_val < score or max_val == 0:
                    max_val = score
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short or scraping failed, skipping.")
        else:
            print(f"Article is not on the requested date (Found: {extracted_date}), skipping.")

        print("-" * 40)

        # Wait between articles to avoid getting blocked by the website
        time.sleep(2)

    print("\nFinished analyzing Ynet security articles!")
    print("-" * 40)
    print('--- Scraping and model evaluation ---')
    print('number of urls: ' + str(article_index))
    print('number of articles: ' + str(article_model_processed))
    print('average score: ' + str(sum_score / article_model_processed))
    print('min score: ' + str(min_val))
    print('max score: ' + str(max_val))


# ---------------------------------------------------------
# Execution Block
# ---------------------------------------------------------
if __name__ == "__main__":

    ynet_daily_check()