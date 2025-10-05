import re
import requests
from typing import Dict, Optional
from .utils import soup_from_html, extract_json_ld, textclean, pick_first

HEADERS = lambda ua: {"User-Agent": ua or "Mozilla/5.0", "Accept-Language": "tr,en;q=0.8"}

class ScrapeError(Exception):
    pass

def _og(soup, prop):
    t = soup.find("meta", property=f"og:{prop}")
    if t and t.get("content"):
        return t["content"].strip()
    return None

def fetch(url: str, user_agent: Optional[str] = None) -> str:
    r = requests.get(url, headers=HEADERS(user_agent), timeout=30)
    r.raise_for_status()
    return r.text

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

    pages = None
    txt = soup.get_text(" ")
    m = re.search(r"(\d{1,4})\s*(sayfa)\b", txt, flags=re.I)
    if m:
        pages = int(m.group(1))

    year = None
    m2 = re.search(r"(19|20)\d{2}", txt)
    if m2:
        year = int(m2.group(0))

    # description
    desc = None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        desc = meta_desc["content"].strip()
    elif soup.find("p"):
        desc = soup.find("p").get_text(strip=True)

    # language
    language = None
    lang_meta = soup.find("html")
    if lang_meta and lang_meta.get("lang"):
        language = lang_meta["lang"].split("-")[0].upper()
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

def scrape_goodreads(url: str, user_agent: Optional[str] = None) -> Dict:
    html = fetch(url, user_agent)
    soup = soup_from_html(html)
    j = extract_json_ld(soup)

    title = textclean(pick_first(
        j.get("name"),
        _og(soup, "title"),
    ))

    author = None
    if isinstance(j.get("author"), dict):
        author = j["author"].get("name")
    elif isinstance(j.get("author"), list) and j.get("author"):
        a0 = j.get("author")[0]
        if isinstance(a0, dict):
            author = a0.get("name")

    cover = pick_first(j.get("image"), _og(soup, "image"))

    publisher = None
    if isinstance(j.get("publisher"), dict):
        publisher = j["publisher"].get("name")
    elif isinstance(j.get("publisher"), str):
        publisher = j.get("publisher")

    translator = None
    txt = soup.get_text(" ")
    mtr = re.search(r"Translated by\s*([^\n\r]+)", txt, flags=re.I)
    if mtr:
        translator = mtr.group(1).strip()

    pages = None
    mp = re.search(r"(\d{1,4})\s*pages\b", txt, flags=re.I)
    if mp:
        pages = int(mp.group(1))

    year = None
    my = re.search(r"\b(19|20)\d{2}\b", txt)
    if my:
        year = int(my.group(0))

    desc = pick_first(j.get("description"), _og(soup, "description"))
    if not desc:
        ptag = soup.find("div", id="description")
        if ptag:
            desc = ptag.get_text(strip=True)

    language = None
    if j.get("inLanguage"):
        language = j.get("inLanguage")
    else:
        lang_html = soup.find("html")
        if lang_html and lang_html.get("lang"):
            language = lang_html["lang"].split("-")[0].upper()

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
        "source": "goodreads",
    }
