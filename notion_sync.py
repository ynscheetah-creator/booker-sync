def fetch_book_data(
    title: str = None,
    author: str = None,
    isbn: str = None,
    goodreads_url: str = None,
    preferred_language: str = None  # YENİ
) -> Dict[str, Optional[str]]:
    """API'lerden kitap verisi çek"""
    data = {}
    
    if goodreads_url:
        book_id = _extract_book_id_from_url(goodreads_url)
        if book_id:
            data["Book Id"] = book_id
            data["goodreadsURL"] = goodreads_url
    
    if isbn:
        print(f"  🔍 Searching by ISBN: {isbn}")
        
        google_data = fetch_from_google_books(isbn=isbn)
        if google_data and google_data.get("Title"):
            print(f"  ✅ Found in Google Books (ISBN): {google_data['Title']}")
            data.update({k: v for k, v in google_data.items() if v})
            return data
        
        ol_data = fetch_from_openlibrary(isbn=isbn)
        if ol_data and ol_data.get("Title"):
            print(f"  ✅ Found in OpenLibrary (ISBN): {ol_data['Title']}")
            data.update({k: v for k, v in ol_data.items() if v})
            return data
    
    if title:
        # Dil tercihine göre arama
        lang_code = None
        if preferred_language == "Turkish":
            lang_code = "tr"
            print(f"  🇹🇷 Searching Turkish edition: {title[:50]}...")
        else:
            print(f"  🔍 Searching by Title: {title[:50]}...")
        
        google_data = fetch_from_google_books(
            title=title, 
            author=author,
            language=lang_code  # Türkçe filtresi
        )
        if google_data and google_data.get("Title"):
            print(f"  ✅ Found in Google Books: {google_data['Title']}")
            data.update({k: v for k, v in google_data.items() if v})
            return data
        
        ol_data = fetch_from_openlibrary(title=title, author=author)
        if ol_data and ol_data.get("Title"):
            print(f"  ✅ Found in OpenLibrary: {ol_data['Title']}")
            data.update({k: v for k, v in ol_data.items() if v})
            return data
    
    print("  ⚠️  No data found from any API")
    return data
