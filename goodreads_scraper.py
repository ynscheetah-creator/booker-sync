# goodreads_scraper.py  —  v2 (strong fallbacks for title/author)

from __future__ import annotations
import json, re, os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
import requests
from bs4 import BeautifulSoup

GOODREADS_BOOK_ID_RE = re.compile(r"/book/show/(\d+)")

def _ua() -> str:
    return os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
    OriginalPublicationYear: Optional[int] = None
    NumberOfPages: Optional[int] = None
    Language: Optional[str] = None
    ISBN: Optional[str] = None
    ISBN13: Optional[str] = None
    AverageRating: Optional[float] = None

    def to_notion_payload_dict(self) -> Dict[str, Any]:
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

def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = " ".join(s.split())
    return s or None

def _first_str(x) -> Optional[str]:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if "name" in x:
            return x.get("name")
    if isinstance(x, list) and x:
        v = x[0]
        if isinstance(v, dict) and "name" in v:
            return v.get("name")
        if isinstance(v, str):
            return v
    return None

def _extract_jsonld(soup: BeautifulSoup) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.text or "{}")
            if isinstance(data, dict):
                out.append(data)
            elif isinstance(data, list):
                out.extend([d for d in data if isinstance(d, dict)])
        except Exception:
            pass
    for d in out:
        t = d.get("@type")
        if t == "Book" or (isinstance(t, list) and "Book" in t):
            return d
    return {}

def _meta(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return _clean(tag["content"]) if tag and tag.has_attr("content") else None

def _book_id_from_url(url: str) -> Optional[int]:
    m = GOODREADS_BOOK_ID_RE.search(url)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

# ---------- NEW: strong fallbacks for title/author ----------

def _fallback_title(soup: BeautifulSoup) -> Optional[str]:
    # 1) og:title (çoğu sayfada: "Title by Author — Goodreads")
    ogt = _meta(soup, "og:title")
    if ogt:
        # " — Goodreads" / " - Goodreads" / " | Goodreads" ayracı
        for sep in (" — Goodreads", " - Goodreads", " | Goodreads"):
            if sep in ogt:
                ogt = ogt.split(sep, 1)[0]
                break
        # " by " varsa, soldaki kısım başlık
        if " by " in ogt:
            ogt = ogt.split(" by ", 1)[0]
        if ogt.strip():
            return _clean(ogt)

    # 2) sayfa <title>
    t = soup.find("title")
    if t and _clean(t.text):
        tt = _clean(t.text)
        for sep in (" — Goodreads", " - Goodreads", " | Goodreads"):
            if sep in tt:
                tt = tt.split(sep, 1)[0]
                break
        if " by " in tt:
            tt = tt.split(" by ", 1)[0]
        if tt.strip():
            return _clean(tt)

    # 3) Görsel başlık h1 – yeni UI’de sık kullanılıyor
    h1 = soup.select_one('h1[data-testid="bookTitle"], h1')
    if h1 and _clean(h1.text):
        return _clean(h1.text)

    return None

def _fallback_author(soup: BeautifulSoup) -> Optional[str]:
    # 1) meta name="author"
    ma = _meta(soup, "author")
    if ma:
        return _clean(ma)

    # 2) og:title "Title by Author" ise sağ taraf
    ogt = _meta(soup, "og:title")
    if ogt and " by " in ogt:
        right = ogt.split(" by ", 1)[1]
        # sondaki " — Goodreads" vb. at
        for sep in (" — Goodreads", " - Goodreads", " | Goodreads"):
            if sep in right:
                right = right.split(sep, 1)[0]
                break
        if right.strip():
            return _clean(right)

    # 3) author link’leri (yeni UI): /author/show/.. içeren ilk link
    a = soup.select_one('a[href*="/author/show/"]')
    if a and _clean(a.text):
        return _clean(a.text)

    # 4) data-testid ile name
    a2 = soup.select_one('a[data-testid="name"]')
    if a2 and _clean(a2.text):
        return _clean(a2.text)

    return None

# ------------------------------------------------------------

def scrape_goodreads(url: str) -> BookData:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": _ua(),
        # TR sayfalar için Türkçe de ekleyelim
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()

    final_url = resp.url
    soup = BeautifulSoup(resp.text, "html.parser")

    jsonld = _extract_jsonld(soup)

    # Title
    title = _clean(jsonld.get("name")) or _fallback_title(soup)

    # Author
    author = _first_str(jsonld.get("author")) or _fallback_author(soup)
    author = _clean(author)

    # Cover
    cover = _meta(soup, "og:image")

    # Publisher, YearPublished
    publisher = _clean(_first_str(jsonld.get("publisher")))
    year_published = None
    dp = _first_str(jsonld.get("datePublished"))
    if dp:
        m = re.search(r"\d{4}", dp)
        if m:
            year_published = int(m.group(0))

    original_year = None  # çoğu sayfada yok

    # Pages
    pages = None
    if jsonld.get("numberOfPages") is not None:
        try:
            pages = int(str(jsonld.get("numberOfPages")).strip())
        except Exception:
            pages = None

    language = _clean(_first_str(jsonld.get("inLanguage")))

    # ISBN / ISBN13
    isbn10, isbn13 = None, None
    isb = _clean(_first_str(jsonld.get("isbn")))
    if isb:
        digits = re.sub(r"[^0-9Xx]", "", isb)
        if len(digits) == 13:
            isbn13 = isb
        elif len(digits) == 10:
            isbn10 = isb

    # Rating
    rating = None
    agg = jsonld.get("aggregateRating") or {}
    if isinstance(agg, dict):
        rv = agg.get("ratingValue")
        try:
            rating = float(rv)
        except Exception:
            pass

    # Book Id
    book_id = _book_id_from_url(final_url) or _book_id_from_url(url)

    return BookData(
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
        ISBN=isbn10,
        ISBN13=isbn13,
        AverageRating=rating,
    )

if __name__ == "__main__":
    import sys, json as _json
    u = sys.argv[1] if len(sys.argv) > 1 else "https://www.goodreads.com/book/show/13038020"
    bd = scrape_goodreads(u).to_notion_payload_dict()
    print(_json.dumps(bd, ensure_ascii=False, indent=2))
