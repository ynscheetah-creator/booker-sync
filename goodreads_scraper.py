import json, re, requests
from bs4 import BeautifulSoup
from typing import Dict, Optional

def _clean(s: Optional[str]) -> Optional[str]:
    if s is None: return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None

def _to_int(s: Optional[str]) -> Optional[int]:
    if not s: return None
    m = re.search(r"\d{1,4}", s)
    return int(m.group(0)) if m else None

def _find_book_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("@type") in ("Book", ["Book"]):
                    return it
        except Exception:
            continue
    return None

def fetch_goodreads(url: str, ua: Optional[str] = None) -> Dict:
    headers = {
        "User-Agent": ua or "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
        "Referer": "https://www.google.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
    if r.status_code != 200 or not r.text:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) Eğer URL kitap sayfası değilse, canonical ile gerçek kitabı bulmayı dene
    canon = soup.find("link", attrs={"rel":"canonical"})
    if canon and canon.has_attr("href"):
        href = canon["href"]
        if "/book/show/" in href and href != r.url:
            r = requests.get(href, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code != 200 or not r.text:
                return {}
            soup = BeautifulSoup(r.text, "html.parser")

    # 2) Son sayfa yine de kitap değilse (og:type veya JSON-LD yoksa) atla
    og_type = soup.find("meta", {"property": "og:type"})
    if og_type and og_type.has_attr("content"):
        if og_type["content"].lower() not in ("book","books.book"):
            return {}

    jd = _find_book_json_ld(soup)
    if not jd:
        # JSON-LD yoksa da güvenilir değil → atla
        return {}

    # ... (buradan sonrası senin mevcut kodunla aynı; jd kullanılıyor)

    # JSON-LD (schema.org/Book)
    jd = _find_book_json_ld(soup) or {}

    # author (tek/liste)
    author = None
    if jd.get("author"):
        if isinstance(jd["author"], list):
            author = ", ".join([_clean(a.get("name")) for a in jd["author"] if isinstance(a, dict) and a.get("name")])
        elif isinstance(jd["author"], dict):
            author = _clean(jd["author"].get("name"))

    publisher = _clean(jd.get("publisher", {}).get("name") if isinstance(jd.get("publisher"), dict) else jd.get("publisher"))
    year = None
    if isinstance(jd.get("datePublished"), str) and jd["datePublished"][:4].isdigit():
        year = int(jd["datePublished"][:4])

    isbn13 = _clean(jd.get("isbn"))
    pages  = jd.get("numberOfPages")
    if isinstance(pages, str):
        pages = _to_int(pages)
    lang = _clean(jd.get("inLanguage"))

    # fallback'lar
    if not isbn13:
        m = re.search(r'ISBN(?:-13)?:?\s*</[^>]+>\s*([0-9\-]{10,17})', r.text, flags=re.I)
        if m: isbn13 = _clean(m.group(1)).replace("-", "")
    if not pages:
        m = re.search(r'(\d{1,4})\s+pages', r.text, flags=re.I)
        if m: pages = int(m.group(1))

    name = _clean(jd.get("name")) or title
    description = _clean(jd.get("description")) or desc

    return {
        "Title": name,
        "Author": author,
        "Publisher": publisher,
        "Year Published": year,
        "Number of Pages": pages,
        "ISBN13": isbn13,
        "Language": (lang or "").upper() if lang else None,
        "Description": description,
        "coverURL": cover,
        "source": "goodreads",
    }
