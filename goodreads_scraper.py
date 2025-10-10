# goodreads_scraper.py
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional
import time


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def _make_soup(html: str) -> BeautifulSoup:
    """Robust soup maker: lxml -> html5lib -> html.parser"""
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


def fetch_goodreads(url: str) -> Dict[str, Optional[str]]:
    """
    Goodreads kitap sayfasından temel alanları çeker.
    """
    print(f"  🔍 Fetching: {url}")
    
    # Rate limiting (Goodreads'i rahatsız etmeyelim)
    time.sleep(1)
    
    try:
        session = requests.Session()
        res = session.get(url, headers=HEADERS, timeout=30)
        res.raise_for_status()
    except Exception as e:
        print(f"  ❌ Request failed: {e}")
        raise
    
    soup = _make_soup(res.text)
    
    # Debug: HTML'in ilk kısmını yazdır
    print(f"  📄 HTML Length: {len(res.text)} chars")
    
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

    # ---- Title (Birden fazla selector deneyelim)
    title_selectors = [
        "h1[data-testid='bookTitle']",
        "h1.Text__title1",
        "h1#bookTitle",
        "h1.BookPageTitleSection__title",
        "h1[itemprop='name']",
        ".BookPageTitleSection h1",
    ]
    
    for selector in title_selectors:
        h1 = soup.select_one(selector)
        if h1:
            data["Title"] = _text(h1)
            print(f"  ✅ Title found with selector: {selector}")
            break
    
    if not data["Title"]:
        # Son çare: tüm h1'leri kontrol et
        all_h1 = soup.find_all("h1")
        if all_h1:
            data["Title"] = _text(all_h1[0])
            print(f"  ⚠️  Title found via fallback h1")

    # ---- Cover URL
    cover_selectors = [
        "img.BookCover__image",
        "img#coverImage",
        "img[itemprop='image']",
        ".BookCover img",
        ".bookCoverContainer img",
    ]
    
    for selector in cover_selectors:
        cover = soup.select_one(selector)
        if cover and cover.get("src"):
            data["Cover URL"] = cover["src"]
            break

    # ---- Author(s)
    author_selectors = [
        "[data-testid='name'] a",
        "a.authorName__container",
        "a.authorName span[itemprop='name']",
        ".ContributorLink__name",
        "span[itemprop='author'] a",
    ]
    
    for selector in author_selectors:
        author_main = soup.select_one(selector)
        if author_main:
            data["Author"] = _text(author_main)
            break

    more_authors = soup.select(
        "[data-testid='contributorName'] a, a.contributorName__container, .ContributorLink"
    )
    if more_authors:
        names = [a.get_text(strip=True) for a in more_authors if _text(a)]
        if data["Author"] in names and data["Author"]:
            names = [n for n in names if n != data["Author"]]
        data["Additional Authors"] = ", ".join(names) if names else None

    # ---- Average rating
    rating_selectors = [
        "[data-testid='rating'] [aria-label*='/']",
        "span[itemprop='ratingValue']",
        ".RatingStatistics__rating",
    ]
    
    for selector in rating_selectors:
        rating = soup.select_one(selector)
        if rating:
            data["Average Rating"] = _text(rating)
            break

    # ---- Book Id
    m = re.search(r"/book/show/(\d+)", url)
    if m:
        data["Book Id"] = m.group(1)

    # ---- Details block
    details_selectors = [
        "[data-testid='bookDetails']",
        "#bookDataBox",
        ".BookDetails",
        ".FeaturedDetails",
    ]
    
    details_block = None
    for selector in details_selectors:
        details_block = soup.select_one(selector)
        if details_block:
            break

    details_text = details_block.get_text("\n", strip=True) if details_block else ""

    # Sayfa sayısı
    m = re.search(r"(\d+)\s+pages?", details_text, re.I)
    if m:
        data["Number of Pages"] = m.group(1)

    # Dil
    m = re.search(r"Language\s*:?\s*([A-Za-zçğıöşİĞÖŞÜ\- ]+)", details_text, re.I)
    if m:
        data["Language"] = m.group(1).strip()

    # ISBN / ISBN13
    m = re.search(r"ISBN(?:-10)?:?\s*([0-9Xx\-]{9,})", details_text)
    if m:
        data["ISBN"] = m.group(1).replace("-", "").upper()
    m = re.search(r"ISBN13:?\s*([0-9\-]{13,})", details_text, re.I)
    if m:
        data["ISBN13"] = re.sub(r"\D", "", m.group(1))

    # Yayın bilgisi
    pub_line = None
    for line in details_text.splitlines():
        if "Published" in line or "Yayın" in line or "Basım" in line:
            pub_line = line.strip()
            break
    if pub_line:
        m = re.search(r"(\d{4})", pub_line)
        if m:
            data["Year Published"] = m.group(1)

        m = re.search(r"\d{4}\D+by\s+(.+)$", pub_line, re.I)
        if m:
            data["Publisher"] = m.group(1).strip()

    # Orijinal yayın yılı
    m = re.search(r"First published\s+.*?(\d{4})", details_text, re.I)
    if m:
        data["Original Publication Year"] = m.group(1)

    # Debug çıktısı
    found_fields = [k for k, v in data.items() if v and k != "goodreadsURL"]
    print(f"  ✅ Scraped: {data['Title'] or 'NO TITLE'}")
    print(f"  📊 Found {len(found_fields)} fields: {', '.join(found_fields[:5])}")
    
    return data
