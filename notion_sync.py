# notion_sync.py
import os
from typing import Dict, Any, Optional
from notion_client import Client
from utils import get_env, as_title, as_rich, as_url, as_number, truncate
from goodreads_scraper import fetch_goodreads
import re

NOTION_TOKEN = get_env("NOTION_TOKEN")
DATABASE_ID = get_env("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError(
        "❌ NOTION_TOKEN ve/veya NOTION_DATABASE_ID environment değişkenleri eksik!\n"
        "   .env dosyasını oluşturup içine şunları ekleyin:\n"
        "   NOTION_TOKEN=your_token\n"
        "   NOTION_DATABASE_ID=your_db_id"
    )

notion = Client(auth=NOTION_TOKEN)

# Notion sütun adları
COLS = [
    "goodreadsURL",
    "Book Id",
    "Title",
    "Cover URL",
    "Author",
    "Additional Authors",
    "Publisher",
    "Year Published",
    "Original Publication Year",
    "Number of Pages",
    "Language",
    "Spoiler",
    "ISBN",
    "ISBN13",
    "Average Rating",
]


def _get_prop_value(p: Dict[str, Any]) -> Optional[str]:
    """Mevcut sayfadaki property'yi string olarak çek (kontrol için)."""
    if p is None or p.get("type") is None:
        return None
    t = p["type"]
    try:
        if t == "title":
            arr = p["title"]
            return "".join([x["plain_text"] for x in arr]) if arr else None
        if t == "rich_text":
            arr = p["rich_text"]
            return "".join([x["plain_text"] for x in arr]) if arr else None
        if t == "url":
            return p["url"]
        if t == "number":
            return str(p["number"]) if p["number"] is not None else None
    except Exception:
        return None
    return None


def _build_updates(scraped: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Scraper'dan gelen veriyi Notion update body'sine çevir."""
    body: Dict[str, Any] = {}

    # Title
    if scraped.get("Title"):
        body["Title"] = as_title(scraped["Title"])

    # URL'ler
    if scraped.get("goodreadsURL"):
        body["goodreadsURL"] = as_url(scraped["goodreadsURL"])
    if scraped.get("Cover URL"):
        body["Cover URL"] = as_url(scraped["Cover URL"])

    # Number (Book Id, Yıllar, Sayfa)
    if scraped.get("Book Id"):
        body["Book Id"] = as_number(scraped["Book Id"])
    if scraped.get("Year Published"):
        body["Year Published"] = as_number(scraped["Year Published"])
    if scraped.get("Original Publication Year"):
        body["Original Publication Year"] = as_number(
            scraped["Original Publication Year"]
        )
    if scraped.get("Number of Pages"):
        body["Number of Pages"] = as_number(scraped["Number of Pages"])
    if scraped.get("Average Rating"):
        body["Average Rating"] = as_number(scraped["Average Rating"])

    # Metinler
    for key in [
        "Author",
        "Additional Authors",
        "Publisher",
        "Language",
        "ISBN",
        "ISBN13",
    ]:
        val = scraped.get(key)
        if val:
            body[key] = as_rich(val)

    return {k: v for k, v in body.items() if v is not None}


def _set_page_cover(page_id: str, cover_url: Optional[str]):
    """Sayfa kapağını ayarla."""
    if not cover_url:
        return
    try:
        notion.pages.update(
            page_id=page_id,
            cover={"type": "external", "external": {"url": cover_url}},
        )
        print("  📸 Cover updated")
    except Exception as e:
        print(f"  ⚠️  Cover update failed: {e}")


def run_once():
    """Notion database'deki tüm sayfaları tara ve Goodreads linklerini işle."""
    print("🚀 Starting Goodreads → Notion sync...\n")

    # Notion'dan sayfaları çek
    results = []
    start_cursor = None
    while True:
        resp = notion.databases.query(
            **{
                "database_id": DATABASE_ID,
                "page_size": 100,
                **({"start_cursor": start_cursor} if start_cursor else {}),
            }
        )
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        start_cursor = resp.get("next_cursor")

    print(f"📚 Found {len(results)} pages in Notion database\n")

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for idx, page in enumerate(results, 1):
        page_id = page["id"]
        props = page.get("properties", {})

        gr_url = _get_prop_value(props.get("goodreadsURL")) or ""

        # Goodreads URL yoksa atla
        if "goodreads.com/book" not in (gr_url or ""):
            skipped_count += 1
            continue

        print(f"[{idx}/{len(results)}] 📖 Processing: {gr_url}")

        try:
            scraped = fetch_goodreads(gr_url)
        except Exception as e:
            print(f"  ❌ Fetch error: {e}\n")
            error_count += 1
            continue

        updates = _build_updates(scraped)

        # Güncellenecek bir şey var mı?
        if not updates:
            print("  ℹ️  No updates needed\n")
            skipped_count += 1
            continue

        try:
            notion.pages.update(page_id=page_id, properties=updates)
            print("  ✅ Properties updated")

            # Cover'ı sayfa kapağı yap
            _set_page_cover(page_id, scraped.get("Cover URL"))
            updated_count += 1
            print()
        except Exception as e:
            print(f"  ❌ Notion update error: {e}\n")
            error_count += 1
            continue

    print("=" * 50)
    print(f"✅ Sync completed!")
    print(f"   Updated: {updated_count}")
    print(f"   Skipped: {skipped_count}")
    print(f"   Errors: {error_count}")
    print("=" * 50)
