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

# Multi-path fallbacks for each language to ensure pages are reached successfully
CATEGORY_URLS = {
    "hindi": [
        "https://dailyepaper.in/category/hindi-epaper/",
        "https://dailyepaper.in/category/hindi-epaper/page/2/",
        "https://dailyepaper.in/category/hindi-newspaper/",
        "https://dailyepaper.in/hindi-newspapers/",
    ],
    "english": [
        "https://dailyepaper.in/category/english-epaper/",
        "https://dailyepaper.in/category/english-epaper/page/2/",
        "https://dailyepaper.in/category/english-newspaper/",
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
        r"\b2It looks like an automated Telegram or WhatsApp bot failed to fetch the daily Hindi newspaper PDFs or links due to a temporary server issue or broken source link.

To fix this:

1. **Retry the command:** Reply with `/menu` or your bot's specific fetch command in the chat to restart the process.
2. **Check back later:** Newspaper fetching bots often rely on web scraping; if the source site is temporarily down or updating, the bot will fail until the site recovers.
3. **Alternative source:** If you need to read Hindi news right away, you can visit official news portals directly:
   * **Dainik Jagran:** [jagran.com](https://www.jagran.com)
   * **Dainik Bhaskar:** [bhaskar.com](https://www.bhaskar.com)
   * **Amar Ujala:** [amarujala.com](https://www.amarujala.com)
