# notion_sync.py - ISBN Takip Çözümü
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
RECENT_EDIT_HOURS = int(get_env("RECENT_EDIT_HOURS", "24"))
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
    except (KeyError, IndexError):
        return None
    return None

def _was_recently_created(page: Dict[str, Any]) -> bool:
    """Sayfa son X saat içinde oluşturuldu mu?"""
    try:
        created_time_str = page.get("created_time")
        if not created_time_str: return False
        created_time = datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - created_time) < timedelta(hours=NEW_ENTRY_HOURS)
    except Exception:
        return False

def _was_recently_edited(page: Dict[str, Any]) -> bool:
    try:
        last_edited = page.get("last_edited_time")
        if not last_edited: return False
        edited_time = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - edited_time) < timedelta(hours=RECENT_EDIT_HOURS)
    except Exception:
        return False

def _isbn_changed(props: Dict[str, Any]) -> bool:
    """
    ISBN değişmiş mi kontrol eder.
    Mevcut ISBN ile son işlenen ISBN'i karşılaştırır.
    """
    current_isbn = _get_prop_value(props.get("ISBN"))
    last_processed_isbn = _get_prop_value(props.get("Last Processed ISBN"))
    
    # ISBN yoksa işleme
    if not current_isbn:
        return False
    
    # İlk kez işleniyorsa veya ISBN değişmişse
    return last_processed_isbn != current_isbn

def _needs_enrichment(props: Dict[str, Any]) -> bool:
    """
    Zenginleştirme gerekli mi kontrol eder.
    Sadece yeni kayıtlar için (temel alanlar var, zenginleştirme alanları boş).
    """
    # Temel alanlardan en az biri var mı?
    has_isbn = bool(_get_prop_value(props.get("ISBN")))
    has_title = bool(_get_prop_value(props.get("Title")))
    has_goodreads = bool(_get_prop_value(props.get("goodreadsURL")))
    
    if not (has_isbn or has_goodreads or has_title):
        return False
    
    # Zenginleştirme alanları kontrolü
    enrichment_fields = [
        "Cover URL", "Description", "Publisher", 
        "Number of Pages", "Year Published", "Author"
    ]
    
    empty_count = sum(
        1 for field in enrichment_fields 
        if not _get_prop_value(props.get(field))
    )
    
    # En az 4/6 zenginleştirme alanı boşsa, zenginleştirme gerekli
    return empty_count >= 4

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
def _build_updates(scraped: Dict[str, Optional[str]], current_isbn: Optional[str]) -> Dict[str, Any]:
    """Tüm alanları Notion formatına çevirir ve son işlenen ISBN'i günceller."""
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
    
    # Son işlenen ISBN'i kaydet
    if current_isbn:
        updates["Last Processed ISBN"] = as_rich(current_isbn)
    
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
    """
    Notion'daki sadece şu kayıtları işler:
    1. Yeni eklenen kayıtlar (son X saat içinde)
    2. ISBN'i değişmiş kayıtlar (mevcut ISBN ≠ son işlenen ISBN)
    """
    logging.info("🚀 ISBN Takip Bazlı Senkronizasyon Başlatılıyor...")
    logging.info("📋 Yeni kayıtlar veya ISBN'i değişmiş kayıtlar işlenecek.\n")
    
    sorts = [{"timestamp": "created_time", "direction": "descending"}]
    limit = int(SCAN_LIMIT) if SCAN_LIMIT and SCAN_LIMIT.isdigit() else None
    
    if limit and limit > 0:
        logging.info(f"📄 Sadece en son {limit} sayfa taranacak.")
    else:
        logging.info("📄 Veritabanındaki tüm sayfalar taranacak.")
    
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

    logging.info(f"📚 Notion'dan {len(all_pages)} sayfa tarandı.\n")
    processed_count = 0
    skipped_count = 0

    for idx, page in enumerate(all_pages, 1):
        props = page.get("properties", {})
        page_id = page["id"]
        
        is_new = _was_recently_created(page)
        is_edited = _was_recently_edited(page)
        isbn_has_changed = _isbn_changed(props)
        needs_enrich = _needs_enrichment(props)

        # MANTIK: Yeni VEYA (düzenlenmiş VE ISBN değişmiş) VEYA (yeni ve eksik alanlar var)
        if not is_new and not (is_edited and isbn_has_changed):
            # Yeni ama eksik alanlar varsa yine de işle
            if not (is_new and needs_enrich):
                skipped_count += 1
                continue
        
        processed_count += 1
        title = _get_prop_value(props.get("Title"))
        gr_url = _get_prop_value(props.get("goodreadsURL"))
        current_isbn = _get_prop_value(props.get("ISBN"))
        display_name = title or gr_url or page_id
        
        logging.info(f"--- [{processed_count}] 📖: {display_name[:70]} ---")
        
        if is_new:
            logging.info("  ➡️ YENİ KAYIT - Tüm veriler çekilecek.")
        elif isbn_has_changed:
            logging.info("  ➡️ ISBN DEĞİŞMİŞ - Yeni ISBN için veriler çekilecek.")
        else:
            logging.info("  ➡️ ZENGİNLEŞTİRME GEREKLİ - Eksik alanlar doldurulacak.")

        scraped_data = fetch_book_data_pipeline(
            title=title,
            author=_get_prop_value(props.get("Author")),
            isbn=current_isbn,
            goodreads_url=gr_url,
        )

        if not scraped_data or not scraped_data.get("Title"):
            logging.warning("  -> Veri bulunamadı, atlanıyor.\n")
            continue

        updates = _build_updates(scraped_data, current_isbn)

        if not updates or len(updates) <= 1:  # Sadece Last Processed ISBN varsa
            logging.info("  -> Eklenecek yeni bilgi yok.\n")
            continue
        
        try:
            notion.pages.update(page_id=page_id, properties=updates)
            logging.info(f"  ✅ Notion güncellendi: {', '.join([k for k in updates.keys() if k != 'Last Processed ISBN'])}")
            _update_page_cover(page_id, scraped_data.get("Cover URL"))
            print()
        except Exception as e:
            logging.error(f"  ❌ Notion güncelleme hatası: {e}\n")
    
    logging.info("=" * 60)
    logging.info("✅ ISBN Takip Bazlı Senkronizasyon Tamamlandı!")
    logging.info(f"   📊 Toplam Taranan: {len(all_pages)}")
    logging.info(f"   ✅ İşlenen: {processed_count}")
    logging.info(f"   ⏭️  Atlanan: {skipped_count}")
    logging.info("=" * 60)
