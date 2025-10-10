# notion_sync.py
import os
from typing import Dict, Any, Optional, Tuple
from notion_client import Client
from utils import (
    get_env, as_title, as_rich, as_url, as_number, as_multi_select, truncate
)
from google_books_api import fetch_from_google_books
from openlibrary_api import fetch_from_openlibrary
import re
from datetime import datetime, timezone, timedelta

NOTION_TOKEN = get_env("NOTION_TOKEN")
DATABASE_ID = get_env("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError(
        "❌ NOTION_TOKEN ve/veya NOTION_DATABASE_ID environment değişkenleri eksik!"
    )

notion = Client(auth=NOTION_TOKEN)

RECENT_EDIT_HOURS = int(os.environ.get("RECENT_EDIT_HOURS", "24"))


def _get_prop_value(p: Dict[str, Any]) -> Optional[str]:
    """Mevcut sayfadaki property'yi string olarak çek"""
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
        if t == "multi_select":
            arr = p["multi_select"]
            return ", ".join([x["name"] for x in arr]) if arr else None
    except Exception:
        return None
    return None


def _extract_book_id_from_url(url: str) -> Optional[str]:
    """Goodreads URL'sinden Book ID çıkar"""
    m = re.search(r"/book/show/(\d+)", url)
    return m.group(1) if m else None


def _was_recently_edited(page: Dict[str, Any], hours: int = 24) -> bool:
    """Sayfa son X saat içinde düzenlendi mi?"""
    try:
        last_edited = page.get("last_edited_time")
        if not last_edited:
            return False
        
        edited_time = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        time_diff = now - edited_time
        
        return time_diff < timedelta(hours=hours)
    except Exception:
        return False


def _build_updates(
    scraped: Dict[str, Optional[str]], 
    existing_props: Dict[str, Any],
    force_update: bool = False
) -> Dict[str, Any]:
    """
    API'den gelen veriyi Notion update body'sine çevir.
    force_update=True ise tüm alanları güncelle (ISBN değişirse)
    force_update=False ise sadece boş alanları doldur
    """
    body: Dict[str, Any] = {}

    if force_update:
        # FORCE UPDATE: Her şeyi üzerine yaz
        if scraped.get("Title"):
            body["Title"] = as_title(scraped["Title"])
        
        if scraped.get("goodreadsURL"):
            body["goodreadsURL"] = as_url(scraped["goodreadsURL"])
        
        if scraped.get("Cover URL"):
            body["Cover URL"] = as_url(scraped["Cover URL"])
        
        if scraped.get("Book Id"):
            body["Book Id"] = as_number(scraped["Book Id"])
        
        if scraped.get("Year Published"):
            body["Year Published"] = as_number(scraped["Year Published"])
        
        if scraped.get("Original Publication Year"):
            body["Original Publication Year"] = as_number(scraped["Original Publication Year"])
        
        if scraped.get("Number of Pages"):
            body["Number of Pages"] = as_number(scraped["Number of Pages"])
        
        if scraped.get("Average Rating"):
            body["Average Rating"] = as_number(scraped["Average Rating"])
        
        # Multi-select alanlar
        if scraped.get("Author"):
            body["Author"] = as_multi_select(scraped["Author"])
        
        if scraped.get("Translator"):
            body["Translator"] = as_multi_select(scraped["Translator"])
        
        # ISBN (tek kolon)
        if scraped.get("ISBN13") or scraped.get("ISBN"):
            isbn_value = scraped.get("ISBN13") or scraped.get("ISBN")
            body["ISBN"] = as_rich(isbn_value)
        
        # Text alanlar
        for key in ["Publisher", "Language", "Description"]:
            val = scraped.get(key)
            if val:
                body[key] = as_rich(val)
    
    else:
        # NORMAL UPDATE: Sadece boş alanları doldur
        existing_title = _get_prop_value(existing_props.get("Title"))
        if scraped.get("Title") and not existing_title:
            body["Title"] = as_title(scraped["Title"])

        existing_gr_url = _get_prop_value(existing_props.get("goodreadsURL"))
        if scraped.get("goodreadsURL") and not existing_gr_url:
            body["goodreadsURL"] = as_url(scraped["goodreadsURL"])
        
        existing_cover = _get_prop_value(existing_props.get("Cover URL"))
        if scraped.get("Cover URL") and not existing_cover:
            body["Cover URL"] = as_url(scraped["Cover URL"])

        if scraped.get("Book Id"):
            existing_book_id = _get_prop_value(existing_props.get("Book Id"))
            if not existing_book_id:
                body["Book Id"] = as_number(scraped["Book Id"])
        
        if scraped.get("Year Published"):
            existing_year = _get_prop_value(existing_props.get("Year Published"))
            if not existing_year:
                body["Year Published"] = as_number(scraped["Year Published"])
        
        if scraped.get("Original Publication Year"):
            existing_orig_year = _get_prop_value(existing_props.get("Original Publication Year"))
            if not existing_orig_year:
                body["Original Publication Year"] = as_number(scraped["Original Publication Year"])
        
        if scraped.get("Number of Pages"):
            existing_pages = _get_prop_value(existing_props.get("Number of Pages"))
            if not existing_pages:
                body["Number of Pages"] = as_number(scraped["Number of Pages"])
        
        if scraped.get("Average Rating"):
            existing_rating = _get_prop_value(existing_props.get("Average Rating"))
            if not existing_rating:
                body["Average Rating"] = as_number(scraped["Average Rating"])

        # Multi-select alanlar (sadece boş ise)
        existing_author = _get_prop_value(existing_props.get("Author"))
        if scraped.get("Author") and not existing_author:
            body["Author"] = as_multi_select(scraped["Author"])
        
        existing_translator = _get_prop_value(existing_props.get("Translator"))
        if scraped.get("Translator") and not existing_translator:
            body["Translator"] = as_multi_select(scraped["Translator"])
        
        # ISBN (sadece boş ise)
        existing_isbn = _get_prop_value(existing_props.get("ISBN"))
        if not existing_isbn:
            isbn_value = scraped.get("ISBN13") or scraped.get("ISBN")
            if isbn_value:
                body["ISBN"] = as_rich(isbn_value)
        
        # Text alanlar (sadece boş ise)
        for key in ["Publisher", "Language", "Description"]:
            existing_value = _get_prop_value(existing_props.get(key))
            scraped_value = scraped.get(key)
            
            if scraped_value and not existing_value:
                body[key] = as_rich(scraped_value)

    return {k: v for k, v in body.items() if v is not None}


def _set_page_cover(page_id: str, cover_url: Optional[str], force: bool = False):
    """Sayfa kapağını ayarla"""
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


def _needs_update(props: Dict[str, Any]) -> Tuple[bool, str]:
    """Bu sayfa güncellenmeye ihtiyaç duyuyor mu?"""
    title = _get_prop_value(props.get("Title"))
    author = _get_prop_value(props.get("Author"))
    isbn = _get_prop_value(props.get("ISBN"))
    cover = _get_prop_value(props.get("Cover URL"))
    publisher = _get_prop_value(props.get("Publisher"))
    pages = _get_prop_value(props.get("Number of Pages"))
    year = _get_prop_value(props.get("Year Published"))
    
    if not any([title, isbn]):
        return False, "No basic info"
    
    if title:
        missing_fields = []
        if not author:
            missing_fields.append("Author")
        if not cover:
            missing_fields.append("Cover")
        if not publisher:
            missing_fields.append("Publisher")
        if not pages:
            missing_fields.append("Pages")
        if not year:
            missing_fields.append("Year")
        
        if missing_fields:
            return True, f"Missing: {', '.join(missing_fields)}"
        else:
            return False, "Complete"
    
    if not title and isbn:
        return True, "Has ISBN but no Title"
    
    return False, "Unknown"


def fetch_book_data(
    title: str = None,
    author: str = None,
    isbn: str = None,
    goodreads_url: str = None
) -> Dict[str, Optional[str]]:
    """API'lerden kitap verisi çek"""
    data = {}
    
    if goodreads_url:
        book_id = _extract_book_id_from_url(goodreads_url)
        if book_id:
            data["Book Id"] = book_id
            data["goodreadsURL"] = goodreads_url
    
    if isbn:
        print(f"  🔍 Searching by ISBN: {isbn}")
        
        google_data = fetch_from_google_books(isbn=isbn)
        if google_data and google_data.get("Title"):
            print(f"  ✅ Found in Google Books (ISBN): {google_data['Title']}")
            data.update({k: v for k, v in google_data.items() if v})
            return data
        
        ol_data = fetch_from_openlibrary(isbn=isbn)
        if ol_data and ol_data.get("Title"):
            print(f"  ✅ Found in OpenLibrary (ISBN): {ol_data['Title']}")
            data.update({k: v for k, v in ol_data.items() if v})
            return data
    
    if title:
        print(f"  🔍 Searching by Title: {title[:50]}...")
        
        google_data = fetch_from_google_books(title=title, author=author)
        if google_data and google_data.get("Title"):
            print(f"  ✅ Found in Google Books: {google_data['Title']}")
            data.update({k: v for k, v in google_data.items() if v})
            return data
        
        ol_data = fetch_from_openlibrary(title=title, author=author)
        if ol_data and ol_data.get("Title"):
            print(f"  ✅ Found in OpenLibrary: {ol_data['Title']}")
            data.update({k: v for k, v in ol_data.items() if v})
            return data
    
    print("  ⚠️  No data found from any API")
    return data


def run_once():
    """Notion database'deki eksik bilgileri tamamla"""
    print("🚀 Starting Smart Sync...\n")
    print("📖 Using Google Books + OpenLibrary APIs")
    print(f"🔄 Pages edited in last {RECENT_EDIT_HOURS}h will be FULLY updated")
    print("💡 Other pages: only fill missing fields\n")

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
    force_updated_count = 0
    skipped_count = 0
    error_count = 0
    complete_count = 0

    for idx, page in enumerate(results, 1):
        page_id = page["id"]
        props = page.get("properties", {})

        recently_edited = _was_recently_edited(page, RECENT_EDIT_HOURS)
        needs_update, reason = _needs_update(props)
        
        if not recently_edited and not needs_update:
            if reason == "Complete":
                complete_count += 1
            else:
                skipped_count += 1
            continue

        existing_title = _get_prop_value(props.get("Title"))
        existing_author = _get_prop_value(props.get("Author"))
        existing_isbn = _get_prop_value(props.get("ISBN"))
        gr_url = _get_prop_value(props.get("goodreadsURL")) or ""

        display_name = existing_title or existing_isbn or gr_url
        print(f"[{idx}/{len(results)}] 📖 {display_name[:60]}")
        
        if recently_edited:
            print(f"  🔄 Recently edited → FULL UPDATE")
        else:
            print(f"  ℹ️  Reason: {reason}")

        try:
            scraped = fetch_book_data(
                title=existing_title,
                author=existing_author,
                isbn=existing_isbn,
                goodreads_url=gr_url if gr_url else None
            )
        except Exception as e:
            print(f"  ❌ Fetch error: {e}\n")
            error_count += 1
            continue

        updates = _build_updates(scraped, props, force_update=recently_edited)

        if not updates:
            print("  ℹ️  No new data to add\n")
            skipped_count += 1
            continue

        try:
            notion.pages.update(page_id=page_id, properties=updates)
            updated_fields = list(updates.keys())
            print(f"  ✅ Updated {len(updated_fields)} fields: {', '.join(updated_fields[:5])}")

            if recently_edited:
                _set_page_cover(page_id, scraped.get("Cover URL"), force=True)
                force_updated_count += 1
            else:
                existing_cover = _get_prop_value(props.get("Cover URL"))
                if not existing_cover and scraped.get("Cover URL"):
                    _set_page_cover(page_id, scraped.get("Cover URL"))
            
            updated_count += 1
            print()
        except Exception as e:
            print(f"  ❌ Notion update error: {e}\n")
            error_count += 1
            continue

    print("=" * 60)
    print(f"✅ Smart Sync completed!")
    print(f"   Updated: {updated_count} (Force: {force_updated_count})")
    print(f"   Complete (skipped): {complete_count}")
    print(f"   Skipped (no info): {skipped_count}")
    print(f"   Errors: {error_count}")
    print("=" * 60)
