import os
from dotenv import load_dotenv
from goodreads_scraper import fetch_goodreads
from notion_sync import query_targets, update_page

load_dotenv()
UA = os.getenv("USER_AGENT", "Mozilla/5.0")

def run_once():
    resp = query_targets()
    for row in resp.get("results", []):
        pid   = row["id"]
        props = row["properties"]
        gr_url = props.get("goodreadsURL",{}).get("url")
        if not gr_url:
            print(f"SKIP no GR url: {pid}")
            continue
        data = fetch_goodreads(gr_url, UA) or {}
        if not data:
            print(f"WARN could not parse GR: {pid} -> {gr_url}")
            continue
        # kolon ismi 'Cover URL' ise de dolsun
        if data.get("coverURL"):
            data["Cover URL"] = data["coverURL"]
        update_page(pid, data)
        print(f"Updated {pid}: {data.get('Title')}")

if __name__ == "__main__":
    run_once()
