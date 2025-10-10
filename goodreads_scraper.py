# goodreads_scraper.py
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _make_soup(html: str) -> BeautifulSoup:
    """
    Robust soup maker: lxml -> html5lib -> html.parser
    """
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
    Dönen dict alanları:
      Title, Author, Additional Authors, Publisher, Year Published,
      Original Publication Year, Number of Pages, Language, ISBN,
      ISBN13, Average Rating, Cover URL, Book Id, goodreadsURL
    """
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    soup = _make_soup(res.text)

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

    # ---- Title
    h1 = soup.select_one("h1[data-testid='bookTitle']")
    if not h1:
        h1 = soup.select_one("h1#bookTitle, h1.BookPageTitleSection__title")
    data["Title"] = _text(h1)

    # ---- Cover URL
    cover = soup.select_one("img.BookCover__image, img#coverImage")
    if cover and cover.get("src"):
        data["Cover URL"] = cover["src"]

    # ---- Author(s)
    author_main = soup.select_one(
        "[data-testid='name'] a, a.authorName__container, a.authorName span[itemprop='name']"
    )
    data["Author"] = _text(author_main)

    more_authors = soup.select(
        "[data-testid='contributorName'] a, a.contributorName__container"
    )
    if more_authors:
        names = [a.get_text(strip=True) for a in more_authors if _text(a)]
        if data["Author"] in names and data["Author"]:
            names = [n for n in names if n != data["Author"]]
        data["Additional Authors"] = ", ".join(names) if names else None

    # ---- Average rating
    rating = soup.select_one(
        "[data-testid='rating'] [aria-label*='/'], span[itemprop='ratingValue']"
    )
    data["Average Rating"] = _text(rating)

    # ---- Book Id
    m = re.search(r"/book/show/(\d+)", url)
    if m:
        data["Book Id"] = m.group(1)

    # ---- Details block (yayınevi, yıl, sayfa, dil, ISBN...)
    details_block = soup.select_one("[data-testid='bookDetails']")
    if not details_block:
        details_block = soup.select_one("#bookDataBox, .BookDetails")

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

    # Yayın bilgisi satırı
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
        else:
            m = re.search(
                r"(?:Yayınları|Yayınevi|Press|Publishing|Publisher)\s*:\s*(.+)$",
                pub_line,
                re.I,
            )
            if m:
                data["Publisher"] = m.group(1).strip()

    # Orijinal yayın yılı
    m = re.search(r"First published\s+.*?(\d{4})", details_text, re.I)
    if m:
        data["Original Publication Year"] = m.group(1)

    return data
