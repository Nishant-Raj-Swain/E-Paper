import re
import os
import httpx
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

CATEGORY_URLS = {
    "hindi": "https://dailyepaper.in/category/hindi-epaper/",
    "english": "https://dailyepaper.in/category/english-epaper/",
    "odia": "https://dailyepaper.in/category/odia-epaper/",
    "marathi": "https://dailyepaper.in/category/marathi-epaper/",
    "bengali": "https://dailyepaper.in/category/bengali-epaper/",
}


def clean_paper_title(raw_title: str) -> str:
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
    base_url = CATEGORY_URLS.get(language.lower(), CATEGORY_URLS["hindi"])
    
    # List containing Page 1 and Page 2 URLs
    urls_to_scrape = [
        base_url,
        f"{base_url.rstrip('/')}/page/2/"
    ]
    
    papers = {}

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20.0) as client:
        for url in urls_to_scrape:
            try:
                response = client.get(url)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                # Multi-selector fix for Odia and other varied post card formats
                headings = soup.select("article h2, article h3, .entry-title, h2.post-title, h3.post-title")

                for heading in headings:
                    raw_title = heading.get_text(strip=True)
                    a_tag = heading.find("a") if heading.name != "a" else heading

                    if a_tag and "href" in a_tag.attrs:
                        post_url = a_tag["href"]
                        clean_name = clean_paper_title(raw_title)
                        if clean_name and clean_name not in papers:
                            papers[clean_name] = post_url

            except Exception as e:
                print(f"Scraper Error for {language} on {url}: {e}")

    return papers


def get_drive_link(post_url: str) -> str | None:
    try:
        response = httpx.get(post_url, headers=HEADERS, follow_redirects=True, timeout=20.0)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Search anchor tags
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if ("drive.google.com" in href or "docs.google.com" in href) and "/forms/" not in href:
                return href

        # 2. Regex fallback
        drive_pattern = r"https?://(?:drive|docs)\.google\.com/(?:file/d/|uc\?|drive/folders/)[^\s\"'<]+"
        match = re.search(drive_pattern, response.text)
        if match:
            return match.group(0)

        return None

    except Exception as e:
        print(f"Drive Extraction Error: {e}")
        return None


def extract_drive_id(url: str) -> str | None:
    """Extracts File ID from any Google Drive link format."""
    match = re.search(r"(?:file/d/|id=|=)([a-zA-Z0-9_-]{25,})", url)
    return match.group(1) if match else None


def download_pdf_from_drive(drive_url: str, output_path: str = "temp_newspaper.pdf") -> str | None:
    """Direct stream downloader with Google Drive confirmation token bypass."""
    file_id = extract_drive_id(drive_url)
    if not file_id:
        return None

    session = requests.Session()
    download_url = "https://docs.google.com/uc?export=download"

    try:
        response = session.get(download_url, params={"id": file_id}, headers=HEADERS, stream=True, timeout=30)
        
        # Check for Google Drive virus scan warning token
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                response = session.get(
                    download_url,
                    params={"id": file_id, "confirm": value},
                    headers=HEADERS,
                    stream=True,
                    timeout=30,
                )
                break

        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                return output_path

    except Exception as e:
        print(f"Bypass Download Error: {e}")

    return None
