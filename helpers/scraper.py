import requests
from bs4 import BeautifulSoup
import json
import os
from typing import List, Dict

class DysonScraper:
    def __init__(self):
        self.base_url = "https://www.dyson.in"
        self.urls = [
            "https://www.dyson.in/vacuum-cleaners/cord-free",
            "https://www.dyson.in/air-treatment/purifiers",
            "https://www.dyson.in/hair-care",
            "https://www.dyson.in/hair-care/airwrap",
            "https://www.dyson.in/hair-care/supersonic",
            "https://www.dyson.in/vacuum-cleaners/cordless/v15-detect/absolute",
            "https://www.dyson.in/vacuum-cleaners/cordless/v12-detect-slim-submarine/gold-and-yellow-and-chrome"
        ]
        self.data_file = "dyson_data.json"

    def scrape_page(self, url: str) -> Dict:
        print(f"Scraping {url}...")
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract main content
            # Dyson.in uses a lot of dynamic content, but we can target common sections
            title = soup.title.string if soup.title else url
            text_content = []
            
            # Target common Dyson product page elements
            for element in soup.find_all(['h1', 'h2', 'h3', 'p', 'li']):
                text = element.get_text(strip=True)
                if text and len(text) > 20: # Filter out short noise
                    text_content.append(text)
            
            return {
                "source": url,
                "title": title,
                "content": "\n".join(text_content)
            }
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None

    def scrape_all(self):
        all_data = []
        for url in self.urls:
            page_data = self.scrape_page(url)
            if page_data:
                all_data.append(page_data)
        
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        print(f"Scraped {len(all_data)} pages. Saved to {self.data_file}")

if __name__ == "__main__":
    scraper = DysonScraper()
    scraper.scrape_all()
