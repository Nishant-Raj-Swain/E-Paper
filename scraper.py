import os
import re
from datetime import datetime
from urllib.parse import urljoin

import httpx
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dailyepaper.in"
HOME_URL = f"{BASE_URL}/daily-news/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Language pages follow the pattern https://dailyepaper.in/<language>-newspapers/
KNOWN_LANGUAGES = [
    "english", "hindi", "bengali", "kannada", "telugu", "tamil", "marathi",
    "odia", "punjabi", "malayalam", "gujarati", "assamese", "urdu",
]

# Old category pages, kept only as a fallback if the new language page yields nothing
CATEGORY_URLS = {
    "hindi": "https://dailyepaper.in/category/hindi-epaper/",
    "english": "https://dailyepaper.in/category/english-epaper/",
    "odia": "https://dailyepaper.in/category/odia-epaper/",
    "marathi": "https://dailyepaper.in/category/marathi-epaper/",
    "bengali": "https://dailyepaper.in/category/bengali-epaper/",
}

DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\b")

# Human-readable reason for the last failed download (handy to show in your UI)
LAST_ERROR = ""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _get_soup(url: str) -> BeautifulSoup | None:
    try:
        response = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=20.0)
        if response.status_code != 200:
            return None
        return BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"Fetch error for {url}: {e}")
        return None


def clean_paper_title(raw_title: str) -> str:
    """Strips download tags, dates, analysis suffixes, and boilerplate labels from titles."""
    patterns = [
        r"(?i)\s*Analysis.*$",
        r"(?i)\s*Newspaper.*$",
        r"(?i)\s*ePaper.*$",
        r"(?i)\s*Today\s*Free\s*Download.*$",
        r"(?i)\s*Free\s*Download.*$",
        r"(?i)\s*Download.*$",
        r"(?i)\s*PDF.*$",
        r"\b202[0-9]\b",
    ]
    cleaned = raw_title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.strip()


# --------------------------------------------------------------------------
# step 1: languages
# --------------------------------------------------------------------------
def get_languages() -> dict:
    """Returns {'odia': language_page_url, ...} from the 'Browse by Language' cards."""
    languages = {}
    soup = _get_soup(HOME_URL)
    if soup:
        for a_tag in soup.find_all("a", href=True):
            if "download now" not in a_tag.get_text(" ", strip=True).lower():
                continue
            card = a_tag.find_parent(["div", "li", "article"])
            text = " ".join(card.get_text(" ", strip=True).split()) if card else ""
            match = re.search(r"([A-Za-z]+)\s+Epaper\s+\d+\s+Newspapers", text, re.I)
            if match:
                languages[match.group(1).lower()] = urljoin(BASE_URL, a_tag["href"])

    if not languages:  # fallback to URL pattern
        languages = {lang: f"{BASE_URL}/{lang}-newspapers/" for lang in KNOWN_LANGUAGES}
    return languages


def _language_url(language: str) -> str:
    language = language.lower().strip()
    return get_languages().get(language, f"{BASE_URL}/{language}-newspapers/")


# --------------------------------------------------------------------------
# step 2: papers of a language  ->  {paper name: paper page url}
# --------------------------------------------------------------------------
def _legacy_category_papers(language: str) -> dict:
    """Old behaviour: scrape post titles from /category/<language>-epaper/ pages."""
    base_url = CATEGORY_URLS.get(language.lower())
    if not base_url:
        return {}

    papers = {}
    for url in (base_url, f"{base_url.rstrip('/')}/page/2/"):
        soup = _get_soup(url)
        if not soup:
            continue
        headings = soup.select("article h2, article h3, .entry-title, h2.post-title, h3.post-title")
        for heading in headings:
            a_tag = heading.find("a") if heading.name != "a" else heading
            if a_tag and "href" in a_tag.attrs:
                name = clean_paper_title(heading.get_text(strip=True))
                if name and name not in papers:
                    papers[name] = a_tag["href"]
    return papers


def get_newspapers_by_language(language: str) -> dict:
    papers = {}
    soup = _get_soup(_language_url(language))

    if soup:
        for a_tag in soup.find_all("a", href=True):
            if "download pdf" not in a_tag.get_text(" ", strip=True).lower():
                continue

            name = None
            card = a_tag.find_parent(["div", "li", "article"])
            # only trust the card text if it belongs to this single button
            if card and len(card.find_all("a", string=re.compile("download pdf", re.I))) == 1:
                texts = [
                    t.strip() for t in card.stripped_strings
                    if "download" not in t.lower() and len(t.strip()) > 2
                ]
                name = texts[-1] if texts else None

            if not name:  # derive from URL slug: /sambad-epaper-free-download-2026/
                slug = a_tag["href"].rstrip("/").split("/")[-1]
                name = re.split(r"-e-?paper", slug)[0].replace("-", " ").title()

            if name and name not in papers:
                papers[name] = urljoin(BASE_URL, a_tag["href"])

    if not papers:
        papers = _legacy_category_papers(language)

    return papers


# --------------------------------------------------------------------------
# step 3: dated editions of a paper  ->  [(date_str, link), ...] newest first
# --------------------------------------------------------------------------
def _parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%d %b %Y")
    except ValueError:
        return datetime.min


def get_editions(post_url: str) -> list:
    """Reads rows like '02 Oct 2026: Download Now'. Holiday rows (no link) are skipped."""
    soup = _get_soup(post_url)
    if not soup:
        return []

    editions = []
    seen = set()
    for a_tag in soup.find_all("a", href=True):
        if "download now" not in a_tag.get_text(" ", strip=True).lower():
            continue
        parent_text = a_tag.parent.get_text(" ", strip=True) if a_tag.parent else ""
        match = DATE_RE.search(parent_text)
        if not match:
            continue
        date_str = " ".join(match.groups())
        if date_str in seen:
            continue
        seen.add(date_str)
        editions.append((date_str, urljoin(BASE_URL, a_tag["href"])))

    editions.sort(key=lambda e: _parse_date(e[0]), reverse=True)
    return editions


# --------------------------------------------------------------------------
# step 4: resolve the Google Drive link
# --------------------------------------------------------------------------
def _resolve_to_drive(link: str) -> str | None:
    """The 'Download Now' link may be a direct Drive link or go through a redirect."""
    if "drive.google.com" in link or "docs.google.com" in link:
        return link
    try:
        response = httpx.get(link, headers=HEADERS, follow_redirects=True, timeout=20.0)
        for hop in list(response.history) + [response]:
            if "drive.google.com" in str(hop.url) or "docs.google.com" in str(hop.url):
                return str(hop.url)
        match = re.search(r"https?://(?:drive|docs)\.google\.com/[^\s\"'<>]+", response.text)
        if match:
            return match.group(0)
    except Exception as e:
        print(f"Redirect resolve error: {e}")
    return None


def get_drive_link(post_url: str, date: str | None = None) -> str | None:
    """
    Returns the Drive link for a paper page.
    date: e.g. '02 Oct 2026'. If omitted, the newest edition is used.
    """
    editions = get_editions(post_url)
    if editions:
        link = editions[0][1]
        if date:
            link = next((l for d, l in editions if d == date), link)
        drive = _resolve_to_drive(link)
        if drive:
            return drive

    # Fallback: old behaviour, first Drive link found anywhere on the page
    soup = _get_soup(post_url)
    if not soup:
        return None
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if ("drive.google.com" in href or "docs.google.com" in href) and "/forms/" not in href:
            return href
    match = re.search(
        r"https?://(?:drive|docs)\.google\.com/(?:file/d/|uc\?|drive/folders/)[^\s\"'<]+",
        soup.decode(),
    )
    return match.group(0) if match else None


def extract_drive_id(url: str) -> str | None:
    """Extracts the file ID from a Google Drive link (folder links are not supported)."""
    if "/folders/" in url:
        return None
    match = re.search(r"(?:/file/d/|/d/|[?&]id=)([a-zA-Z0-9_-]{20,})", url)
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# step 5: download
# --------------------------------------------------------------------------
def _save_if_pdf(response: requests.Response, output_path: str) -> bool:
    """Streams the response to disk only if it really is a PDF (not an HTML error page)."""
    global LAST_ERROR
    first = next(response.iter_content(chunk_size=32768), b"")

    if not first.startswith(b"%PDF"):
        text = first.decode("utf-8", errors="ignore")
        if "Too many users" in text or "quota" in text.lower():
            LAST_ERROR = "Google Drive download quota exceeded for this file. Try later or another edition."
        else:
            LAST_ERROR = "Drive returned a web page instead of the PDF."
        return False

    with open(output_path, "wb") as f:
        f.write(first)
        for chunk in response.iter_content(chunk_size=32768):
            if chunk:
                f.write(chunk)
    return os.path.getsize(output_path) > 10000


def download_pdf_from_drive(drive_url: str, output_path: str = "temp_newspaper.pdf") -> str | None:
    """Tries the current Drive endpoint first, then the legacy cookie-token flow."""
    global LAST_ERROR
    LAST_ERROR = ""

    file_id = extract_drive_id(drive_url)
    if not file_id:
        LAST_ERROR = "Could not find a Drive file id in the link."
        return None

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Strategy 1: current direct-download endpoint (confirm=t skips the virus-scan page)
        response = session.get(
            "https://drive.usercontent.google.com/download",
            params={"id": file_id, "export": "download", "confirm": "t"},
            stream=True,
            timeout=30,
        )
        if response.status_code == 200 and _save_if_pdf(response, output_path):
            return output_path

        # Strategy 2: legacy endpoint with the download_warning cookie token
        url = "https://docs.google.com/uc?export=download"
        response = session.get(url, params={"id": file_id}, stream=True, timeout=30)
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                response = session.get(
                    url, params={"id": file_id, "confirm": value}, stream=True, timeout=30
                )
                break
        if response.status_code == 200 and _save_if_pdf(response, output_path):
            return output_path

    except Exception as e:
        LAST_ERROR = f"Download error: {e}"
        print(LAST_ERROR)

    if os.path.exists(output_path) and os.path.getsize(output_path) <= 10000:
        os.remove(output_path)
    return None


def download_latest_available(post_url: str, output_path: str = "temp_newspaper.pdf",
                              max_editions: int = 3) -> tuple[str, str] | None:
    """
    Tries the newest edition first and falls back to older ones if Drive blocks the file.
    Returns (path, date) on success, None otherwise.
    """
    for date, link in get_editions(post_url)[:max_editions]:
        drive_url = _resolve_to_drive(link)
        if not drive_url:
            continue
        path = download_pdf_from_drive(drive_url, output_path)
        if path:
            return path, date
        print(f"{date}: {LAST_ERROR or 'download failed'}")
    return None


# --------------------------------------------------------------------------
# quick manual test:  python scrapper.py
# --------------------------------------------------------------------------
if __name__ == "__main__":
    lang = "odia"
    papers = get_newspapers_by_language(lang)
    print(f"{lang}: {list(papers)}")
    if papers:
        name, url = next(iter(papers.items()))
        print("Editions:", get_editions(url)[:3])
        result = download_latest_available(url)
        print("Result:", result or LAST_ERROR)
