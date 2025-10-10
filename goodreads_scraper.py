# -*- coding: utf-8 -*-
from __future__ import annotations
import re, html, time
from typing import Dict, Optional
import requests
from bs4 import BeautifulSoup

def _ua(ua: Optional[str]) -> str:
    return ua or ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36")

def _clean(x: Optional[str]) -> str:
    if not x: return ""
    x = html.unescape(x)
    return re.sub(r"\s+", " ", x).strip()

def _int_in(s: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", s or "")
    return int(m.group(0)) if m else None

def _only_int(s: str) -> Optional[int]:
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None

def _sel_text(soup: BeautifulSoup, css: str) -> str:
    el = soup.select_one(css)
    return _clean(el.get_text(" ", strip=True)) if el else ""

def _og_image(soup: BeautifulSoup) -> Optional[str]:
    m = soup.find("meta", property="og:image")
    return m["content"].strip() if m and m.get("content") else None

def _row_value(soup: BeautifulSoup, label_contains: str) -> Optional[str]:
    # yeni tasarım BookDetails satırı
    row = soup.select_one(
        f".BookDetails .BookDetails__row:has(.BookDetails__label:contains('{label_contains}'))"
    )
    if row:
        val = row.select_one(".BookDetails__description") or row
        return _clean(val.get_text(" ", strip=True))
    # fallback
    cand = soup.find(string=re.compile(label_contains, re.I))
    if cand:
        return _clean(cand.find_parent().get_text(" ", strip=True))
    return None

def _publisher_from_published(text: str) -> Optional[str]:
    if not text: return None
    pub = ""
    if " by " in text: pub = text.split(" by ")[-1]
    elif "by" in text: pub = text.split("by")[-1]
    pub = _clean(pub)
    if not pub or any(ch.isdigit() for ch in pub): return None
    return pub

def fetch_goodreads(url: str, ua: Optional[str] = None, timeout: int = 25) -> Dict[str, Optional[str]]:
    headers = {"User-Agent": _ua(ua), "Accept-Language": "en-US,en;q=0.8,tr;q=0.7"}
    r = requests.get(url.strip(), headers=headers, timeout=timeout, allow_redirects=True)
    if r.status_code in (403, 503):  # CF anlık
        time.sleep(1.0)
        r = requests.get(url.strip(), headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # temel alanlar
    title  = _sel_text(soup, "h1[data-testid='bookTitle']") or _sel_text(soup, "#bookTitle")
    author = _sel_text(soup, "a.ContributorLink__name") or _sel_text(soup, "span.AuthorName__name") \
             or _sel_text(soup, "a.authorName span")

    # yayınevi & yıl (Published satırından)
    published = _row_value(soup, "Published") or ""
    publisher = _publisher_from_published(published)
    year_pub  = _int_in(published)

    # sayfa sayısı
    pages = _row_value(soup, "pages") or _sel_text(soup, "[data-testid='pagesFormat']")
    pages_n = _only_int(pages)

    # dil
    language = _row_value(soup, "Edition language")
    # isbn / isbn13
    isbn13_block = _row_value(soup, "ISBN13") or ""
    m13 = re.search(r"(97(8|9))\d{10}", isbn13_block.replace("-", ""))
    isbn13 = m13.group(0) if m13 else None

    isbn_block = _row_value(soup, "ISBN") or ""
    m10 = re.search(r"\b(\d{9}[\dXx])\b", isbn_block.replace("-", ""))
    isbn = m10.group(1).upper() if m10 else None

    # puan
    rating = _sel_text(soup, "[data-testid='rating']") or _sel_text(soup, "span[itemprop='ratingValue']")
    try:
        avg_rating = float(rating.replace(",", ".")) if rating else None
    except Exception:
        avg_rating = None

    # kapak
    cover = _og_image(soup) or None
    if not cover:
        img = soup.select_one("[data-testid='coverImage'] img") or soup.select_one("img.BookCover__image")
        if img and img.get("src"): cover = img["src"]

    # book id
    book_id = None
    m_id = re.search(r"/book/show/(\d+)", r.url)
    if m_id: book_id = int(m_id.group(1))

    return {
        "Title": title or None,
        "Author": author or None,
        "Additional Authors": None,           # (istersen genişletebilirsin)
        "Publisher": publisher,
        "Year Published": year_pub,
        "Original Publication Year": None,    # GR bazı sayfalarda ayrı; şimdilik boş
        "Number of Pages": pages_n,
        "Language": language,
        "ISBN": isbn,
        "ISBN13": isbn13,
        "Average Rating": avg_rating,
        "coverURL": cover,
        "Book Id": book_id,
        "goodreadsURL": r.url,                # canonical url
    }
