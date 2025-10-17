# notion_sync.py
import os
from typing import Dict, Any, Optional
from notion_client import Client
from utils import (
    get_env, as_title, as_rich, as_url, as_number, as_multi_select
)
from google_books_api import fetch_from_google_books
from openlibrary_api import fetch_from_openlibrary
from goodreads_scraper import fetch_goodreads
from datetime import datetime, timezone, timedelta
import logging

# --- CONSTANTS ---
NOTION_TOKEN = get_env("NOTION_TOKEN")
DATABASE_ID = get_env("NOTION_DATABASE_ID")
NEW_ENTRY_HOURS = int(get_env("NEW_ENTRY_HOURS", "24"))
SCAN_LIMIT = get_env("SCAN_LIMIT")

# --- INITIALIZATION ---
if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError("❌ NOTION_TOKEN ve NOTION_DATABASE_ID ortam değişkenleri ayarlanmalı!")
notion = Client(auth=NOTION_TOKEN)

# --- HELPER FUNCTIONS ---
def _get_prop_value(p: Dict[str, Any]) -> Optional[str]:
    if p is None: return None
    t = p.get("type")
    try:
        if t == "title":
            arr = p.get("title", [])
            return "".join([x.get("plain_text", "") for x in arr]) if arr else None
        if t == "rich_text":
            arr = p.get("rich_text", [])
            return "".join([x.get("plain_text", "") for x in arr]) if arr else None
        if t == "url": return p.get("url")
        if t == "number": return str(p.get("number")) if p.get("number") is not None else None
        if t == "multi_select":
            arr = p.get("multi_select", [])
            return ", ".join([x.get("name", "") for x in arr]) if arr else None
        if t == "checkbox": # Checkbox değerini okumak için
            return p.get("checkbox", False)
    except (KeyError, IndexError):
        return None
    return None

def _was_recently_created(page: Dict[str, Any]) -> bool:
    try:
        created_time_str = page.get("created_time")
        if not created_time_str: return False
        created_time = datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - created_time) < timedelta(hours=NEW_ENTRY_HOURS)
    except Exception:
        return False

def _merge_book_data(*sources: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    merged = {}
    for source in sources:
        if not source: continue
        for key, value in source.items():
            if key not in merged and value:
                merged[key] = value
    return merged

# --- CORE DATA FETCHING ---
def fetch_book_data_pipeline(
    title: Optional[str], author: Optional[str], isbn: Optional[str], goodreads_url: Optional[str]
) -> Dict[str, Optional[str]]:
    goodreads_data, api_data = {}, {}
    if goodreads_url:
        try:
            goodreads_data = fetch_goodreads(goodreads_url)
        except Exception as e:
            logging.warning(f"  ⚠️ Goodreads scraper hatası: {e}")
    search_title = goodreads_data.get("Title") or title
    search_author = goodreads_data.get("Author") or author
    search_isbn = goodreads_data.get("ISBN13") or goodreads_data.get("ISBN") or isbn
    try:
        if search_isbn:
            api_data = fetch_from_google_books(isbn=search_isbn) or fetch_from_openlibrary(isbn=search_isbn)
        elif search_title:
            api_data = fetch_from_google_books(title=search_title, author=search_author) or fetch_from_openlibrary(title=search_title, author=search_author)
    except Exception as e:
        logging.warning(f"  ⚠️ API arama hatası: {e}")
    final_data = _merge_book_data(goodreads_data, api_data)
    if not final_data:
        logging.warning("  ⚠️ Hiçbir kaynaktan veri bulunamadı.")
    return final_data

# --- NOTION UPDATE LOGIC ---
def _build_updates(
    scraped: Dict[str, Optional[str]]
) -> Dict[str, Any]:
    updates = {}
    prop_map = {
        "Title": ("Title", as_title), "Author": ("Author", as_multi_select),
        "Translator": ("Translator", as_multi_select), "goodreadsURL": ("goodreadsURL", as_url),
        "Cover URL": ("Cover URL", as_url), "Publisher": ("Publisher", as_rich),
        "Year Published": ("Year Published", as_number), "Original Publication Year": ("Original Publication Year", as_number),
        "Number of Pages": ("Number of Pages", as_number), "Description": ("Description", as_rich),
        "Language": ("Language", as_rich),
    }
    for prop_name, (scraped_key, formatter) in prop_map.items():
        scraped_val = scraped.get(scraped_key)
        if scraped_val:
            formatted_value = formatter(scraped_val)
            if formatted_value:
                updates[prop_name] = formatted_value
    
    isbn_val = scraped.get("ISBN13") or scraped.get("ISBN")
    if isbn_val:
        updates["ISBN"] = as_rich(isbn_val)
    return updates

def _update_page_cover(page_id: str, cover_url: Optional[str]):
    if not cover_url: return
    try:
        notion.pages.update(page_id=page_id, cover={"type": "external", "external": {"url": cover_url}})
        logging.info("  📸 Kapak fotoğrafı güncellendi.")
    except Exception as e:
        logging.warning(f"  ⚠️ Kapak güncellenemedi: {e}")

# --- MAIN RUNNER ---
def run_once():
    """Notion'daki sadece YENİ veya 'Refresh Data' İŞARETLİ kayıtları işler."""
    logging.info("🚀 Akıllı Senkronizasyon Başlatılıyor...")
    # FİLTRE: Sadece yeni veya işaretli olanları Notion'dan çek
    db_filter = {
        "or": [
            {
                "timestamp": "created_time",
                "created_time": {
                    "past_hours": NEW_ENTRY_HOURS
                }
            },
            {
                "property": "Refresh Data", # Değişiklik
                "checkbox": {
                    "equals": True
                }
            }
        ]
    }

    sorts = [{"timestamp": "created_time", "direction": "descending"}]
    limit = int(SCAN_LIMIT) if SCAN_LIMIT and SCAN_LIMIT.isdigit() else None
    
    all_pages = []
    start_cursor = None
    while True:
        if limit and len(all_pages) >= limit: break
        page_size = 100
        if limit:
            remaining = limit - len(all_pages)
            if remaining < 100: page_size = remaining
        try:
            response = notion.databases.query(
                database_id=DATABASE_ID,
                filter=db_filter,
                sorts=sorts,
                start_cursor=start_cursor,
                page_size=page_size
            )
            results = response.get("results", [])
            all_pages.extend(results)
            if not response.get("has_more") or not results: break
            start_cursor = response.get("next_cursor")
        except Exception as e:
            logging.error(f"❌ Notion veritabanı okunurken hata oluştu: {e}")
            return

    if not all_pages:
        logging.info("✅ İşlem yapılacak yeni veya işaretlenmiş bir kayıt bulunamadı. Senkronizasyon tamamlandı.")
        return

    logging.info(f"📚 İşlem yapılacak {len(all_pages)} kayıt bulundu.\n")

    for idx, page in enumerate(all_pages, 1):
        props = page.get("properties", {})
        page_id = page["id"]
        
        is_new = _was_recently_created(page)
        is_refresh_data = _get_prop_value(props.get("Refresh Data")) # Değişiklik

        title = _get_prop_value(props.get("Title"))
        gr_url = _get_prop_value(props.get("goodreadsURL"))
        display_name = title or gr_url or page_id
        
        logging.info(f"--- [{idx}/{len(all_pages)}] 📖: {display_name[:70]} ---")
        if is_new:
            logging.info("  ➡️ Yeni kayıt bulundu, tüm veriler çekilecek.")
        elif is_refresh_data:
            logging.info("  ➡️ 'Refresh Data' işaretli, tüm veriler yeniden çekilecek.") # Değişiklik

        scraped_data = fetch_book_data_pipeline(
            title=title,
            author=_get_prop_value(props.get("Author")),
            isbn=_get_prop_value(props.get("ISBN")),
            goodreads_url=gr_url,
        )

        if not scraped_data or not scraped_data.get("Title"):
            logging.warning("  -> Veri bulunamadı veya başlık çekilemedi, atlanıyor.\n")
            continue

        updates = _build_updates(scraped_data)

        if not updates:
            logging.info("  -> Eklenecek yeni bilgi yok.\n")
            continue
        
        try:
            notion.pages.update(page_id=page_id, properties=updates)
            logging.info(f"  ✅ Notion güncellendi: {', '.join(updates.keys())}")
            _update_page_cover(page_id, scraped_data.get("Cover URL"))
            
            # Başarılı güncellemeden sonra checkbox'ı temizle
            if is_refresh_data:
                notion.pages.update(page_id=page_id, properties={"Refresh Data": {"checkbox": False}}) # Değişiklik
                logging.info("  ✔️ 'Refresh Data' işareti kaldırıldı.") # Değişiklik
            print()
        except Exception as e:
            logging.error(f"  ❌ Notion güncelleme hatası: {e}\n")
    
    logging.info("=" * 50)
    logging.info("✅ Akıllı Senkronizasyon Tamamlandı!")
    logging.info(f"   İşlem Yapılan Sayfa Sayısı: {len(all_pages)}")
    logging.info("=" * 50)
