import os
import time
import random
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from live_prediction import get_morale_score #model


def scrape_article_Keshet12(driver, url):
    """
    מושך את תוכן הכתבה באמצעות הדפדפן הפתוח
    """
    try:
        driver.get(url)
        # המתנה קלה כדי שמאקו יטען את הכתבה
        time.sleep(random.uniform(3.0, 5.0))

        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- חילוץ כותרת ---
        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Title Not Found"

        # --- חילוץ תוכן ---
        paragraphs = soup.find_all('p')
        content = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 15])

        # --- חילוץ תאריך (לוגיקה של מאקו) ---
        date_str = ""
        meta_date = soup.find('meta', property='article:published_time')
        if meta_date and meta_date.get('content'):
            date_str = meta_date['content']

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


def get_links_Keshet12(driver, category_url, max_scrolls=8):
    """
    סורק את עמוד הקטגוריה, גולל מטה ואוסף קישורים לכתבות
    """
    print(f"Scanning category for links using undetected_chromedriver: {category_url}")

    try:
        driver.get(category_url)
        time.sleep(5)  # ממתין לטעינת העמוד הראשון

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        article_links = set()

        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')

            # --- סינון קפדני למאקו צבא וביטחון ---
            if 'Article-' in href and '.htm' in href and '/news-military/' in href:
                full_url = f"https://www.mako.co.il{href}" if href.startswith('/') else href
                article_links.add(full_url)

        return list(article_links)

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []

def Keshet12_daily_check():

    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)
    articles_num = 0

    security_category_url = "https://www.mako.co.il/news-military"

    print("Launching Undetected Chromedriver...")
    options = uc.ChromeOptions()

    # 🌟 קסם 1: טעינה "להוטה" - לא מחכים לפרסומות ולטראקרים
    options.page_load_strategy = 'eager'

    driver = uc.Chrome(options=options)

    # 🌟 קסם 2: עצירה כפויה אחרי 20 שניות כדי למנוע היתקעות לנצח
    driver.set_page_load_timeout(20)
    driver.maximize_window()

    links_to_scrape = get_links_Keshet12(driver, security_category_url)

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date_str = scrape_article_Keshet12(driver, url)

        # בדיקת תאריך חכמה
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

        # שמירה אם זה מאתמול

        if is_yesterday:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                articles_num += 1
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short or scraping failed, skipping.")

        print("-" * 40)
        time.sleep(random.uniform(2.0, 4.0))

    # Close the browser properly at the end of the scan!
    print("\nFinished analyzing Mako security articles!"
          f"\nArticles extracted: {articles_num}")
    try:
        driver.quit()
    except Exception:
        pass

    # The Ultimate Silencer: Forces Python to exit instantly,
    # preventing the buggy Garbage Collector from throwing WinError 6.
    os._exit(0)


# ---------------------------------------------------------
# בלוק הרצה ראשי
# ---------------------------------------------------------
if __name__ == "__main__":

    today_date = datetime.now(timezone.utc).date()
    yesterday_date = today_date - timedelta(days=1)
    articles_num = 0

    security_category_url = "https://www.mako.co.il/news-military"

    print("Launching Undetected Chromedriver...")
    options = uc.ChromeOptions()

    # 🌟 קסם 1: טעינה "להוטה" - לא מחכים לפרסומות ולטראקרים
    options.page_load_strategy = 'eager'

    driver = uc.Chrome(options=options)

    # 🌟 קסם 2: עצירה כפויה אחרי 20 שניות כדי למנוע היתקעות לנצח
    driver.set_page_load_timeout(20)
    driver.maximize_window()

    links_to_scrape = get_links_Keshet12(driver, security_category_url)

    print(f"\nFound {len(links_to_scrape)} security articles. Starting analysis...\n")
    print("-" * 40)

    for url in links_to_scrape:
        print(f"Scraping: {url}")

        title, content, date_str = scrape_article_Keshet12(driver, url)

        # בדיקת תאריך חכמה
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

        # שמירה אם זה מאתמול

        if is_yesterday:
            if title and content and len(content) > 50:
                score = get_morale_score(title, content)
                articles_num += 1
                print(f"Title: {title}")
                print(f"Morale Score: {score}")

            else:
                print("Article is too short or scraping failed, skipping.")

        print("-" * 40)
        time.sleep(random.uniform(2.0, 4.0))

    # Close the browser properly at the end of the scan!
    print("\nFinished analyzing Mako security articles!"
        f"\nArticles extracted: {articles_num}")
    try:
        driver.quit()
    except Exception:
        pass

    # The Ultimate Silencer: Forces Python to exit instantly,
    # preventing the buggy Garbage Collector from throwing WinError 6.
    os._exit(0)