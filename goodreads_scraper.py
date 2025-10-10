# -*- coding: utf-8 -*-
"""
Robust Goodreads scraper:
- Prefers JSON-LD (schema.org/Book)
- Falls back to OG meta for title/cover
- Extracts Book Id from the URL
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
import os
import requests
from bs4 import BeautifulSoup


GOODREADS_BOOK_ID_RE = re.compile(r"/book/show/(\d+)")

def _ua() -> str:
    return os.getenv(
        "USER_AGENT",
        # makul bir UA (GitHub Actions’ta 403 riskini azaltır)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


@dataclass
class BookData:
    goodreadsURL: Optional[str] = None
    BookId: Optional[int] = None
    Title: Optional[str] = None
    CoverURL: Optional[str] = None
    Author: Optional[str] = None
    AdditionalAuthors: Optional[str] = None
    Publisher: Optional[str] = None
    YearPublished: Optional[int] = None
    OriginalPublicationYear: Optional[int] = None  # çoğu sayfada yok; boş kalabilir
    NumberOfPages: Optional[int] = None
    Language: Optional[str] = None
    ISBN: Optional[str] = None
    ISBN13: Optional[str] = None
    AverageRating: Optional[float] = None

    def to_notion_payload_dict(self) -> Dict[str, Any]:
        """
        Notion mapping adları (kolon başlıkları) ile aynı anahtarlar.
        """
        return {
            "goodreadsURL": self.goodreadsURL,
            "Book Id": self.BookId,
            "Title": self.Title,
            "Cover URL": self.CoverURL,
            "Author": self.Author,
            "Additional Authors": self.AdditionalAuthors,
            "Publisher": self.Publisher,
            "Year Published": self.YearPublished,
            "Original Publication Year": self.OriginalPublicationYear,
            "Number of Pages": self.NumberOfPages,
            "Language": self.Language,
            "ISBN": self.ISBN,
            "ISBN13": self.ISBN13,
            "Average Rating": self.AverageRating,
        }


def _clean(txt: Optional[str]) -> Optional[str]:
    if not txt:
        return None
    t = " ".join(txt.split())
    return t or None


def _first_str(x) -> Optional[str]:
    if isinstance(x, str):
        return x
    if isinstance(x, dict) and "name" in x:
        return x.get("name")
    if isinstance(x, list) and x:
        # list of dict/str
        if isinstance(x[0], dict):
            return x[0].get("name")
        if isinstance(x[0], str):
            return x[0]
    return None


def _extract_jsonld(soup: BeautifulSoup) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.text or "{}")
            if isinstance(data, dict):
                candidates.append(data)
            elif isinstance(data, list):
                candidates.extend([d for d in data if isinstance(d, dict)])
        except Exception:
            continue

    # Book nesnesini seç
    for d in candidates:
        t = d.get("@type")
        if t == "Book" or (isinstance(t, list) and "Book" in t):
            return d
    return {}


def _extract_og(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find(
        "meta", attrs={"name": prop}
    )
    return _clean(tag["content"]) if tag and tag.has_attr("content") else None


def _book_id_from_url(url: str) -> Optional[int]:
    m = GOODREADS_BOOK_ID_RE.search(url)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def scrape_goodreads(url: str) -> BookData:
    sess = requests.Session()
    sess.headers.update({"User-Agent": _ua(), "Accept-Language": "en-US,en;q=0.8,tr;q=0.7"})
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()

    final_url = resp.url  # olası yönlendirme sonrası
    soup = BeautifulSoup(resp.text, "html.parser")

    jsonld = _extract_jsonld(soup)

    # ---- temel alanlar
    title = _clean(jsonld.get("name"))
    if not title:
        # og:title çoğu zaman "Title by Author — Goodreads" biçiminde
        ogt = _extract_og(soup, "og:title")
        if ogt and " by " in ogt:
            title = _clean(ogt.split(" by ", 1)[0])
        else:
            title = _clean(ogt)

    author = _first_str(jsonld.get("author"))
    author = _clean(author)

    cover = _extract_og(soup, "og:image")

    publisher = _first_str(jsonld.get("publisher"))
    publisher = _clean(publisher)

    # Tarihler
    year_published = None
    dp = _first_str(jsonld.get("datePublished"))
    if dp:
        # YYYY veya YYYY-MM-DD gelebilir
        m = re.search(r"\d{4}", dp)
        if m:
            year_published = int(m.group(0))

    # JSON-LD’de genelde originalPublicationYear yok;
    # bulabilirsek doldururuz, yoksa None kalsın.
    original_year = None

    # Sayfa sayısı
    pages = None
    try:
        pages = int(str(jsonld.get("numberOfPages")).strip()) if jsonld.get("numberOfPages") else None
    except Exception:
        pages = None

    language = _first_str(jsonld.get("inLanguage"))
    language = _clean(language)

    isbn = _first_str(jsonld.get("isbn"))
    isbn = _clean(isbn)
    isbn13 = None
    if isbn:
        if len(re.sub(r"[^0-9Xx]", "", isbn)) == 13:
            isbn13 = isbn
            isbn = None
        elif len(re.sub(r"[^0-9Xx]", "", isbn)) == 10:
            # ISBN10 ise olduğu gibi ISBN alanına
            pass
        else:
            # biçimlenmiş/bozuksa rich_text’e aynen geçer
            pass

    rating = None
    agg = jsonld.get("aggregateRating") or {}
    if isinstance(agg, dict):
        rv = agg.get("ratingValue")
        try:
            rating = float(rv)
        except Exception:
            rating = None

    # Book Id URL’den
    book_id = _book_id_from_url(final_url) or _book_id_from_url(url)

    data = BookData(
        goodreadsURL=final_url,
        BookId=book_id,
        Title=title,
        CoverURL=cover,
        Author=author,
        AdditionalAuthors=None,
        Publisher=publisher,
        YearPublished=year_published,
        OriginalPublicationYear=original_year,
        NumberOfPages=pages,
        Language=language,
        ISBN=isbn,
        ISBN13=isbn13,
        AverageRating=rating,
    )
    return data


if __name__ == "__main__":
    import sys
    u = sys.argv[1] if len(sys.argv) > 1 else "https://www.goodreads.com/book/show/13038020"
    bd = scrape_goodreads(u)
    print(json.dumps(bd.to_notion_payload_dict(), ensure_ascii=False, indent=2))
