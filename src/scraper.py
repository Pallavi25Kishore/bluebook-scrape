"""Main scraper"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

from src.config import TARGET_URL, REQUEST_HEADERS, REQUEST_TIMEOUT, OUTPUT_DIR
from src.utils import setup_logging, clean_text, save_html


class BluebookScraper:
    def __init__(self):
        self.logger = setup_logging()
        self.driver = None
        self.data = {}

    def setup_driver(self):
        """Set up Chrome driver with options"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in background
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={REQUEST_HEADERS['User-Agent']}")

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.logger.info("Chrome driver initialized")

    def fetch_page(self, url):
        """Fetch page content using Selenium"""
        try:
            self.logger.info(f"Fetching: {url}")
            self.driver.get(url)

            # Wait for content to load (adjust selector as needed)
            wait = WebDriverWait(self.driver, 10)
            # Try to wait for main content
            time.sleep(3)  # Basic wait for JS to execute

            return self.driver.page_source
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def parse_content(self, html):
        """Parse HTML content"""
        soup = BeautifulSoup(html, 'lxml')

        self.logger.info("Parsing content...")

        # Print page title to verify content loaded
        title = soup.find('title')
        self.logger.info(f"Page title: {title.text if title else 'No title found'}")

        # Look for main content areas
        main_content = soup.find('main') or soup.find('div', {'id': 'main-content'})

        if main_content:
            self.logger.info("Found main content area")
        else:
            self.logger.warning("No main content area found")
            self.logger.info(f"Body preview: {str(soup.body)[:500]}...")

        # Placeholder structure
        self.data = {
            "title": "India Legal Citations",
            "sections": [],
            "metadata": {
                "source": TARGET_URL,
                "scraped_at": datetime.now().isoformat()
            }
        }

    def save_results(self):
        """Save scraped data to files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save as JSON
        json_file = OUTPUT_DIR / f"bluebook_india_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Results saved to {json_file}")

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()
            self.logger.info("Chrome driver closed")

    def run(self):
        """Main scraping workflow"""
        self.logger.info("Starting Bluebook scraper...")

        try:
            # Set up driver
            self.setup_driver()

            # Fetch page
            html = self.fetch_page(TARGET_URL)
            if not html:
                self.logger.error("Failed to fetch page. Exiting.")
                return

            # Save raw HTML
            save_html(html, "bluebook_india_rendered.html")

            # Parse content
            self.parse_content(html)

            # Save results
            self.save_results()

            self.logger.info("Scraping completed!")

        finally:
            # Always cleanup
            self.cleanup()


def main():
    scraper = BluebookScraper()
    scraper.run()


if __name__ == "__main__":
    main()