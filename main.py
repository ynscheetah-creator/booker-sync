import os
from typing import Dict
from dotenv import load_dotenv
from .scrapers import scrape_1000kitap, scrape_goodreads
from .notion_sync import query_targets, update_page

load_dotenv()

UA = os.getenv("USER_AGENT", "Mozilla/5.0")

def detect_and_scrape(url: str) -> Dict:
    if not url:
        return {}
    if "1000kitap.com" in url:
        return scrape_1000kitap(url, UA)
    if "goodreads.com" in url:
        return scrape_goodreads(url, UA)
    return {}

def run_once():
    results = query_targets()
    for row in results.get("results", []):
        pid = row["id"]
        props = row["properties"]
        u1000 = props.get("1000kitapURL", {}).get("url") if props.get("1000kitapURL") else None
        ugr = props.get("goodreadsURL", {}).get("url") if props.get("goodreadsURL") else None

        title_filled = bool(props.get("Title", {}).get("title"))
        author_filled = bool(props.get("Author", {}).get("rich_text"))
        if title_filled and author_filled:
            continue

        url = u1000 or ugr
        if not url:
            continue

        try:
            data = detect_and_scrape(url)
            if data:
                update_page(pid, data)
                print(f"Updated: {pid} ← {data.get('source')} : {data.get('Title')}")
        except Exception as e:
            print(f"WARN: {pid} {e}")

if __name__ == "__main__":
    run_once()
