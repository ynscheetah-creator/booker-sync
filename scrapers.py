import re
import json
import requests
from typing import Dict, Optional
from utils import soup_from_html, extract_json_ld, textclean, pick_first

HEADERS = lambda ua: {"User-Agent": ua or "Mozilla/5.0", "Accept-Language": "tr,en;q=0.8"}

class ScrapeError(Exception):
    pass

def _og(soup, prop):
    tag = soup.find("meta", property=f"og:{prop}")
    return tag.get("content", "").strip() if tag and tag.get("content") else None

def _meta_name(soup, name):
    tag = soup.find("meta", attrs={"name": name})
    return tag.get("content", "").strip() if tag and tag.get("content") else None

def _meta_prop(soup, prop):
    tag = soup.find("meta", attrs={"property": prop})
    return tag.get("content", "").strip() if tag and tag.get("content") else None

def fetch(url: str, user_agent: Optional[str] = None) -> str:
    r = requests.get(url, headers=HEADERS(user_agent), timeout=30)
    r.raise_for_status()
    return r.text

# ---------- Google Books fallback (ISBN ile) ----------
def googlebooks_by_isbn(isbn: Optional[str], user_agent: Optional[str] = None) -> Dict:
    if not isbn:
        return {}
    try:
        r = requests.get(
            f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}",
            headers=HEADERS(user_agent),
            timeout=30,
        )
        if r.status_code != 200:
            return {}
        j = r.json()
        items = j.get("items") or []
        if not items:
            return {}
        v = items[0].get("volumeInfo", {})
        lang = (v.get("language") or "").upper() if v.get("language") else None
        year = None
        if isinstance(v.get("publishedDate"), str) and v["publishedDate"][:4].isdigit():
            year = int(v["publishedDate"][:4])
        cover = None
        if isinstance(v.get("imageLinks"), dict):
            cover = v["imageLinks"].get("thumbnail") or v["imageLinks"].get("smallThumbnail")

        return {
            "Title": v.get("title"),
            "Author": ", ".join(v.get("authors", [])) if v.get("authors") else None,
            "Publisher": v.get("publisher"),
            "Year Published": year,
            "Number of Pages": v.get("pageCount"),
            "coverURL": cover,
            "Language": lang,
            "Description": v.get("description"),
        }
    except Exception:
        return {}

# ---------- 1000Kitap ----------
def scrape_1000kitap(url: str, user_agent: Optional[str] = None) -> Dict:
    html = fetch(url, user_agent)
    soup = soup_from_html(html)
    j = extract_json_ld(soup)

    title = textclean(pick_first(
        j.get("name"),
        soup.find("h1").get_text(strip=True) if soup.find("h1") else None,
        _og(soup, "title"),
    ))

    author = None
    if isinstance(j.get("author"), dict):
        author = j.get("author", {}).get("name")
    elif isinstance(j.get("author"), list) and j.get("author"):
        a0 = j.get("author")[0]
        if isinstance(a0, dict):
            author = a0.get("name")
    if not author:
        a_tag = soup.find("a", href=re.compile(r"/yazar/"))
        author = a_tag.get_text(strip=True) if a_tag else None

    cover = pick_first(j.get("image"), _og(soup, "image"))

    publisher = None
    if isinstance(j.get("publisher"), dict):
        publisher = j["publisher"].get("name")
    elif isinstance(j.get("publisher"), str):
        publisher = j.get("publisher")
    if not publisher:
        pub_a = soup.find("a", href=re.compile(r"/yayinevi/"))
        publisher = pub_a.get_text(strip=True) if pub_a else None

    translator = None
    tr_a = soup.find("a", href=re.compile(r"/cevirmen/"))
    if tr_a:
        translator = tr_a.get_text(strip=True)

    txt = soup.get_text(" ")
    pages = None
    m = re.search(r"(\d{1,4})\s*(sayfa)\b", txt, flags=re.I)
    if m:
        pages = int(m.group(1))

    year = None
    m2 = re.search(r"\b(19|20)\d{2}\b", txt)
    if m2:
        year = int(m2.group(0))

    # açıklama
    desc = _meta_name(soup, "description") or (soup.find("p").get_text(strip=True) if soup.find("p") else None)

    # dil
    language = None
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        language = html_tag["lang"].split("-")[0].upper()
    elif "dil" in txt.lower():
        mlang = re.search(r"[Dd]il[:\s]+([A-Za-zÇĞİÖŞÜçğıöşü]+)", txt)
        if mlang:
            language = mlang.group(1).capitalize()

    return {
        "Title": title,
        "Author": author,
        "Translator": translator,
        "Publisher": publisher,
        "Number of Pages": pages,
        "coverURL": cover,
        "Year Published": year,
        "Language": language,
        "Description": desc,
        "source": "1000kitap",
    }

# ---------- Goodreads (ISBN → Google Books ile doğrulama) ----------
def scrape_goodreads(url: str, user_agent: Optional[str] = None) -> Dict:
    html = fetch(url, user_agent)
    soup = soup_from_html(html)
    j = extract_json_ld(soup)

    # Temel alanlar
    title = textclean(pick_first(
        _og(soup, "title"),
        j.get("name"),
    ))

    # Author: meta[name='author'] → yoksa sayfadaki /author/ linki
    author = _meta_name(soup, "author")
    if not author:
        a = soup.find("a", href=re.compile(r"/author/"))
        author = a.get_text(strip=True) if a else None

    cover = pick_first(
        _og(soup, "image"),
        j.get("image"),
    )

    # ISBN, sayfa, yıl (OpenGraph 'books.*' alanları)
    isbn = _meta_prop(soup, "books:isbn")
    pages = None
    mp = _meta_prop(soup, "books:page_count")
    if mp and mp.isdigit():
        pages = int(mp)
    year = None
    rdate = _meta_prop(soup, "books:release_date")
    if rdate and rdate[:4].isdigit():
        year = int(rdate[:4])

    desc = _meta_name(soup, "description") or _og(soup, "description") or j.get("description")

    # Dil (varsa JSON-LD'de)
    language = None
    if j.get("inLanguage"):
        language = str(j.get("inLanguage")).upper()
    else:
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            language = html_tag["lang"].split("-")[0].upper()

    data = {
        "Title": title,
        "Author": author,
        "Publisher": None,                     # aşağıda GB ile dolabilir
        "Number of Pages": pages,
        "coverURL": cover,
        "Year Published": year,
        "Language": language,
        "Description": desc,
        "source": "goodreads",
    }

    # ISBN varsa Google Books ile doğrula / zenginleştir
    gb = googlebooks_by_isbn(isbn, user_agent)
    if gb:
        # GB verisi olan alanları doldur/override et
        for k, v in gb.items():
            if v:
                data[k] = v

    return data
