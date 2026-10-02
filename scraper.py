import os
import re
import gdown
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Category mappings for supported languages
CATEGORY_URLS = {
    "hindi": "https://dailyepaper.in/category/hindi-epaper/",
    "english": "https://dailyepaper.in/category/english-epaper/",
    "odia": "https://dailyepaper.in/category/odia-epaper/",
    "marathi": "https://dailyepaper.in/category/marathi-epaper/",
    "bengali": "https://dailyepaper.in/category/bengali-epaper/",
}


def clean_paper_title(raw_title: str) -> str:
    """Extra title boilerplate clean karate."""
    patterns = [
        r"(?i)\s*ePaper\s*Download\s*Daily\s*After\s*07:00\s*AM",
        r"(?i)\s*Today\s*Download\s*After\s*07:00\s*AM",
        r"(?i)\s*Free\s*Download\s*Daily\s*After\s*07:00\s*AM",
        r"(?i)\s*Newspaper\s*Today\s*Download.*$",
        r"(?i)\s*ePaper\s*Hindi\s*Download.*$",
        r"(?i)\s*ePaper.*$",
    ]
    cleaned = raw_title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.strip()


def get_newspapers_by_language(language: str) -> dict:
    """STEP 1: User ne language select kelyavar category pages vrun sarv newspapers extract karte."""
    url = CATEGORY_URLS.get(language.lower(), CATEGORY_URLS["hindi"])

    try:
        response = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=15.0)
        if response.status_code != 200:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        headings = soup.select("article h2, article h3, .entry-title")
        papers = {}

        for heading in headings:
            raw_title = heading.get_text(strip=True)
            a_tag = heading.find("a")

            if a_tag and "href" in a_tag.attrs:
                post_url = a_tag["href"]
                clean_name = clean_paper_title(raw_title)
                if clean_name:
                    papers[clean_name] = post_url

        return papers

    except Exception as e:
        print(f"Scraper Error: {e}")
        return {}


def get_drive_link(post_url: str) -> str | None:
    """STEP 2: Selected paper chya post link vrun Google Drive URL shoondhte."""
    try:
        response = httpx.get(post_url, headers=HEADERS, follow_redirects=True, timeout=15.0)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Anchor tag check
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if ("drive.google.com" in href or "docs.google.com" in href) and "/forms/" not in href:
                return href

        # Regex fallback
        drive_pattern = r"https?://(?:drive|docs)\.google\.com/(?:file/d/|uc\?|drive/folders/)[^\s\"'<]+"
        match = re.search(drive_pattern, response.text)
        if match:
            return match.group(0)

        return None

    except Exception as e:
        print(f"Drive Extraction Error: {e}")
        return None


def download_pdf_from_drive(drive_url: str, output_path: str = "temp_newspaper.pdf") -> str | None:
    """STEP 3: Google Drive link vrun local storage madhe PDF download karte."""
    try:
        downloaded_path = gdown.download(drive_url, output_path, quiet=True, fuzzy=True)
        if downloaded_path and os.path.exists(downloaded_path):
            return downloaded_path
        return None
    except Exception as e:
        print(f"PDF Download Error: {e}")
        return None
