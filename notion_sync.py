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
import re
from datetime import datetime, timezone, timedelta
import logging

# --- CONSTANTS ---
NOTION_TOKEN = get_env("NOTION_TOKEN")
DATABASE_ID = get_env("NOTION_DATABASE_ID")
RECENT_EDIT_HOURS = int(get_env("RECENT_EDIT_HOURS", "24"))
# YENİ: Taranacak maksimum sayfa sayısı (isteğe bağlı)
SCAN_LIMIT = get_env("SCAN_LIMIT")

# --- INITIALIZATION ---
if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError("❌ NOTION_TOKEN ve NOTION_DATABASE_ID ortam değişkenleri ayarlanmalı!")
notion = Client(auth=NOTION_TOKEN)

# --- HELPER FUNCTIONS ---
def _get_prop_value(p: Dict[str, Any]) -> Optional[str]:
    """Mevcut sayfadaki property'yi string olarak çek."""
    if p is None: return None
    t = p.get("type")
    try:
        if t == "title":
            arr = p.get("title", [])
            return "".join([x.get("plain_text", "") for x in arr]) if arr else None
        if t == "rich_text":
            arr = p.get("rich_text", [])
            return "".join([x.get("plain_text", "") for x in arr]) if arr else None
        if t == "url":
            return p.get("url")
        if t == "number":
            return str(p.get("number")) if p.get("number") is not None else None
        if t == "multi_select":
            arr = p.get("multi_select", [])
            return ", ".join([x.get("name", "") for x in arr]) if arr else None
    except (KeyError, IndexError):
        return None
    return None

def _was_recently_edited(page: Dict[str, Any]) -> bool:
    """Sayfa son X saat içinde düzenlendi mi?"""
    try:
        last_edited = page.get("last_edited_time")
        if not last_edited: return False
        edited_time = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - edited_time) < timedelta(hours=RECENT_EDIT_HOURS)
    except Exception:
        return False

def _needs_update(props: Dict[str, Any]) -> bool:
    """Bu sayfa güncellenmeye ihtiyaç duyuyor mu?"""
    required_fields = ["Author", "Cover URL", "Number of Pages", "Year Published", "Publisher"]
    return any(not _get_prop_value(props.get(field)) for field in required_fields)

def _merge_book_data(*sources: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    """Veri kaynaklarını öncelik sırasına göre akıllıca birleştirir."""
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
    """Veri çekme akışını yönetir: Goodreads -> API'ler."""
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
    scraped: Dict[str, Optional[str]], existing_props: Dict[str, Any], force: bool
) -> Dict[str, Any]:
    """Notion güncelleme gövdesini oluşturur."""
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
        existing_val = _get_prop_value(existing_props.get(prop_name))
        scraped_val = scraped.get(scraped_key)
        if scraped_val and (force or not existing_val):
            formatted_value = formatter(scraped_val)
            if formatted_value:
                updates[prop_name] = formatted_value
    
    existing_isbn = _get_prop_value(existing_props.get("ISBN"))
    isbn_val = scraped.get("ISBN13") or scraped.get("ISBN")
    if isbn_val and (force or not existing_isbn):
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
    """Notion veritabanını tarar ve eksik bilgileri tamamlar."""
    logging.info("🚀 Akıllı Senkronizasyon Başlatılıyor...")

    # YENİ: Notion'a her zaman en son eklenenden başlamasını söyle
    sorts = [{"timestamp": "created_time", "direction": "descending"}]
    limit = int(SCAN_LIMIT) if SCAN_LIMIT and SCAN_LIMIT.isdigit() else None

    if limit and limit > 0:
        logging.info(f"🔄 Sadece en son eklenen {limit} sayfa taranacak.")
    else:
        logging.info("🔄 Veritabanındaki tüm sayfalar taranacak (en yeniden eskiye).")

    all_pages = []
    start_cursor = None
    
    while True:
        # Limite ulaştıysak döngüyü kır
        if limit and len(all_pages) >= limit:
            break

        # Bir sonraki istek için sayfa boyutunu ayarla
        page_size = 100
        if limit:
            remaining = limit - len(all_pages)
            if remaining < 100:
                page_size = remaining

        try:
            response = notion.databases.query(
                database_id=DATABASE_ID,
                sorts=sorts,
                start_cursor=start_cursor,
                page_size=page_size
            )
            results = response.get("results", [])
            all_pages.extend(results)

            if not response.get("has_more") or not results:
                break # Çekilecek sayfa kalmadı

            start_cursor = response.get("next_cursor")
        except Exception as e:
            logging.error(f"❌ Notion veritabanı okunurken hata oluştu: {e}")
            return

    logging.info(f"📚 Notion'dan {len(all_pages)} sayfa tarandı.\n")

    for idx, page in enumerate(all_pages, 1):
        props = page.get("properties", {})
        page_id = page["id"]
        
        force_update = _was_recently_edited(page)
        needs_update = _needs_update(props)

        if not force_update and not needs_update:
            continue

        title = _get_prop_value(props.get("Title"))
        gr_url = _get_prop_value(props.get("goodreadsURL"))
        display_name = title or gr_url or page_id
        
        logging.info(f"--- [{idx}/{len(all_pages)}] 📖: {display_name[:70]} ---")
        if force_update:
            logging.info("  🔄 Yakın zamanda düzenlendi, tam güncelleme yapılacak.")
        else:
            logging.info("  ℹ️ Eksik alanlar var, doldurulacak.")

        scraped_data = fetch_book_data_pipeline(
            title=title,
            author=_get_prop_value(props.get("Author")),
            isbn=_get_prop_value(props.get("ISBN")),
            goodreads_url=gr_url,
        )

        if not scraped_data:
            logging.warning("  -> Veri bulunamadı, atlanıyor.\n")
            continue

        if not scraped_data.get("Title") and not title:
            logging.warning("  -> Başlık bulunamadığı için bu sayfa atlanıyor.\n")
            continue

        updates = _build_updates(scraped_data, props, force=force_update)

        if not updates:
            logging.info("  -> Eklenecek yeni bilgi yok.\n")
            continue
            
        if "Title" not in updates:
            existing_title_prop = props.get("Title")
            if existing_title_prop:
                updates["Title"] = existing_title_prop

        try:
            notion.pages.update(page_id=page_id, properties=updates)
            logging.info(f"  ✅ Notion güncellendi: {', '.join(updates.keys())}")

            existing_cover = page.get("cover")
            if scraped_data.get("Cover URL") and (force_update or not existing_cover):
                _update_page_cover(page_id, scraped_data.get("Cover URL"))
            
            print()
        except Exception as e:
            logging.error(f"  ❌ Notion güncelleme hatası: {e}\n")
    
    logging.info("=" * 50)
    logging.info("✅ Akıllı Senkronizasyon Tamamlandı!")
    logging.info("=" * 50)
