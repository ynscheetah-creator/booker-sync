import os
from typing import Dict
from dotenv import load_dotenv
from scrapers import scrape_1000kitap, scrape_goodreads, requests
from notion_sync import query_targets, update_page

load_dotenv()
UA = os.getenv("USER_AGENT", "Mozilla/5.0")

def try_scrape(url_1000: str, url_gr: str) -> Dict:
    # 1) Goodreads → ISBN varsa Google Books doğrulaması içerir
    if url_gr:
        try:
            data = scrape_goodreads(url_gr, UA)
            if data.get("Title") or data.get("Author"):
                return data
        except Exception as e:
            print(f"WARN: Goodreads scrape error: {e}")

    # 2) 1000Kitap (403 olabilir)
    if url_1000:
        try:
            return scrape_1000kitap(url_1000, UA)
        except requests.HTTPError as e:
            print(f"WARN: 1000Kitap fetch failed: {e}")
        except Exception as e:
            print(f"WARN: 1000Kitap scrape error: {e}")

    return {}

def run_once():
    results = query_targets()
    for row in results.get("results", []):
        pid = row["id"]
        props = row["properties"]
        u1000 = props.get("1000kitapURL", {}).get("url") if props.get("1000kitapURL") else None
        ugr = props.get("goodreadsURL", {}).get("url") if props.get("goodreadsURL") else None
        if not (u1000 or ugr):
            continue

        title_filled = bool(props.get("Title", {}).get("title"))
        author_filled = bool(props.get("Author", {}).get("rich_text"))
        if title_filled and author_filled:
            continue

        data = try_scrape(u1000, ugr)
        if data:
            update_page(pid, data)
            print(f"Updated: {pid} ← {data.get('source')} : {data.get('Title')}")
        else:
            print(f"WARN: No data for page {pid}")

if __name__ == "__main__":
    run_once()
