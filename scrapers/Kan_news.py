import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import pandas as pd
import time
import random


def uc_scrape_kan_full(url):
    print("Starting undetected browser...")
    options = uc.ChromeOptions()

    # זכור לעדכן את version_main לגרסת הכרום שיש לך כרגע (למשל 146 או 147)
    driver = uc.Chrome(options=options, version_main=146)

    articles_data = []
    links_and_dates = []  # עכשיו נשמור כאן מילון של גם לינק וגם תאריך

    try:
        driver.get(url)
        print("Waiting for initial load...")
        time.sleep(5)

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # שלב 1: איסוף לינקים ותאריכים מעמוד הקטגוריה
        list_items = soup.select('li.articles-item')

        for li in list_items:
            a_tag = li.find('a', href=True)
            if a_tag:
                href = a_tag['href']
                if '/content/' in href:
                    full_url = href if href.startswith('http') else f"https://www.kan.org.il{href}"

                    # חילוץ התאריך בדיוק לפי התגית שמצאת!
                    date_span = li.find('span', class_='article-info-date')
                    article_date = 'N/A'
                    if date_span:
                        # שולפים את מאפיין ה-UTC האידיאלי. אם הוא לא קיים משום מה, ניקח את הטקסט
                        if date_span.has_attr('data-date-utc'):
                            article_date = date_span['data-date-utc']
                        else:
                            article_date = date_span.text.strip()

                    # מוודאים שאין כפילויות
                    if not any(d['URL'] == full_url for d in links_and_dates) and full_url != url:
                        links_and_dates.append({'URL': full_url, 'Date': article_date})

        print(f"Found {len(links_and_dates)} articles! Starting full scraping...\n")

        # שלב 2: כניסה לכל כתבה כדי להביא את התוכן (הורדנו את מגבלת ה-10)
        for item in links_and_dates:
            article_url = item['URL']
            article_date = item['Date']  # התאריך כבר שמור אצלנו!

            try:
                sleep_time = random.uniform(4.0, 7.5)
                time.sleep(sleep_time)

                driver.get(article_url)
                art_soup = BeautifulSoup(driver.page_source, 'html.parser')

                # כותרת
                title_tag = art_soup.find('h1')
                title = title_tag.text.strip() if title_tag else 'N/A'

                # בדיקת חסימות (WAF)
                if "forbidden" in title.lower() or "access denied" in title.lower() or title == 'N/A':
                    print(f"Blocked on: {article_url} - Skipping...")
                    continue

                # כתב
                meta_author = art_soup.find('meta', attrs={'name': 'author'})
                if meta_author and meta_author.get('content'):
                    author = meta_author['content']
                else:
                    author_tag = art_soup.find(class_=lambda c: c and ('author' in c.lower() or 'writer' in c.lower()))
                    author = author_tag.text.strip() if author_tag else 'N/A'

                # תוכן
                p_tags = art_soup.find_all('p')
                content = " ".join([p.text.strip() for p in p_tags if len(p.text.strip()) > 15])

                if not content:
                    content = "No content found. Check tags."

                articles_data.append({
                    'Date': article_date,  # מכניסים את התאריך המדויק לטבלה
                    'Title': title,
                    'Author': author,
                    'Content': content,
                    'URL': article_url
                })

                print(f"Successfully scraped: {title[:40]}... | Date: {article_date} (Slept {sleep_time:.1f}s)")

            except Exception as e:
                print(f"Error scraping {article_url}: {e}")

    finally:
        driver.quit()

    return pd.DataFrame(articles_data)


# הפעלת הפונקציה המלאה
category_url = 'https://www.kan.org.il/content/kan-news/defense/'
df_kan = uc_scrape_kan_full(category_url)

# שמירה לקובץ אקסל/CSV בקידוד עברית תקין
file_name = '../News_raw_csv/kan_news_defense.csv'
print(f"\nScraping complete. Saving to {file_name}...")
df_kan.to_csv(file_name, index=False, encoding='utf-8-sig')

print(f"Saved successfully! Here is the final preview:")
print(df_kan.head())