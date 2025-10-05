import os
from typing import Dict
from dotenv import load_dotenv
from notion_sync import query_targets, update_page
from googlebooks import fetch_google_books

load_dotenv()
UA = os.getenv("USER_AGENT", "Mozilla/5.0")

def try_google(url_1000: str, url_gr: str) -> Dict:
    # URL varsa slug veya isbn/title kısmını al
    q = None
    for u in (url_gr, url_1000):
        if not u:
            continue
        if "isbn" in u.lower():
            q = u.split("isbn")[-1].strip("=/:")
            break
        slug = u.rstrip("/").split("/")[-1]
        if slug and not slug.startswith("kitap"):
            q = slug.replace("-", " ")
            break
    if not q:
        return {}
    return fetch_google_books(q, UA)

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

        data = try_google(u1000, ugr)
        if data:
            update_page(pid, data)
            print(f"Updated: {pid} ← {data.get('source')} : {data.get('Title')}")
        else:
            print(f"WARN: No data for page {pid}")

if __name__ == "__main__":
    run_once()
