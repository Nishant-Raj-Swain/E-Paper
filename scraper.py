import re
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

async def get_newspapers_by_language(language: str):
    """Scrapes newspaper list for selected language."""
    url = f"https://dailyepaper.in/{language.lower()}-newspapers/"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            papers = []
            
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "-newspaper-free-download" in href:
                    name = a_tag.get_text(strip=True)
                    if name and {"name": name, "link": href} not in papers:
                        papers.append({"name": name, "link": href})
                        
            return papers[:10]  # Return top 10 results
        except Exception as e:
            print(f"Scraping Error: {e}")
            return []

async def get_drive_link(paper_url: str):
    """Fetches Google Drive link from newspaper detail page."""
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
        try:
            res = await client.get(paper_url)
            soup = BeautifulSoup(res.text, "html.parser")
            
            # Step 1: Find link containing 'download' or 'drive.google.com'
            target_link = None
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = a_tag.get_text(strip=True).lower()
                if "drive.google.com" in href:
                    return href
                if "download" in text and not target_link:
                    target_link = href
                    
            if not target_link:
                return None

            # Step 2: Follow wrapper/redirect link to get direct Google Drive link
            sub_res = await client.get(target_link)
            sub_soup = BeautifulSoup(sub_res.text, "html.parser")
            
            for a_tag in sub_soup.find_all("a", href=True):
                if "drive.google.com" in a_tag["href"]:
                    return a_tag["href"]
                    
            return target_link
        except Exception as e:
            print(f"Drive Link Error: {e}")
            return None
