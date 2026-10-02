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

# Base WordPress category endpoint mappings
CATEGORY_BASES = {
    "hindi": "https://dailyepaper.in/category/hindi-epaper/",
    "english": "https://dailyepaper.in/category/english-epaper/",
    "bengali": "https://dailyepaper.in/category/bengali-epaper/",
    "odia": "https://dailyepaper.in/category/odia-epaper/",
    "marathi": "https://dailyepaper.in/category/marathi-epaper/",
}

NAV_IGNORE = {
    "home", "english", "hindi", "tamil", "telugu", "marathi", "punjabi", "odia",
    "kannada", "malyalam", "bengali", "gujrati", "assam", "urdu", "about us",
    "dmca", "contact us", "privacy policy", "disclaimer", "all english",
    "all regional", "all tamil", "all telugu", "all hindi", "all epapers",
    "menu", "categories", "recent posts"
}


def clean_paper_title(raw_title: str) -> str:
    """Strips boilerplate labels, years, and download tags from post titles."""
    patterns = [
        r"(?i)\s*ePaper\s*Download\s*Daily\s*After\s*07:00\s*AM",
        r"(?i)\s*Today\s*Download\s*After\s*07:00\s*AM",
        r"(?i)\s*Free\s*Download\s*Daily\s*After\s*07:00\s*AM",
        r"(?i)\s*Newspaper\s*Today\s*Download.*$",
        r"(?i)\s*ePaper\s*(?:Hindi|Odia|Marathi|Bengali|English)\s*Download.*$",
        r"(?i)\s*ePaper\s*Free\s*Download.*$",
        r"(?i)\s*Free\s*Download.*$",
        r"(?i)\s*ePaper.*$",
        r"(?i)\s*PDF\s*Download.*$",
        r"\b202[0-9]\b",  # Removes dynamic year strings like 2025, 2026
    ]
    cleaned = raw_title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.strip()


def get_newspapers_by_language(language: str) -> dict:
    """Fetches newspapers across Page 1 and Page 2 for the requested category."""
    base_url = CATEGORY_BASES.get(language.lower(), CATEGORY_BASES["hindi"])
    
    # Generate Page 1 and Page 2 URLs
    urls_to_scrape = [
        base_url,
        f"{base_url.rstrip('/')}/page/2/"
    ]
    
    papers = {}

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25.0) as client:
        for page_url in urls_to_scrape:
            try:
                response = client.get(page_url)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                # Deconstruct navigation menus to isolate content posts
                for nav in soup.select("header, footer, nav, sidebar, .widget, #masthead, #site-navigation, .menu"):
                    nav.decompose()

                # Extract WordPress post title links
                headings = soup.select(
                    "article h2, article h3, .entry-title, h2.post-title, h3.post-title, .post-archive h2"
                )

                for heading in headings:
                    raw_title = heading.get_text(strip=True)
                    a_tag = heading if heading.name == "a" else heading.find("a")

                    if a_tag and "href" in a_tag.attrs:
                        post_url = a_tag["href"]
                        clean_name = clean_paper_title(raw_title)

                        # Filter out navigation, pagination, and invalid links
                        if (
                            clean_name
                            and len(clean_name) > 2
                            and clean_name.lower() not in NAV_IGNORE
                            and clean_name not in papers
                        ):
                            if not any(x in post_url for x in ["/category/", "/page/", "/tag/", "#"]):
                                papers[clean_name] = post_url

            except Exception as e:
                print(f"Scraper Error for {language} on {page_url}: {e}")

    return papers


def get_drive_link(post_url: str) -> str | None:
    """Extracts Google Drive attachment link from paper post page."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25.0) as client:
            response = client.get(post_url)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Search anchor tags for Google Drive links
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
