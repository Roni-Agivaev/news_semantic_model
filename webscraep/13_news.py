from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random


def scrape_13tv_pages(max_pages):
    print("Starting stealth requests (curl_cffi) for 13tv...")

    # אתחול סשן שמזייף את טביעת האצבע של הדפדפן
    session = requests.Session(impersonate="chrome120")

    articles_data = []
    links = []

    try:
        # שלב 1: ריצה בלולאה על כל עמודי הקטגוריה
        print(f"Scanning pages 1 to {max_pages}...")
        for page_num in range(1, max_pages + 1):
            # כתובת העמוד משתנה לפי מספר הלולאה
            if page_num == 1:
                # לפעמים עמוד 1 הוא פשוט הכתובת הראשית
                url = "https://13tv.co.il/news/politics/security/"
            else:
                url = f"https://13tv.co.il/news/politics/security/page/{page_num}/"

            print(f"Fetching links from: {url}")

            response = session.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # באתר ערוץ 13, כתבות בדרך כלל יושבות תחת הנתיב /item/
            page_links_count = 0
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/item/' in href:
                    full_url = href if href.startswith('http') else f"https://13tv.co.il{href}"
                    # מוודאים שאין כפילויות של אותה כתבה
                    if full_url not in links:
                        links.append(full_url)
                        page_links_count += 1

            print(f"-> Found {page_links_count} new articles on page {page_num}.")

            # השהייה בין עמוד לעמוד כדי לא להציף את השרת
            time.sleep(random.uniform(1.5, 3.0))

        print(f"\nTotal unique articles found across {max_pages} pages: {len(links)}")
        print("Starting content extraction...\n")

        # שלב 2: מעבר על כל הכתבות שנאספו מכל העמודים
        for article_url in links:
            try:
                # השהייה אקראית לפני כל כתבה
                sleep_time = random.uniform(2.0, 4.5)
                time.sleep(sleep_time)

                art_response = session.get(article_url)
                art_soup = BeautifulSoup(art_response.text, 'html.parser')

                # כותרת
                title_tag = art_soup.find('h1')
                title = title_tag.text.strip() if title_tag else 'N/A'

                # דילוג אם הגענו בטעות לעמוד שגיאה או חסימה
                if title == 'N/A' or "forbidden" in title.lower() or "404" in title:
                    print(f"Skipping {article_url} - Invalid title.")
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
                    author_tag = art_soup.find(class_=lambda c: c and ('writer' in c.lower() or 'author' in c.lower()))
                    author = author_tag.text.strip() if author_tag else 'N/A'

                # תוכן (חיפוש פסקאות)
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


# הפעלת הפונקציה - מעבירים 4 כפרמטר של העמוד המקסימלי
df_13tv = scrape_13tv_pages(max_pages=4)

# שמירה לקובץ CSV בקידוד עברית תקין
file_name = '../News_raw_csv/13tv_news_security.csv'
print(f"\nSaving data to {file_name}...")
df_13tv.to_csv(file_name, index=False, encoding='utf-8-sig')
print("Done! Here is a preview:")
print(df_13tv.head())