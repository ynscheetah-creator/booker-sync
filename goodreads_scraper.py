# goodreads_scraper.py
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional
import time
import json
import logging
from urllib.parse import urlparse, urlunparse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}

def _make_soup(html: str) -> BeautifulSoup:
    for parser in ("lxml", "html5lib", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    return BeautifulSoup(html, "html.parser")

def _text(el) -> Optional[str]:
    if not el: return None
    return el.get_text(strip=True) or None

def _sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
    return clean_url

def _extract_from_json_ld(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    data = {}
    script = soup.find("script", type="application/ld+json")
    if not script: return data
    
    try:
        json_data = json.loads(script.string)
        book_data = {}
        graph = json_data.get('@graph', [])
        for item in graph:
            if item.get('@type') == 'Book':
                book_data = item
                break
        if not book_data and json_data.get('@type') == 'Book':
            book_data = json_data

        if book_data:
            data["Title"] = book_data.get("name")
            data["Average Rating"] = str(book_data.get("aggregateRating", {}).get("ratingValue", ""))
            authors = book_data.get("author", [])
            if authors:
                if isinstance(authors, list) and authors:
                    data["Author"] = authors[0].get("name")
                elif isinstance(authors, dict):
                     data["Author"] = authors.get("name")
            data["ISBN"] = book_data.get("isbn")
            data["Number of Pages"] = str(book_data.get("numberOfPages", ""))
            if book_data.get("image"):
                data["Cover URL"] = book_data["image"]
    except (json.JSONDecodeError, AttributeError) as e:
        logging.warning(f"  ⚠️ JSON-LD parse error: {e}")
    return data

def fetch_goodreads(url: str) -> Dict[str, Optional[str]]:
    clean_url = _sanitize_url(url)
    logging.info(f"  🔍 Goodreads'ten çekiliyor: {clean_url}")
    time.sleep(1.5)

    try:
        res = requests.get(clean_url, headers=HEADERS, timeout=30)
        res.raise_for_status()
        res.encoding = 'utf-8' # Karakter kodlamasını garantile
    except Exception as e:
        logging.error(f"  ❌ Goodreads isteği başarısız: {e}")
        raise

    soup = _make_soup(res.text)
    data = {
        "Title": None, "Author": None, "Publisher": None, "Year Published": None,
        "Number of Pages": None, "ISBN": None, "ISBN13": None,
        "Average Rating": None, "Cover URL": None, "Book Id": None,
        "goodreadsURL": clean_url,
    }

    json_ld_data = _extract_from_json_ld(soup)
    data.update({k: v for k, v in json_ld_data.items() if v})
    if json_ld_data.get("Title"):
        logging.info("  ✅ Veri, güvenilir JSON-LD kaynağından çekildi.")

    if not data["Title"]:
        data["Title"] = _text(soup.select_one("h1[data-testid='bookTitle'], .BookPageTitleSection__title"))
    if not data["Author"]:
        data["Author"] = _text(soup.select_one("a[data-testid='authorName'], .ContributorLink__name"))
    if not data["Cover URL"]:
        cover_img = soup.select_one("img.ResponsiveImage")
        if cover_img and "nophoto" not in cover_img.get("src", ""):
            data["Cover URL"] = cover_img["src"]
    if not data["Average Rating"]:
        rating_text = _text(soup.select_one(".RatingStatistics__rating"))
        if rating_text: data["Average Rating"] = rating_text
            
    details_block = soup.select_one(".BookDetails, .FeaturedDetails")
    details_text = details_block.get_text(" ") if details_block else soup.get_text(" ")

    if not data["Number of Pages"]:
        m = re.search(r"(\d+)\s*pages", details_text, re.I)
        if m: data["Number of Pages"] = m.group(1)
    if not data["Year Published"]:
        m = re.search(r"(?:Published|First published)\s.*?(\d{4})", details_text, re.I)
        if m: data["Year Published"] = m.group(1)
    if not data["ISBN13"]:
        m = re.search(r"ISBN13:?\s*(\d{13})", details_text)
        if m: data["ISBN13"] = m.group(1)
    
    m = re.search(r"/book/show/(\d+)", clean_url)
    if m: data["Book Id"] = m.group(1)

    found_count = sum(1 for v in data.values() if v)
    logging.info(f"  ✅ Goodreads'ten çekildi: {data['Title'] or 'BAŞLIK YOK'} ({found_count} alan dolu)")
    
    return data
