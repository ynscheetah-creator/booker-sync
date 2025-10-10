# -*- coding: utf-8 -*-
"""
Goodreads kitap sayfasından (yalnızca /book/show/ …) alanları çeker.
JSON-LD yoksa yeni/klasik arayüz seçicileri ve TR/EN regex'leriyle fallback yapar.
'This edition' bloğuna öncelik verilir; publisher/year/pages/language burada aranır.
"""
import json
import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup


# -------------------- yardımcılar --------------------

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

def _slice_after(html: str, anchors, window: int = 3000) -> Optional[str]:
    """HTML içinde verilen anchordan sonraki dar bir pencere döndür."""
    if isinstance(anchors, str):
        anchors = [anchors]
    for a in anchors:
        m = re.search(re.escape(a), html, flags=re.I)
        if m:
            start = m.start()
            return html[start:start + window]
    return None

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
    # yeni arayüz çeşitleri
    sels = [
        '[data-testid="name"]',
        'a[data-testid="authorName"]',
        '.ContributorLink__name',     # yeni sınıf isimleri
    ]
    els = None
    for sel in sels:
        els = soup.select(sel)
        if els:
            break
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
        html, flags=re.I,
    )
    if m:
        return re.sub(r"[^0-9Xx]", "", m.group(1))
    m = re.search(r'ISBN(?:-13)?:?\s*</[^>]+>\s*([0-9\-Xx]{10,17})', html, flags=re.I)
    if m:
        return re.sub(r"[^0-9Xx]", "", m.group(1))
    return None

def _fallback_pages(soup: BeautifulSoup, html: str) -> Optional[int]:
    el = soup.find(attrs={"itemprop": "numberOfPages"})
    if el and _clean(el.get_text()):
        return _to_int(el.get_text())
    # 138 pages / 138 pages / 138 page / 138 sayfa
    m = re.search(r'(\d{1,4})\s*(?:pages?|sayfa)\b', html, flags=re.I)
    return int(m.group(1)) if m else None

def _fallback_publisher_year_from_block(block: str) -> (Optional[str], Optional[int]):
    """'This edition' veya benzeri dar blok içinde Published satırından çıkar."""
    pub = None
    year = None
    if not block:
        return pub, year
    # Published ... 1952 ... by Varlık Yayınları
    my = re.search(r'Published[^<\n]*?\b(1[5-9]\d{2}|20\d{2})\b', block, flags=re.I)
    if my:
        year = int(my.group(1))
    mp = re.search(r'Published[^<\n]*?by\s*([^<,\n]+)', block, flags=re.I)
    if mp:
        pub = _clean(mp.group(1))
    return pub, year

def _fallback_language_from_block(block: str) -> Optional[str]:
    if not block:
        return None
    # Language: Turkish
    ml = re.search(r'Language[^:<\n]*[:>]\s*([A-Za-zÇĞİÖŞÜçğıöşü\- ]+)', block, flags=re.I)
    if ml:
        return _clean(ml.group(1))
    return None

# -------------------- ana fonksiyon --------------------

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
    og_desc  = soup.find("meta", {"property": "og:description"})
    cover = _clean(og_image["content"]) if og_image and og_image.has_attr("content") else None
    ogt   = _clean(og_title["content"]) if og_title and og_title.has_attr("content") else None
    desc  = _clean(og_desc["content"])  if og_desc and og_desc.has_attr("content") else None

    # JSON-LD
    jd = _find_book_json_ld(soup) or {}

    # Title
    title = _clean(jd.get("name")) or ogt or _fallback_title(soup)

    # Author
    author = None
    if jd.get("author"):
        if isinstance(jd["author"], list):
            author = ", ".join([_clean(a.get("name")) for a in jd["author"] if isinstance(a, dict) and a.get("name")])
        elif isinstance(jd["author"], dict):
            author = _clean(jd["author"].get("name"))
    if not author:
        author = _fallback_author(soup)

    # ---- “This edition / Format / Published” bloğunu daralt ----
    details = _slice_after(html, ["This edition", "Format", "Published"], window=3500)

    # Publisher & Year (önce dar blokta dene)
    pub, year = _fallback_publisher_year_from_block(details)
    if not year:
        # “First published … 1933” gibi satırdan yıl
        mf = re.search(r'First published[^<\n]*?\b(1[5-9]\d{2}|20\d{2})\b', html, flags=re.I)
        if mf:
            year = int(mf.group(1))
    if not pub:
        # geniş fallback (riskli ama son çare)
        p2, y2 = _fallback_publisher_year_from_block(html)
        pub = pub or p2
        year = year or y2

    # Pages
    pages = _fallback_pages(soup, details or html)

    # ISBN
    isbn13 = _clean(jd.get("isbn")) or _fallback_isbn(soup, html)

    # Language
    lang = _clean(jd.get("inLanguage")) or _fallback_language_from_block(details or html)
    if lang:
        lang = lang.title() if len(lang) < 6 else lang  # Turkish / English vs.
        # normalize tek kelimeyi büyük harfe çevirmek istemeyebiliriz
        lang = _clean(lang)

    # Description
    description = _clean(jd.get("description")) or desc

    # ---- Notion güvenlik limitleri ----
    if pub:
        pub = pub.replace("\n", " ").strip()[:200]
    if title:
        title = title.strip()[:1000]
    if author:
        author = author.strip()[:1000]
    if description:
        description = description.strip()[:1900]

    data = {
        "Title": title,
        "Author": author,
        "Publisher": pub,
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
