# goodreads_scraper_selenium.py
from __future__ import annotations

import re
import time
from typing import Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup


def _text(el) -> Optional[str]:
    if not el:
        return None
    txt = el.get_text(strip=True)
    return txt or None


def fetch_goodreads_selenium(url: str) -> Dict[str, Optional[str]]:
    """Selenium ile Goodreads'ten veri çek"""
    print(f"  🔍 Fetching with Selenium: {url}")
    
    # Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Arka planda çalış
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        # Sayfanın yüklenmesini bekle (title elementini bekle)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        
        # Biraz daha bekle (dinamik içerik için)
        time.sleep(2)
        
        # HTML'i al
        html = driver.page_source
        print(f"  📄 HTML Length: {len(html)} chars")
        
    except Exception as e:
        print(f"  ❌ Selenium error: {e}")
        if driver:
            driver.quit()
        raise
    finally:
        if driver:
            driver.quit()
    
    # BeautifulSoup ile parse et
    soup = BeautifulSoup(html, "lxml")
    
    data: Dict[str, Optional[str]] = {
        "Title": None,
        "Author": None,
        "Additional Authors": None,
        "Publisher": None,
        "Year Published": None,
        "Original Publication Year": None,
        "Number of Pages": None,
        "Language": None,
        "ISBN": None,
        "ISBN13": None,
        "Average Rating": None,
        "Cover URL": None,
        "Book Id": None,
        "goodreadsURL": url,
    }

    # Title
    h1 = soup.select_one("h1[data-testid='bookTitle'], h1.Text__title1")
    data["Title"] = _text(h1)

    # Author
    author = soup.select_one("[data-testid='name'] a, a.ContributorLink")
    data["Author"] = _text(author)

    # Rating
    rating = soup.select_one("[data-testid='rating']")
    if rating:
        rating_text = _text(rating)
        m = re.search(r"(\d+\.?\d*)", rating_text)
        if m:
            data["Average Rating"] = m.group(1)

    # Cover
    cover = soup.select_one("img.BookCover__image")
    if cover and cover.get("src"):
        data["Cover URL"] = cover["src"]

    # Book Id
    m = re.search(r"/book/show/(\d+)", url)
    if m:
        data["Book Id"] = m.group(1)

    # Sayfa detaylarını bul
    page_text = soup.get_text("\n")

    # Pages
    m = re.search(r"(\d+)\s+pages", page_text, re.I)
    if m:
        data["Number of Pages"] = m.group(1)

    # Language
    m = re.search(r"Language\s*:?\s*(\w+)", page_text, re.I)
    if m:
        data["Language"] = m.group(1)

    # Published year
    m = re.search(r"(?:Published|First published)\s+.*?(\d{4})", page_text, re.I)
    if m:
        data["Year Published"] = m.group(1)

    # Publisher
    m = re.search(r"by\s+([^,\n]+(?:Yayınları|Yayınevi|Publishing|Press))", page_text, re.I)
    if m:
        data["Publisher"] = m.group(1).strip()

    # ASIN (ISBN yerine)
    m = re.search(r"ASIN\s*:?\s*([A-Z0-9]+)", page_text)
    if m:
        data["ISBN"] = m.group(1)

    found_count = sum(1 for v in data.values() if v)
    print(f"  ✅ Scraped: {data['Title'] or 'NO TITLE'} ({found_count}/14 fields)")
    
    return data
