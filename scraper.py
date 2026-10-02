import os
import re
import cloudscraper
import requests
from bs4 import BeautifulSoup

# Initialize cloudscraper session to bypass Cloudflare protection
scraper = cloudscraper.create_scraper(
    browser={
        "browser": "chrome",
        "platform": "windows",
        "desktop": True,
    }
)

CATEGORY_URLS = {
    "hindi": [
        "https://dailyepaper.in/category/hindi-epaper/",
        "https://dailyepaper.in/category/hindi-epaper/page/2/",
        "https://dailyepaper.in/hindi-newspapers/",
    ],
    "english": [
        "https://dailyepaper.in/category/english-epaper/",
        "https://dailyepaper.in/category/english-epaper/page/2/",
        "https://dailyepaper.in/english-newspapers/",
    ],
    "bengali": [
        "https://dailyepaper.in/category/bengali-epaper/",
        "https://dailyepaper.in/category/bengali-epaper/page/2/",
        "https://dailyepaper.in/bengali-newspapers/",
    ],
    "odia": [
        "https://dailyepaper.in/category/odia-epaper/",
        "https://dailyepaper.in/category/odia-epaper/page/2/",
        "https://dailyepaper.in/odia-newspapers/",
    ],
    "marathi": [
        "https://dailyepaper.in/category/marathi-epaper/",
        "https://dailyepaper.in/category/marathi-epaper/page/2/",
        "https://dailyepaper.in/marathi-newspapers/",
    ],
}

NAV_IGNORE = {
    "home", "english", "hindi", "tamil", "telugu", "marathi", "punjabi", "odia",
    "kannada", "malyalam", "bengali", "gujrati", "assam", "urdu", "about us",
    "dmca", "contact us", "privacy policy", "disclaimer", "all english",
    "all regional", "all tamil", "all telugu", "all hindi", "all epapers",
    "menu", "categories", "recent posts", "download pdf", "download"
}


def clean_paper_title(raw_title: str) -> str:
    """Strips download tags, dates, and boilerplate labels from paper titles."""
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


def get_newspapers_by_language(language: str) -> dict:
    """Scrapes newspapers using CloudScraper to bypass Cloudflare protection."""
    urls = CATEGORY_URLS.get(language.lower(), CATEGORY_URLS["hindi"])
    papers = {}

    for url in urls:
        try:
            response = scraper.get(url, timeout=20)
            if response.status_code != 200:
                print(f"Failed to fetch {url} - Status Code: {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove navigation, headers, footers, and sidebars
            for nav in soup.select("header, footer, nav, sidebar, .widget, #masthead, #site-navigation, .menu"):
                nav.decompose()

            # Target post headings & titles
            headings = soup.select(
                "article h2, article h3, .entry-title, h2.post-title, h3.post-title, .post-archive h2, article a"
            )

            for heading in headings:
                raw_title = heading.get_text(strip=True)
                a_tag = heading if heading.name == "a" else heading.find("a")

                if a_tag and "href" in a_tag.attrs:
                    post_url = a_tag["href"]
                    clean_name = clean_paper_title(raw_title)

                    if (
                        clean_name
                        and len(clean_name) > 2
                        and clean_name.lower() not in NAV_IGNORE
                        and clean_name not in papers
                    ):
                        if "dailyepaper.in/" in post_url and not any(
                            x in post_url for x in ["/category/", "/page/", "/tag/", "#", "contact", "privacy", "about", "dmca"]
                        ):
                            papers[clean_name] = post_url

        except Exception as e:
            print(f"Scraper Error for {language} at {url}: {e}")

    return papers


def get_drive_link(post_url: str) -> str | None:
    """Extracts Google Drive link from the paper's individual post page."""
    try:
        response = scraper.get(post_url, timeout=20)
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
        response = session.get(download_url, params={"id": file_id}, stream=True, timeout=30)

        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                response = session.get(
                    download_url,
                    params={"id": file_id, "confirm": value},
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
