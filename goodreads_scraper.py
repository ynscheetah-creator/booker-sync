# -*- coding: utf-8 -*-
from __future__ import annotations
import re
import html
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

HEADERS_DEFAULT = lambda ua: {
    "User-Agent": ua or (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8,tr;q=0.7",
}

def _clean_text(x: Optional[str]) -> str:
    if not x:
        return ""
    x = html.unescape(x)
    x = re.sub(r"\s+", " ", x).strip()
    return x

def _int_or_none(s: str) -> Optional[int]:
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None

def _meta_og_image(soup: BeautifulSoup) -> Optional[str]:
    m = soup.find("meta", property="og:image")
    if m and m.get("content"):
        return m["content"].strip()
    return None

def _select_text(soup: BeautifulSoup, css: str) -> str:
    el = soup.select_one(css)
    return _clean_text(el.get_text(" ", strip=True)) if el else ""

def _extract_published_row(soup: BeautifulSoup) -> str:
    """
    Goodreads yeni tasarım:
      - data-testid'li BookDetails satırları var
      - 'Published' label'ını taşıyan satırdan metni al
    Eski tasarım (fallback) için de bir iki seçenek deniyoruz.
    """
    # Yeni tasarım – label 'Published'
    row = soup.select_one(
        ".BookDetails .BookDetails__row:has(.BookDetails__label:contains('Published'))"
    )
    if row:
        return _select_text(row, ".BookDetails__row")

    # Alternatif yeni tasarım
    row2 = soup.select_one("div[data-testid='publicationInfo']")
    if row2:
        return row2.get_text(" ", strip=True)

    # Eski tasarım fallback
    for cand in soup.find_all(["div", "span", "td"]):
        try:
            txt = cand.get_text(" ", strip=True)
        except Exception:
            continue
        if txt and txt.lower().startswith("published"):
            return txt
    return ""

def _publisher_from_published(text: str) -> Optional[str]:
    """Only pick the 'by <publisher>' part from the Published text."""
    if not text:
        return None
    # en güvenilir yaklaşım: ' by ' ile ayır
    if " by " in text:
        pub = text.split(" by ")[-1].strip()
    elif "by" in text:
        pub = text.split("by")[-1].strip()
    else:
        pub = ""

    pub = _clean_text(pub)
    # Rakam barındırıyorsa (yıl/sayfa) muhtemelen yanlış
    if any(ch.isdigit() for ch in pub):
        return None
    # Kısa çöplerden kaç
    if len(pub) < 2:
        return None
    return pub

def _year_from_published(text: str) -> Optional[int]:
    """
    Published ... 1 September 1952 by ... → 1952
    """
    if not text:
        return None
    m = re.search(r"(19|20)\d{2}", text)
    return int(m.group(0)) if m else None

def _pages_from_block(soup: BeautifulSoup) -> Optional[int]:
    """
    Yeni tasarımda: data-testid='pagesFormat' içinde '138 pages' gibi.
    """
    t = _select_text(soup, "[data-testid='pagesFormat']")
    if not t:
        # eski tasarım: 'pages' içeren küçük stringler
        candidate = soup.find(string=re.compile(r"\bpages\b", re.I))
        t = _clean_text(candidate) if candidate else ""
    return _int_or_none(t)

def _language_from_details(soup: BeautifulSoup) -> Optional[str]:
    # Yeni tasarım: 'Edition language' satırı
    row = soup.select_one(
        ".BookDetails .BookDetails__row:has(.BookDetails__label:contains('Edition language'))"
    )
    if row:
        val = row.select_one(".BookDetails__description")
        if val:
            return _clean_text(val.get_text(" ", strip=True))
    # Eski tasarım (fallback)
    candidate = soup.find(string=re.compile(r"Edition language", re.I))
    if candidate:
        parent = candidate.find_parent()
        if parent:
            return _clean_text(parent.get_text(" ", strip=True).replace("Edition language", ""))
    return None

def _isbn13_from_details(soup: BeautifulSoup) -> Optional[str]:
    # Yeni tasarım: 'ISBN13' satırı
    row = soup.select_one(
        ".BookDetails .BookDetails__row:has(.BookDetails__label:contains('ISBN13'))"
    )
    if row:
        val = row.select_one(".BookDetails__description")
        if val:
            text = _clean_text(val.get_text(" ", strip=True))
            m = re.search(r"(97(8|9))\d{10}", text.replace("-", ""))
            if m:
                return m.group(0)
    # Eski tasarım fallback
    m = soup.find(string=re.compile(r"ISBN13", re.I))
    if m:
        candidate = _clean_text(m.parent.get_text(" ", strip=True))
        mm = re.search(r"(97(8|9))\d{10}", candidate.replace("-", ""))
        if mm:
            return mm.group(0)
    return None

def _description(soup: BeautifulSoup) -> Optional[str]:
    # data-testid'li açıklama kutuları
    d = soup.select_one("[data-testid='description']") or soup.select_one("[data-testid='bookDescription']")
    if d:
        return _clean_text(d.get_text(" ", strip=True))
    # fallback
    d2 = soup.select_one("#description") or soup.select_one(".description")
    return _clean_text(d2.get_text(" ", strip=True)) if d2 else None

def _title(soup: BeautifulSoup) -> Optional[str]:
    # yeni
    t = _select_text(soup, "h1[data-testid='bookTitle']")
    if t:
        return t
    # eski
    t = _select_text(soup, "#bookTitle")
    return t or None

def _author(soup: BeautifulSoup) -> Optional[str]:
    # yeni
    a = _select_text(soup, "a.ContributorLink__name") or _select_text(soup, "span.AuthorName__name")
    if a:
        return a
    # eski
    a = _select_text(soup, "a.authorName span")
    return a or None

def fetch_goodreads(url: str, ua: Optional[str] = None, timeout: int = 25) -> Dict[str, Optional[str]]:
    """
    Goodreads kitap sayfasından alanları döndürür.
    Dönüş:
      Title, Author, Publisher, Year Published, Number of Pages, Language,
      ISBN13, Description, coverURL
    """
    url = url.strip()
    # bazen /book/show/ dışındaki url’ler yönleniyor → requests takip ediyor
    headers = HEADERS_DEFAULT(ua)
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()

    # Cloudflare vb. anlık engel durumlarında küçük bekleme tekrar
    if resp.status_code in (403, 503) and "cf" in resp.headers.get("server", "").lower():
        time.sleep(1.0)
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    data: Dict[str, Optional[str]] = {}

    data["Title"] = _title(soup)
    data["Author"] = _author(soup)

    # Published satırından publisher & year
    published_text = _extract_published_row(soup)
    data["Publisher"] = _publisher_from_published(published_text)
    y = _year_from_published(published_text)
    data["Year Published"] = y if y is None else int(y)

    # Sayfa sayısı
    data["Number of Pages"] = _pages_from_block(soup)

    # Dil
    data["Language"] = _language_from_details(soup)

    # ISBN13
    data["ISBN13"] = _isbn13_from_details(soup)

    # Description
    data["Description"] = _description(soup)

    # Kapak (og:image veya data-testid cover)
    cover = _meta_og_image(soup) or None
    if not cover:
        cover_img = soup.select_one("[data-testid='coverImage'] img") or soup.select_one("img.BookCover__image")
        if cover_img and cover_img.get("src"):
            cover = cover_img["src"]
    data["coverURL"] = cover

    # Temizle/Kısalt – uzun metinleri notion tarafında da sınırlıyoruz ama burada da sadeleyelim
    if data.get("Description"):
        data["Description"] = data["Description"][:1900]

    # Boş/yanlış publisher’ları None yap
    if data.get("Publisher"):
        pub = data["Publisher"]
        if any(ch.isdigit() for ch in pub or "") or len(pub or "") < 2:
            data["Publisher"] = None

    return data
