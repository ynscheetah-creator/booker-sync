# goodreads_scraper.py
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional
import time
import json


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "DNT": "1",
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
    """JSON-LD structured data'dan bilgi çek (Goodreads bunu kullanıyor!)"""
    data = {}
    
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            json_data = json.loads(script.string)
            
            # Book object bul
            if json_data.get("@type") == "Book":
                data["Title"] = json_data.get("name")
                data["Average Rating"] = str(json_data.get("aggregateRating", {}).get("ratingValue", ""))
                
                # Author
                author = json_data.get("author", {})
                if isinstance(author, dict):
                    data["Author"] = author.get("name")
                elif isinstance(author, list) and author:
                    data["Author"] = author[0].get("name")
                
                # Other fields
                data["ISBN"] = json_data.get("isbn")
                data["Number of Pages"] = str(json_data.get("numberOfPages", ""))
                data["Language"] = json_data.get("inLanguage")
                data["Publisher"] = json_data.get("publisher", {}).get("name") if isinstance(json_data.get("publisher"), dict) else None
                
                # Cover
                if json_data.get("image"):
                    data["Cover URL"] = json_data["image"]
                
                break
        except Exception:
            continue
    
    return data


def fetch_goodreads(url: str) -> Dict[str, Optional[str]]:
    """Goodreads kitap sayfasından temel alanları çeker"""
    print(f"  🔍 Fetching: {url}")
    
    # Rate limiting
    time.sleep(1.5)
    
    try:
        session = requests.Session()
        res = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        res.raise_for_status()
    except Exception as e:
        print(f"  ❌ Request failed: {e}")
        raise
    
    soup = _make_soup(res.text)
    
    # Debug
    print(f"  📄 HTML Length: {len(res.text)} chars")
    
    # Başlangıç verileri
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

    # 🔥 ÖNCELİKLE JSON-LD'DEN ÇEK (En güvenilir yöntem)
    json_ld_data = _extract_from_json_ld(soup)
    data.update({k: v for k, v in json_ld_data.items() if v})
    
    if json_ld_data:
        print(f"  ✅ Found data in JSON-LD")

    # ---- Title (birden fazla yöntem)
    if not data["Title"]:
        title_selectors = [
            "h1[data-testid='bookTitle']",
            "h1.Text__title1",
            "h1#bookTitle",
            "h1[itemprop='name']",
        ]
        
        for selector in title_selectors:
            h1 = soup.select_one(selector)
            if h1:
                data["Title"] = _text(h1)
                break
        
        # Fallback: ilk h1
        if not data["Title"]:
            all_h1 = soup.find_all("h1", limit=3)
            for h1 in all_h1:
                text = _text(h1)
                if text and len(text) > 3:  # Çok kısa başlıkları atla
                    data["Title"] = text
                    break

    # ---- Cover URL
    if not data["Cover URL"]:
        cover_selectors = [
            "img.BookCover__image",
            "img#coverImage",
            "img[itemprop='image']",
        ]
        
        for selector in cover_selectors:
            cover = soup.select_one(selector)
            if cover and cover.get("src"):
                src = cover["src"]
                # Placeholder olmadığından emin ol
                if "nophoto" not in src.lower():
                    data["Cover URL"] = src
                    break

    # ---- Author
    if not data["Author"]:
        author_selectors = [
            "[data-testid='name'] a",
            "a.authorName__container",
            ".ContributorLink__name",
            "span[itemprop='author'] a",
        ]
        
        for selector in author_selectors:
            author_el = soup.select_one(selector)
            if author_el:
                data["Author"] = _text(author_el)
                break

    # Additional authors
    more_authors = soup.select(
        "[data-testid='contributorName'] a, .ContributorLink"
    )
    if more_authors:
        names = [a.get_text(strip=True) for a in more_authors if _text(a)]
        if data["Author"] and data["Author"] in names:
            names = [n for n in names if n != data["Author"]]
        if names:
            data["Additional Authors"] = ", ".join(names)

    # ---- Average rating
    if not data["Average Rating"]:
        rating_selectors = [
            "[data-testid='rating']",
            "span[itemprop='ratingValue']",
            ".RatingStatistics__rating",
        ]
        
        for selector in rating_selectors:
            rating = soup.select_one(selector)
            if rating:
                text = _text(rating)
                # Sayı çıkar
                m = re.search(r"(\d+\.?\d*)", text)
                if m:
                    data["Average Rating"] = m.group(1)
                    break

    # ---- Book Id
    m = re.search(r"/book/show/(\d+)", url)
    if m:
        data["Book Id"] = m.group(1)

    # ---- Details block
    details_selectors = [
        "[data-testid='bookDetails']",
        ".DetailsLayoutRightParagraph",
        ".FeaturedDetails",
    ]
    
    details_block = None
    for selector in details_selectors:
        details_block = soup.select_one(selector)
        if details_block:
            break

    if details_block:
        details_text = details_block.get_text("\n", strip=True)
    else:
        # Tüm sayfayı tara
        details_text = soup.get_text("\n")

    # Sayfa sayısı
    if not data["Number of Pages"]:
        m = re.search(r"(\d+)\s*pages?", details_text, re.I)
        if m:
            data["Number of Pages"] = m.group(1)

    # Dil
    if not data["Language"]:
        m = re.search(r"Language\s*:?\s*([A-Za-zçğıöşİĞÖŞÜ\- ]+)", details_text, re.I)
        if m:
            data["Language"] = m.group(1).strip()

    # ISBN
    if not data["ISBN"]:
        m = re.search(r"ISBN(?:-10)?:?\s*([0-9Xx\-]{9,})", details_text)
        if m:
            data["ISBN"] = m.group(1).replace("-", "").upper()
    
    if not data["ISBN13"]:
        m = re.search(r"ISBN13:?\s*([0-9\-]{13,})", details_text, re.I)
        if m:
            data["ISBN13"] = re.sub(r"\D", "", m.group(1))

    # Yayın yılı
    if not data["Year Published"]:
        # "Published 2020" gibi
        m = re.search(r"Published\s+.*?(\d{4})", details_text, re.I)
        if m:
            data["Year Published"] = m.group(1)
        else:
            # Herhangi bir 4 haneli yıl
            years = re.findall(r"\b(19\d{2}|20\d{2})\b", details_text)
            if years:
                data["Year Published"] = years[0]

    # Orijinal yayın
    if not data["Original Publication Year"]:
        m = re.search(r"(?:First published|Originally published)\s+.*?(\d{4})", details_text, re.I)
        if m:
            data["Original Publication Year"] = m.group(1)

    # Publisher
    if not data["Publisher"]:
        m = re.search(r"Published\s+.*?by\s+([^,\n]+)", details_text, re.I)
        if m:
            data["Publisher"] = m.group(1).strip()

    # Debug
    found_count = sum(1 for v in data.values() if v)
    print(f"  ✅ Scraped: {data['Title'] or 'NO TITLE'} ({found_count}/14 fields)")
    
    return data
