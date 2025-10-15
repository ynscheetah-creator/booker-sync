# goodreads_scraper.py
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional, List
import time
import json
import logging


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}


def _make_soup(html: str) -> BeautifulSoup:
    """Robust soup maker"""
    for parser in ("lxml", "html5lib", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    return BeautifulSoup(html, "html.parser")


def _text(el) -> Optional[str]:
    if not el:
        return None
    txt = el.get_text(strip=True)
    return txt or None


def _extract_from_json_ld(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """JSON-LD structured data'dan bilgi çek"""
    data = {}
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            json_data = json.loads(script.string)
            if json_data.get("@type") == "Book":
                data["Title"] = json_data.get("name")
                data["Average Rating"] = str(json_data.get("aggregateRating", {}).get("ratingValue", ""))
                author = json_data.get("author", [{}])[0]
                data["Author"] = author.get("name")
                data["ISBN"] = json_data.get("isbn")
                data["Number of Pages"] = str(json_data.get("numberOfPages", ""))
                if json_data.get("image"):
                    data["Cover URL"] = json_data["image"]
                break
        except Exception:
            continue
    return data

def _extract_genres(soup: BeautifulSoup) -> Optional[str]:
    """Sayfadan kitap türlerini (genre) çeker."""
    genre_links = soup.select("a[href*='/genres/']")
    genres = set()
    for link in genre_links:
        text = link.get_text(strip=True)
        # Genel "Genres" linkini atla
        if text and len(text) > 2 and text.lower() != 'genres':
            genres.add(text)
    
    if genres:
        # En fazla 5 tür al
        return ", ".join(list(genres)[:5])
    return None

def _extract_series(soup: BeautifulSoup) -> Optional[str]:
    """Sayfadan seri bilgisini çeker."""
    series_div = soup.find('div', class_='BookPageTitleSection__title')
    if series_div:
        series_link = series_div.find('a', href=re.compile(r'/series/'))
        if series_link:
            series_text = series_link.get_text(strip=True)
            # Kitap numarasını da içeren tam metni al
            full_series_text_el = series_link.find_parent('h3')
            if full_series_text_el:
                return full_series_text_el.get_text(strip=True)
            return series_text
    # Fallback for older layouts
    series_h2 = soup.find('h2', id='bookSeries')
    if series_h2 and series_h2.find('a'):
        return series_h2.find('a').get_text(strip=True).replace('(','').replace(')','').strip()
    return None


def fetch_goodreads(url: str) -> Dict[str, Optional[str]]:
    """Goodreads kitap sayfasından temel ve zenginleştirilmiş alanları çeker."""
    logging.info(f"  🔍 Goodreads'ten çekiliyor: {url}")
    time.sleep(1.5)

    try:
        res = requests.get(url, headers=HEADERS, timeout=30)
        res.raise_for_status()
    except Exception as e:
        logging.error(f"  ❌ Goodreads isteği başarısız: {e}")
        # Hata durumunda yeniden fırlat, ana döngü yakalasın
        raise

    soup = _make_soup(res.text)
    data: Dict[str, Optional[str]] = {
        "Title": None, "Author": None, "Publisher": None, "Year Published": None,
        "Number of Pages": None, "ISBN": None, "ISBN13": None,
        "Average Rating": None, "Cover URL": None, "Book Id": None,
        "goodreadsURL": url, "Genres": None, "Series": None,
    }

    # 1. JSON-LD (En güvenilir)
    json_ld_data = _extract_from_json_ld(soup)
    data.update({k: v for k, v in json_ld_data.items() if v})

    # 2. HTML'den kalanları kazı
    if not data["Title"]:
        data["Title"] = _text(soup.select_one("h1[data-testid='bookTitle']"))
    if not data["Author"]:
        data["Author"] = _text(soup.select_one("a[data-testid='authorName']"))
    if not data["Cover URL"]:
        cover_img = soup.select_one("img.BookCover__image, img.ResponsiveImage")
        if cover_img and "nophoto" not in cover_img.get("src", ""):
            data["Cover URL"] = cover_img["src"]
            
    # Diğer detaylar
    details_text = soup.get_text("\n")
    if not data["Number of Pages"]:
        m = re.search(r"(\d+)\s*pages", details_text, re.I)
        if m: data["Number of Pages"] = m.group(1)
    if not data["Year Published"]:
        m = re.search(r"(?:Published|First published)\s+(\d{4})", details_text, re.I)
        if m: data["Year Published"] = m.group(1)
    if not data["ISBN13"]:
        m = re.search(r"ISBN13:?\s*(\d{13})", details_text)
        if m: data["ISBN13"] = m.group(1)

    # 3. Yeni zenginleştirilmiş veriler
    data["Genres"] = _extract_genres(soup)
    data["Series"] = _extract_series(soup)

    m = re.search(r"/book/show/(\d+)", url)
    if m: data["Book Id"] = m.group(1)

    found_count = sum(1 for v in data.values() if v)
    logging.info(f"  ✅ Goodreads'ten çekildi: {data['Title'] or 'BAŞLIK YOK'} ({found_count} alan dolu)")
    return data
