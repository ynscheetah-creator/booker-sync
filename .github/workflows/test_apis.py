# test_apis.py
from google_books_api import fetch_from_google_books
from openlibrary_api import fetch_from_openlibrary
import json


def test_book():
    """Test kitabı: İş Bulma İdarehanesi"""
    title = "İş Bulma İdarehanesi"
    author = "Panait Istrati"
    
    print("="*60)
    print(f"Testing: {title} by {author}")
    print("="*60)
    
    print("\n1️⃣  GOOGLE BOOKS:")
    print("-" * 60)
    gb_data = fetch_from_google_books(title=title, author=author)
    print(json.dumps(gb_data, ensure_ascii=False, indent=2))
    
    print("\n2️⃣  OPENLIBRARY:")
    print("-" * 60)
    ol_data = fetch_from_openlibrary(title=title, author=author)
    print(json.dumps(ol_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    test_book()
