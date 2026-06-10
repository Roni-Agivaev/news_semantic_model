from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random


def stealth_scrape_mako(url):
    print("Starting ultra-stealth requests (curl_cffi)...")

    # אתחול סשן שמזייף לחלוטין את טביעת האצבע של הדפדפן ברמת ה-TLS
    session = requests.Session(impersonate="chrome120")

    articles_data = []
    links = []

    try:
        # שליחת בקשה לעמוד הראשי
        response = session.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        # איסוף לינקים בדיוק כמו שתיקנו קודם (רק כתבות עם .htm)
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/news' in href and '.htm' in href:
                full_url = href if href.startswith('http') else f"https://www.mako.co.il{href}"
                if full_url not in links and full_url != url:
                    links.append(full_url)

        print(f"Found {len(links)} articles! Starting content extraction...\n")

        # מעבר על הכתבות
        for article_url in links:
            try:
                sleep_time = random.uniform(2.0, 4.5)
                time.sleep(sleep_time)

                # כניסה לכתבה עצמה
                art_response = session.get(article_url)
                art_soup = BeautifulSoup(art_response.text, 'html.parser')

                # כותרת
                title_tag = art_soup.find('h1')
                title = title_tag.text.strip() if title_tag else 'N/A'

                if title == 'N/A' or "forbidden" in title.lower():
                    print(f"Skipping {article_url} - No valid title found.")
                    continue

                # תאריך
                time_tag = art_soup.find('time')
                if time_tag:
                    article_date = time_tag.get('datetime', time_tag.text.strip())
                else:
                    meta_date = art_soup.find('meta', property='article:published_time')
                    article_date = meta_date['content'] if meta_date else 'N/A'

                # כתב
                author_tag = art_soup.find(class_=lambda c: c and ('writer' in c.lower() or 'author' in c.lower()))
                author = author_tag.text.strip() if author_tag else 'N/A'

                # תוכן
                p_tags = art_soup.find_all('p')
                content = " ".join([p.text.strip() for p in p_tags if len(p.text.strip()) > 15])

                if not content:
                    content = "No content found."

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
        session.close()

    return pd.DataFrame(articles_data)


# הפעלת הפונקציה
category_url = 'https://www.mako.co.il/news-military?partner=NewsNavBar'
df_mako = stealth_scrape_mako(category_url)

# שמירה לקובץ
file_name = '../News_raw_csv/mako_news_military.csv'
print(f"\nSaving to {file_name}...")
df_mako.to_csv(file_name, index=False, encoding='utf-8-sig')
print("Done!")