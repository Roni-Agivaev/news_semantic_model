import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

def scrape_ynet_category(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    articles_data = []
    links = []

    # שלב 1: איסוף הלינקים
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/article/' in href:
            full_url = href if href.startswith('http') else f"https://www.ynet.co.il{href}"
            if full_url not in links:
                links.append(full_url)

    print(f"Found {len(links)} potential articles. Starting to scrape...\n")

    # שלב 2: מעבר על הכתבות (הגבלתי ל-10 לבדיקה)
    for article_url in links:
        try:
            time.sleep(2)

            res = requests.get(article_url, headers=headers)
            art_soup = BeautifulSoup(res.content, 'html.parser')

            # חילוץ כותרת
            title_tag = art_soup.find('h1')
            title = title_tag.text.strip() if title_tag else 'N/A'

            # חילוץ תאריך הכתבה (חיפוש בתגית time או ב-meta tags)
            time_tag = art_soup.find('time')
            if time_tag:
                # לפעמים התאריך המדויק מופיע במאפיין datetime
                article_date = time_tag.get('datetime', time_tag.text.strip())
            else:
                # גיבוי: חיפוש בתגיות המטא של העמוד
                meta_date = art_soup.find('meta', property='article:published_time')
                article_date = meta_date['content'] if meta_date else 'N/A'

            # חילוץ שם הכתב
            author_tag = art_soup.find(class_=lambda c: c and ('author' in c.lower() or 'writer' in c.lower()))
            author = author_tag.text.strip() if author_tag else 'N/A'

            # חילוץ התוכן דרך data-text="true"
            span_tags = art_soup.find_all('span', attrs={'data-text': 'true'})
            content = " ".join([span.text.strip() for span in span_tags if len(span.text.strip()) > 0])

            if not content:
                content = "No content found. Check tags."

            # הוספת התאריך למילון הנתונים
            articles_data.append({
                'Date': article_date,
                'Title': title,
                'Author': author,
                'Content': content,
                'URL': article_url
            })

            print(f"Successfully scraped: {title} (Date: {article_date})")

        except Exception as e:
            print(f"Error scraping {article_url}: {e}")

    return pd.DataFrame(articles_data)

# הפעלה
category_url = 'https://www.ynet.co.il/news/category/344'
df_ynet = scrape_ynet_category(category_url)

# תצוגה מקדימה
print("\nScraping complete. Here is the data preview:")
print(df_ynet.head())

df_ynet.to_csv('Ynet_news.csv', index=False, encoding='utf-8-sig')