import re
import json
from typing import Dict, Optional
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}

ID_RE = re.compile(r"/book/show/(\d+)")
YEAR_RE = re.compile(r"(19|20)\d{2}")
PAGE_RE = re.compile(r"(\d+)\s*pages", re.I)
ISBN_RE = re.compile(r"(\d{9,13}[0-9xX])")


def _clean(txt: Optional[str]) -> Optional[str]:
    if not txt:
        return None
    return re.sub(r"\s+", " ", txt).strip()


def fetch_goodreads(url: str) -> Dict[str, Optional[str]]:
    """Yeni Goodreads HTML yapısına göre kitap verilerini döndürür."""
    res = requests.get(url, headers=HEADERS, timeout=25)
    res.raise_for_status()
   def _make_soup(html: str) -> BeautifulSoup:
    # Önce lxml, yoksa html5lib, o da yoksa html.parser
    for parser in ("lxml", "html5lib", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    # En kötü senaryo
    return BeautifulSoup(html, "html.parser")
    data = {
        "goodreadsURL": url,
        "Book Id": None,
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
        "Cover URL": None,
        "Average Rating": None,
    }

    # Book Id
    m = ID_RE.search(url)
    if m:
        data["Book Id"] = m.group(1)

    # --- Title ---
    title_el = soup.select_one("h1.Text__title1, h1.BookPageTitleSection__title")
    if title_el:
        data["Title"] = _clean(title_el.get_text())

    # --- Author ---
    author_el = soup.select_one("a.ContributorLink, span[itemprop='author'] [itemprop='name']")
    if author_el:
        data["Author"] = _clean(author_el.get_text())

    # --- Cover URL ---
    cover_el = soup.select_one("img.BookCover__image, img#coverImage")
    if cover_el and cover_el.get("src"):
        data["Cover URL"] = cover_el["src"]

    # --- Average rating ---
    rating_el = soup.select_one("div.RatingStatistics__rating, span.AverageRating")
    if rating_el:
        try:
            data["Average Rating"] = float(rating_el.get_text(strip=True))
        except Exception:
            pass

    # --- JSON-LD fallback (bazı veriler burada) ---
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            js = json.loads(script.string.strip())
        except Exception:
            continue
        if isinstance(js, dict) and js.get("@type") in {"Book", "CreativeWork"}:
            data["Title"] = data["Title"] or js.get("name")
            author = js.get("author")
            if isinstance(author, dict):
                data["Author"] = data["Author"] or author.get("name")
            elif isinstance(author, list) and author:
                data["Author"] = data["Author"] or author[0].get("name")
            data["ISBN"] = data["ISBN"] or js.get("isbn")

    # --- Details bölümü ---
    details_root = soup.select_one("[data-testid='bookDetails']")
    if details_root:
        text = details_root.get_text("\n", strip=True)

        # Number of Pages
        m = PAGE_RE.search(text)
        if m:
            data["Number of Pages"] = m.group(1)

        # Year Published
        pub_match = re.search(r"Published\s+([^\n]+)", text, re.I)
        if pub_match:
            y = YEAR_RE.findall(pub_match.group(1))
            if y:
                data["Year Published"] = y[0]

        # Language
        lang_match = re.search(r"Language\s*([^:\n]*)\n?([^\n]+)", text, re.I)
        if lang_match:
            cand = _clean(lang_match.group(2))
            if cand:
                data["Language"] = cand

        # Publisher
        pub2 = re.search(r"Publisher\s*([^:\n]*)\n?([^\n]+)", text, re.I)
        if pub2:
            val = _clean(pub2.group(2))
            if "Published" not in val[:15]:
                data["Publisher"] = val

        # ISBN / ISBN13
        isbn13_match = re.search(r"ISBN13\s*[:：]?\s*([0-9xX\-]+)", text, re.I)
        if isbn13_match:
            data["ISBN13"] = isbn13_match.group(1).replace("-", "")
        isbn_match = re.search(r"\bISBN\s*[:：]?\s*([0-9xX\-]+)", text, re.I)
        if isbn_match:
            cand = isbn_match.group(1).replace("-", "")
            if len(cand) in (10, 13):
                data["ISBN"] = cand

    # --- Ek fallback: eski stil detaylar ---
    if not data["Publisher"]:
        old_pub = soup.select_one("#bookDataBox .infoBoxRowTitle:contains('Publisher') + .infoBoxRowItem")
        if old_pub:
            data["Publisher"] = _clean(old_pub.get_text())

    if not data["Number of Pages"]:
        old_pages = soup.select_one("#details span[itemprop='numberOfPages']")
        if old_pages:
            data["Number of Pages"] = _clean(old_pages.get_text().split()[0])

    # --- Year Published Fallback ---
    if not data["Year Published"]:
        pub_date = soup.find("div", string=re.compile(r"Published", re.I))
        if pub_date:
            y = YEAR_RE.findall(pub_date.get_text())
            if y:
                data["Year Published"] = y[0]

    return data


if __name__ == "__main__":
    test_url = "https://www.goodreads.com/book/show/13038020-i-bulma-i-darehanesi"
    info = fetch_goodreads(test_url)
    print(json.dumps(info, ensure_ascii=False, indent=2))
