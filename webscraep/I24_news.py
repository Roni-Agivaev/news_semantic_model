import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import pandas as pd
import time
import random


def scrape_i24_accurate_final(url, clicks=5):
    print("Starting browser for i24NEWS...")
    options = uc.ChromeOptions()

    # משתמשים בגרסה 146 שמותקנת אצלך
    driver = uc.Chrome(options=options, version_main=146)

    articles_data = []
    links = []

    try:
        driver.get(url)
        print("Waiting for initial load...")
        time.sleep(6)

        # --- תהליך גלילה ולחיצה על כפתור "טען עוד מאמרים" ---
        print(f"Attempting to load more articles up to {clicks} times...")
        for i in range(clicks):
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

                button = driver.find_element(By.XPATH, '//button[contains(., "טען עוד מאמרים")]')

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", button)

                print(f"Clicked 'Load More' {i + 1}/{clicks}. Waiting for new batch...")
                time.sleep(3.5)
            except Exception as e:
                print("No more 'Load More' button found or end of page reached.")
                break

        print("Final scroll to ensure everything is fully rendered...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)

        print("Finished loading pages! Extracting accurate links...")

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # --- שלב 1: איסוף הלינקים ---
        for a in soup.find_all('a', href=True):
            href = a['href']

            # אוספים רק לינקים של כתבות אמיתיות
            if 'artc-' in href:
                full_url = href if href.startswith('http') else f"https://www.i24news.tv{href}"

                if full_url not in links:
                    links.append(full_url)

        print(f"Awesome! Found {len(links)} perfectly matched articles. Starting extraction...\n")

        # --- שלב 2: כניסה לכתבות ---
        for article_url in links:
            try:
                # המתנה אקראית בין כתבה לכתבה כדי לא להיראות כמו בוט
                sleep_time = random.uniform(2.5, 5.0)
                time.sleep(sleep_time)

                driver.get(article_url)

                # --- המתנה לטעינת הכתבה במלואה (התיקון שלנו) ---
                time.sleep(4)

                # סגירת חלונית העוגיות ("אני מאשר") אם היא קופצת
                try:
                    cookie_btn = driver.find_element(By.XPATH, '//button[contains(., "אני מאשר")]')
                    driver.execute_script("arguments[0].click();", cookie_btn)
                    time.sleep(1)
                except:
                    pass
                    # -----------------------------------------------

                art_soup = BeautifulSoup(driver.page_source, 'html.parser')

                # כותרת
                title_tag = art_soup.find('h1')
                title = title_tag.text.strip() if title_tag else 'N/A'

                if title == 'N/A' or "forbidden" in title.lower() or "404" in title:
                    print(f"Skipping {article_url} - Title not found.")
                    continue

                # תאריך
                time_tag = art_soup.find('time')
                if time_tag:
                    article_date = time_tag.get('datetime', time_tag.text.strip())
                else:
                    meta_date = art_soup.find('meta', property='article:published_time')
                    article_date = meta_date['content'] if meta_date else 'N/A'

                # כתב
                meta_author = art_soup.find('meta', attrs={'name': 'author'})
                if meta_author and meta_author.get('content'):
                    author = meta_author['content']
                else:
                    author_tag = art_soup.find(class_=lambda c: c and (
                                'writer' in c.lower() or 'author' in c.lower() or 'byline' in c.lower()))
                    author = author_tag.text.strip() if author_tag else 'N/A'

                # תוכן
                p_tags = art_soup.find_all('p')
                content = " ".join([p.text.strip() for p in p_tags if len(p.text.strip()) > 15])

                if not content:
                    content = "No content found. Might be a video-only article."

                articles_data.append({
                    'Date': article_date,
                    'Title': title,
                    'Author': author,
                    'Content': content,
                    'URL': article_url
                })

                print(f"Successfully scraped: {title[:40]}...")

            except Exception as e:
                print(f"Error on {article_url}: {e}")

    finally:
        driver.quit()

    return pd.DataFrame(articles_data)


# הפעלת הפונקציה
category_url = 'https://www.i24news.tv/he/news/news/defense-news'
# פה אפשר לשנות את מספר הלחיצות על "טען עוד" כדי לאסוף יותר מידע
df_i24 = scrape_i24_accurate_final(category_url, clicks=5)

# שמירה לקובץ CSV
file_name = '../News_raw_csv/i24_defense_news_final.csv'
print(f"\nSaving data to {file_name}...")
df_i24.to_csv(file_name, index=False, encoding='utf-8-sig')
print("Done!")