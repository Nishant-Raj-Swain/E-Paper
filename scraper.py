import os
import re
import httpx
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CATEGORY_URLS = {
    "english": [
        "https://dailyepaper.in/english-newspapers/",
        "https://dailyepaper.in/category/english-epaper/",
    ],
    "hindi": [
        "https://dailyepaper.in/hindi-newspapers/",
        "https://dailyepaper.in/category/hindi-epaper/",
    ],
    "odia": [
        "https://dailyepaper.in/odia-newspapers/",
        "https://dailyepaper.in/category/odia-epaper/",
    ],
    "marathi": [
        "https://dailyepaper.in/marathi-newspapers/",
        "https://dailyepaper.in/category/marathi-epaper/",
    ],
    "bengali": [
        "https://dailyepaper.in/bengali-newspapers/",
        "https://dailyepaper.in/category/bengali-epaper/",
    ],
}

NAV_IGNORE = {
    "home", "english", "hindi", "tamil", "telugu", "marathi", "punjabi", "odia",
    "kannada", "malyalam", "bengali", "gujrati", "assam", "urdu", "about us",
    "dmca", "contact us", "privacy policy", "disclaimer", "all english",
    "all regional", "all tamil", "all telugu", "all hindi", "all epapers",
    "menu", "categories", "recent posts", "download pdf", "download",
    "read todays hindi", "hindi newspapers", "english newspapers"
}


def clean_paper_title(raw_title: str) -> str:
    """Removes boilerplate button labels, years, and download suffixes."""
    patterns = [
        r"(?i)\s*Download\s*PDF",
        r"(?i)\s*ePaper\s*Download\s*Daily\s*After\s*07:00\s*AM",
        r"(?i)\s*Today\s*Download\s*After\s*07:00\s*AM",
        r"(?i)\s*Free\s*Download\s*Daily\s*After\s*07:00\s*AM",
        r"(?i)\s*Newspaper\s*Today\s*Download.*$",
        r"(?i)\s*ePaper\s*(?:Hindi|Odia|Marathi|Bengali|English)\s*Download.*$",
        r"(?i)\s*ePaper\s*Free\s*Download.*$",
        r"(?i)\s*Free\s*Download.*$",
        r"(?i)\s*ePaper.*$",
        r"(?i)\s*PDF\s*Download.*$",
        r"\b202[0-9]\b",
    ]
    cleaned = raw_title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.strip()


def extract_title_from_url(url: str) -> str:
    """Converts a post URL slug into a readable paper title."""
    # Example: https://dailyepaper.in/dainik-jagran-epaper-free-download-2026/ -> dainik-jagran
    slug = url.rstrip("/").split("/")[-1]
    title = clean_paper_title(slug.replace("-", " "))
    return title.title()


def get_newspapers_by_language(language: str) -> dict:
    """Scrapes newspaper titles directly from individual post links in the content body."""
    urls = CATEGORY_URLS.get(language.lower(), CATEGORY_URLS["hindi"])
    papers = {}

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25.0) as client:
        for url in urls:
            try:
                response = client.get(url)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                # Remove header, footer, and sidebar navigation
                for nav in soup.select("header, footer, nav, sidebar, .widget, #masthead, #site-navigation, .menu"):
                    nav.decompose()

                # Isolate main body
                main_area = soup.select_one("main, #content, .site-main, .entry-content, article") or soup

                # Extract all post links
                all_links = main_area.find_all("a", href=True)

                for link in all_links:
                    href = link["href"]

                    # Exclude non-article URLs
                    if not ("dailyepaper.in/" in href) or any(
                        x in href for x in ["/category/", "/page/", "/tag/", "#", "contact", "privacy", "about", "dmca"]
                    ):
                        continue

                    # Try getting title from anchor text, image alt, or title attribute
                    raw_text = link.get_text(strip=True)
                    if not raw_text or raw_text.lower() in ["download pdf", "download", "click here"]:
                        img = link.find("img")
                        if img and img.get("alt"):
                            raw_text = img["alt"]
                        elif link.get("title"):
                            raw_text = link["title"]

                    clean_name = clean_paper_title(raw_text)

                    # Fallback to URL slug parsing if link text was missing/generic
                    if not clean_name or clean_name.lower() in NAV_IGNORE:
                        clean_name = extract_title_from_url(href)

                    if (
                        clean_name
                        and len(clean_name) > 2
                        and clean_name.lower() not in NAV_IGNORE
                        and clean_name not in papers.values()
                    ):
                        papers[clean_name] = href

                if len(papers) >= 3:
                    break

            except Exception as e:
                print(f"Scraper Error for {language} at {url}: {e}")

    return papers


def get_drive_link(post_url: str) -> str | None:
    """Extracts Google Drive link from the paper's individual post page."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25.0) as client:
            response = client.get(post_url)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # 1. Direct Google Drive links
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
    match = re.search(r"(?:file/d/|id=|=)([a-zA-Z0-9_-]{25,})", url)
    return match.group(1) if match else None


def download_pdf_from_drive(drive_url: str, output_path: str = "temp_newspaper.pdf") -> str | None:
    file_id = extract_drive_id(drive_url)
    if not file_id:
        return None

    session = requests.Session()
    download_url = "https://docs.google.com/uc?export=download"

    try:
        response = session.get(download_url, params={"id": file_id}, headers=HEADERS, stream=True, timeout=30)

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
