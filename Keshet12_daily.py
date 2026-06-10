import os
import time
import random
from datetime import datetime, timezone, timedelta
import pandas as pd
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from live_prediction import get_morale_score


def scrape_article_Keshet12(driver, url):
    """
    Extracts the article content using the open undetected_chromedriver session.
    """
    try:
        driver.get(url)
        # load the article text
        time.sleep(random.uniform(3.0, 5.0))

        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- Extract Title ---
        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

        # --- Extract Content ---
        paragraphs = soup.find_all('p')
        content = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 15])

        # --- Extract Date ---
        date_str = ""
        meta_date = soup.find('meta', property='article:published_time')
        if meta_date and meta_date.get('content'):
            date_str = meta_date['content']

        # Fallback: scan for the text tag containing the time/date
        if not date_str:
            for span in soup.find_all(['span', 'div']):
                text = span.get_text(strip=True)
                if len(text) < 30 and ":" in text and any(char.isdigit() for char in text):
                    date_str = text
                    if "אתמול" in text:
                        break

        if len(content) >= 50:
            return title, content, date_str

        return None, None, None

    except Exception as e:
        print(f"Error scraping article: {e}")
        return None, None, None


def get_links_Keshet12(driver, category_url):
    """
    Scans the category page and collects article links.
    """
    print(f"Scanning category for links using undetected_chromedriver: {category_url}")

    try:
        driver.get(category_url)
        time.sleep(5)  # Wait for the initial page shell to load

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        article_links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            # filtering articles
            if 'Article-' in href and '.htm' in href and '/news-military/' in href:
                full_url = f"https://www.mako.co.il{href}" if href.startswith('/') else href
                article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []


def Keshet12_daily():
    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)

    security_category_url = "https://www.mako.co.il/news-military"

    print("Launching Undetected Chromedriver...")
    options = uc.ChromeOptions()
    options.page_load_strategy = 'eager'

    driver = uc.Chrome(options=options)
    driver.set_page_load_timeout(20)
    driver.maximize_window()

    links_to_scrape = get_links_Keshet12(driver, security_category_url)

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date_str = scrape_article_Keshet12(driver, url)

        # Smart date check parsing
        is_yesterday = False
        if date_str:
            if "אתמול" in date_str:
                is_yesterday = True
            elif "T" in date_str:
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

        # Save the data if the article was published yesterday
        if is_yesterday:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

                exact_model_input = f"{title} [SEP] {content}"
                source_website = 'Channel 12'
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # --- Save to TXT log file ---
                log_filename = "predictions_log.txt"
                with open(log_filename, "a", encoding="utf-8") as log_file:
                    log_file.write(f"\n--- {current_time} ---\n")
                    log_file.write(f"Source: {source_website}\n")
                    log_file.write(f"URL: {url}\n")
                    log_file.write(f"Title: {title}\n")
                    log_file.write(f"Date String: {date_str}\n")
                    log_file.write(f"Score: {score}\n")
                    log_file.write(f"Exact Input ({len(content)} chars):\n{exact_model_input}\n")
                    log_file.write("--------------------------------------------------\n")
                    print(f"\n Input text and score successfully saved to '{log_filename}'")

                # --- Save to CSV dataset ---
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
            print("Article is not from yesterday, skipping.")

        print("-" * 40)
        time.sleep(random.uniform(2.0, 4.0))

    print("\nFinished analyzing Mako security articles!")
    try:
        driver.quit()
    except Exception:
        pass

    os._exit(0)


# Execution Block

if __name__ == "__main__":
    Keshet12_daily()
