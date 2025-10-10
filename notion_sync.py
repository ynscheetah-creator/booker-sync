# notion_sync.py  —  v2 (placeholder-aware, safe updates, debug logs)
from __future__ import annotations
import os, re, sys, time
from typing import Dict, Any, Optional

from notion_client import Client
from notion_client.helpers import iterate_paginated_api

from goodreads_scraper import scrape_goodreads, BookData

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    print("ERROR: NOTION_TOKEN / NOTION_DATABASE_ID env eksik.")
    sys.exit(1)

notion = Client(auth=NOTION_TOKEN)

# === Ayarlar ===
# Sizin DB kolon adlarınız:
COLS = {
    "url": "goodreadsURL",              # URL
    "book_id": "Book Id",               # number
    "title": "Title",                   # title
    "cover_url": "Cover URL",           # url
    "author": "Author",                 # rich_text
    "add_authors": "Additional Authors",# rich_text
    "publisher": "Publisher",           # rich_text
    "year_published": "Year Published", # number
    "orig_year": "Original Publication Year", # number
    "pages": "Number of Pages",         # number
    "lang": "Language",                 # rich_text
    "isbn": "ISBN",                     # rich_text
    "isbn13": "ISBN13",                 # rich_text
    "rating": "Average Rating",         # number
}

# “Placeholder” gibi gördüğümüz başlık/yazar metinleri
PLACEHOLDERS = {"goodreads", "authors", "author", "good reads"}

def _is_placeholder(s: Optional[str]) -> bool:
    if not s:
        return True
    return s.strip().lower() in PLACEHOLDERS

def _rt_get(prop: Dict[str, Any]) -> str:
    # rich_text veya title alanından düz string oku
    if not prop:
        return ""
    if "rich_text" in prop:
        arr = prop.get("rich_text", [])
    elif "title" in prop:
        arr = prop.get("title", [])
    else:
        return ""
    out = []
    for r in arr:
        t = r.get("plain_text")
        if t:
            out.append(t)
    return " ".join(out).strip()

def _prop_get_url(properties: Dict[str, Any], name: str) -> Optional[str]:
    prop = properties.get(name, {})
    if prop.get("type") == "url":
        return prop.get("url")
    return None

def _prop_get_number(properties: Dict[str, Any], name: str) -> Optional[float]:
    prop = properties.get(name, {})
    if prop.get("type") == "number":
        return prop.get("number")
    return None

def _prop_get_textlike(properties: Dict[str, Any], name: str) -> str:
    prop = properties.get(name, {})
    return _rt_get(prop)

def _truncate(s: Optional[str], limit: int = 1900) -> Optional[str]:
    if not s:
        return None
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[:limit]
    return s

def _build_updates(page: Dict[str, Any], parsed: BookData) -> Dict[str, Any]:
    """Boş/placeholder alanları parsed verilerle doldurur, Update payload döndürür."""
    updates: Dict[str, Any] = {}

    props = page.get("properties", {})

    # --- Title
    current_title = _prop_get_textlike(props, COLS["title"])
    if _is_placeholder(current_title) and parsed.Title:
        updates[COLS["title"]] = {
            "title": [{"type": "text", "text": {"content": parsed.Title}}]
        }

    # --- Author
    current_author = _prop_get_textlike(props, COLS["author"])
    if _is_placeholder(current_author) and parsed.Author:
        updates[COLS["author"]] = {
            "rich_text": [{"type": "text", "text": {"content": parsed.Author}}]
        }

    # --- Additional Authors (eğer geliyorsa)
    if parsed.AdditionalAuthors and not _prop_get_textlike(props, COLS["add_authors"]):
        updates[COLS["add_authors"]] = {
            "rich_text": [{"type": "text", "text": {"content": _truncate(parsed.AdditionalAuthors)}}]
        }

    # --- Publisher (uzun metin güvenliği)
    if parsed.Publisher and not _prop_get_textlike(props, COLS["publisher"]):
        updates[COLS["publisher"]] = {
            "rich_text": [{"type": "text", "text": {"content": _truncate(parsed.Publisher)}}]
        }

    # --- Year Published
    if parsed.YearPublished is not None and _prop_get_number(props, COLS["year_published"]) is None:
        updates[COLS["year_published"]] = {"number": parsed.YearPublished}

    # --- Original Publication Year
    if parsed.OriginalPublicationYear is not None and _prop_get_number(props, COLS["orig_year"]) is None:
        updates[COLS["orig_year"]] = {"number": parsed.OriginalPublicationYear}

    # --- Pages
    if parsed.NumberOfPages is not None and _prop_get_number(props, COLS["pages"]) is None:
        updates[COLS["pages"]] = {"number": parsed.NumberOfPages}

    # --- Language
    if parsed.Language and not _prop_get_textlike(props, COLS["lang"]):
        updates[COLS["lang"]] = {
            "rich_text": [{"type": "text", "text": {"content": _truncate(parsed.Language, 100)}}]
        }

    # --- ISBN & ISBN13
    if parsed.ISBN and not _prop_get_textlike(props, COLS["isbn"]):
        updates[COLS["isbn"]] = {
            "rich_text": [{"type": "text", "text": {"content": parsed.ISBN}}]
        }
    if parsed.ISBN13 and not _prop_get_textlike(props, COLS["isbn13"]):
        updates[COLS["isbn13"]] = {
            "rich_text": [{"type": "text", "text": {"content": parsed.ISBN13}}]
        }

    # --- Rating
    if parsed.AverageRating is not None and _prop_get_number(props, COLS["rating"]) is None:
        updates[COLS["rating"]] = {"number": parsed.AverageRating}

    # --- Cover URL (gözükmesi için)
    current_cover = _prop_get_url(props, COLS["cover_url"])
    if parsed.CoverURL and not current_cover:
        updates[COLS["cover_url"]] = {"url": parsed.CoverURL}

    # --- Book Id
    current_bid = _prop_get_number(props, COLS["book_id"])
    if parsed.BookId is not None and current_bid is None:
        updates[COLS["book_id"]] = {"number": parsed.BookId}

    return updates

def update_page_cover_if_needed(page_id: str, page: Dict[str, Any], parsed: BookData):
    # sayfa kapak resmi: parsed.CoverURL varsa ve mevcut cover yoksa set et
    if not parsed.CoverURL:
        return
    current_cover = page.get("cover")
    if current_cover is None:
        notion.pages.update(page_id=page_id, cover={"type": "external", "external": {"url": parsed.CoverURL}})

def run_once():
    # DB’de goodreadsURL dolu olan tüm sayfaları çek
    # (Filtreyi daha daraltmak istersen: Title = "Goodreads" OR Author boş v.b. ekleyebilirsin)
    print("Querying Notion database…")
    pages = iterate_paginated_api(
        notion.databases.query,
        database_id=DATABASE_ID,
        filter={
            "property": COLS["url"],
            "url": {"is_not_empty": True}
        }
    )

    count = 0
    for page in pages:
        page_id = page["id"]
        props = page.get("properties", {})
        gr_url = _prop_get_url(props, COLS["url"])
        if not gr_url:
            continue

        print(f"\n--- PAGE {page_id} ---")
        print(f"URL: {gr_url}")

        try:
            parsed = scrape_goodreads(gr_url)
        except Exception as e:
            print(f"SCRAPE ERROR: {e}")
            continue

        # Debug log: çekilen veriyi göster
        print("PARSED:", parsed.to_notion_payload_dict())

        updates = _build_updates(page, parsed)

        if updates:
            try:
                notion.pages.update(page_id=page_id, properties=updates)
                print("Updated properties:", list(updates.keys()))
            except Exception as e:
                print("UPDATE ERROR:", e)

        try:
            update_page_cover_if_needed(page_id, page, parsed)
        except Exception as e:
            print("COVER ERROR:", e)

        count += 1
        time.sleep(0.5)  # Goodreads'e nazik davranalım

    print(f"\nDone. Processed {count} pages.")

if __name__ == "__main__":
    run_once()
