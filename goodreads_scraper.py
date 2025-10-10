# -*- coding: utf-8 -*-
"""
Goodreads kitap sayfasından (yalnızca /book/show/ …) alanları çeker.
JSON-LD yoksa yeni/klasik arayüz seçicileri ve TR/EN regex'leriyle fallback yapar.
"""
import json
import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.search(r"\d{1,4}", s)
    return int(m.group(0)) if m else None


def _find_book_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and (
                    it.get("@type") == "Book" or ("Book" in (it.get("@type") or []))
                ):
                    return it
        except Exception:
            continue
    return None


def _fallback_title(soup: BeautifulSoup) -> Optional[str]:
    el = soup.select_one('h1[data-testid="bookTitle"]') or soup.select_one("#bookTitle")
    return _clean(el.get_text()) if el else None


def _fallback_author(soup: BeautifulSoup) -> Optional[str]:
    # yeni arayüz
    els = soup.select('[data-testid="name"]') or soup.select(
        'a[data-testid="authorName"]'
    )
    if not els:
        # klasik
        els = soup.select("a.authorName span") or soup.select("a.authorName")
    if els:
        parts = [_clean(e.get_text()) for e in els]
        return ", ".join([p for p in parts if p])
    return None


def _fallback_isbn(soup: BeautifulSoup, html: str) -> Optional[str]:
    el = soup.find(attrs={"itemprop": "isbn"})
    if el and _clean(el.get_text()):
        return re.sub(r"[^0-9Xx]", "", _clean(el.get_text()))
    m = re.search(
        r'<meta[^>]+property=["\']books:isbn["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.I,
    )
    if m:
        return re.sub(r"[^0-9Xx]", "", m.group(1))
    m = re.search(
        r"ISBN(?:-13)?:?\s*</[^>]+>\s*([0-9\-Xx]{10,17})", html, flags=re.I
    )
    if m:
        return re.sub(r"[^0-9Xx]", "", m.group(1))
    return None


def _fallback_pages(soup: BeautifulSoup, html: str) -> Optional[int]:
    el = soup.find(attrs={"itemprop": "numberOfPages"})
    if el and _clean(el.get_text()):
        return _to_int(el.get_text())
    m = re.search(r"(\d{1,4})\s*(?:sayfa|pages)\b", html, flags=re.I)
    return int(m.group(1)) if m else None


def _fallback_publisher_year(html: str) -> (Optional[str], Optional[int]):
    pub = None
    year = None
    m = re.search(r"Published[^<]*?by\s*([^<]+)", html, flags=re.I)
    if m:
        pub = _clean(m.group(1))
    m = re.search(r"\b(19|20)\d{2}\b", html)
    if m:
        year = int(m.group(0))
    mt = re.search(r"Yayı[nn]c[ıi]:?\s*</[^>]+>\s*([^<]+)", html, flags=re.I)
    if mt and not pub:
        pub = _clean(mt.group(1))
    mt = re.search(r"Yayın\s*tarihi:?\s*</[^>]+>\s*([^<]+)", html, flags=re.I)
    if mt and not year:
        m2 = re.search(r"\b(19|20)\d{2}\b", mt.group(1))
        if m2:
            year = int(m2.group(0))
    return pub, year


def fetch_goodreads(url: str, ua: Optional[str] = None) -> Dict:
    """
    Goodreads kitap sayfasından başlık, yazar, yıl, yayınevi, sayfa sayısı, ISBN,
    açıklama ve kapak görseli URL'sini döndürür.
    """
    headers = {
        "User-Agent": ua or "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
        "Referer": "https://www.google.com/",
    }
    try:
        r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
    except Exception:
        return {}

    if r.status_code != 200 or not r.text:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    html = r.text

    # canonical kitap linkine geç (kısaltılmış/yan URL'lerde)
    canon = soup.find("link", attrs={"rel": "canonical"})
    if canon and canon.has_attr("href"):
        href = canon["href"]
        if "/book/show/" in href and href != r.url:
            r = requests.get(href, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code == 200 and r.text:
                soup = BeautifulSoup(r.text, "html.parser")
                html = r.text

    # og metas
    og_image = soup.find("meta", {"property": "og:image"})
    og_title = soup.find("meta", {"property": "og:title"})
    og_desc = soup.find("meta", {"property": "og:description"})
    cover = _clean(og_image["content"]) if og_image and og_image.has_attr("content") else None
    ogt = _clean(og_title["content"]) if og_title and og_title.has_attr("content") else None
    desc = _clean(og_desc["content"]) if og_desc and og_desc.has_attr("content") else None

    # JSON-LD
    jd = _find_book_json_ld(soup) or {}

    # Title
    title = _clean(jd.get("name")) or ogt or _fallback_title(soup)

    # Author
    author = None
    if jd.get("author"):
        if isinstance(jd["author"], list):
            author = ", ".join(
                [_clean(a.get("name")) for a in jd["author"] if isinstance(a, dict) and a.get("name")]
            )
        elif isinstance(jd["author"], dict):
            author = _clean(jd["author"].get("name"))
    if not author:
        author = _fallback_author(soup)

    # Publisher & Year
    publisher = _clean(jd.get("publisher", {}).get("name") if isinstance(jd.get("publisher"), dict) else jd.get("publisher"))
    year = None
    if isinstance(jd.get("datePublished"), str) and jd["datePublished"][:4].isdigit():
        year = int(jd["datePublished"][:4])
    if not publisher or not year:
        p2, y2 = _fallback_publisher_year(html)
        if not publisher:
            publisher = p2
        if not year:
            year = y2

    # Pages & ISBN & Language
    pages = jd.get("numberOfPages")
    if isinstance(pages, str):
        pages = _to_int(pages)
    if not pages:
        pages = _fallback_pages(soup, html)

    isbn13 = _clean(jd.get("isbn")) or _fallback_isbn(soup, html)

    lang = _clean(jd.get("inLanguage"))
    if lang:
        lang = lang.upper()

    description = _clean(jd.get("description")) or desc

    # ---- güvenlik: Notion limitleri (rich_text max ~2000) ----
    if publisher:
        publisher = publisher.replace("\n", " ").strip()[:200]
    if title:
        title = title.strip()[:1000]
    if author:
        author = author.strip()[:1000]
    if description:
        description = description.strip()[:1900]

    data = {
        "Title": title,
        "Author": author,
        "Publisher": publisher,
        "Year Published": year,
        "Number of Pages": pages,
        "ISBN13": isbn13,
        "Language": lang,
        "Description": description,
        "coverURL": cover,
        "source": "goodreads",
    }

    # tamamen boşsa veri dönme
    if not any([title, author, cover, isbn13]):
        print(f"WARN could not parse GR: {url}")
        return {}

    return data
