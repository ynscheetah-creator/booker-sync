import sys
from goodreads_scraper import fetch_goodreads
import json

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.goodreads.com/book/show/13038020-i-bulma-i-darehanesi"
    data = fetch_goodreads(url)
    print(json.dumps(data, ensure_ascii=False, indent=2))
