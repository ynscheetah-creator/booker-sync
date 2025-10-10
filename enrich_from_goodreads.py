# enrich_from_goodreads.py
import sys
from goodreads_scraper import fetch_goodreads
import json


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python enrich_from_goodreads.py <goodreads_url>")
        print("\nExample:")
        print("  python enrich_from_goodreads.py https://www.goodreads.com/book/show/13038020")
        sys.exit(1)

    url = sys.argv[1]
    print(f"🔍 Fetching data from: {url}\n")

    try:
        data = fetch_goodreads(url)
        print("\n" + "=" * 60)
        print("📚 SCRAPED DATA:")
        print("=" * 60)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
