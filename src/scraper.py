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
from bs4 import Tag

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
      """Parse HTML content into structured format"""
      soup = BeautifulSoup(html, 'lxml')

      self.logger.info("Parsing content...")

      # Initialize data structure
      self.data = {
          "title": "India Legal Citations - Table T2.18",
          "metadata": {
              "source": TARGET_URL,
              "scraped_at": datetime.now().isoformat(),
              "bluebook_version": "v21"
          },
          "sections": []
      }

      # Find the main content container
      main_content = soup.find('div', class_=lambda x: x and 'leading-0' in str(x))

      if not main_content:
          self.logger.warning("Main content not found")
          return

      # Get the title
      title_h1 = main_content.find('h1')
      if title_h1:
          self.data["full_title"] = clean_text(title_h1.get_text())

      # Get intro paragraph
      intro_div = main_content.find('div', class_='relative')
      if intro_div and intro_div.find('p', class_='font-serif'):
          self.data["introduction"] = clean_text(intro_div.find('p', class_='font-serif').get_text())

      # Find all section containers - they have id starting with 'b-'
      section_divs = main_content.find_all('div', id=lambda x: x and x.startswith('b-'))

      self.logger.info(f"Found {len(section_divs)} section divs with b- IDs")

      for section_div in section_divs:
          # Find the h2 within this section div
          section_h2 = section_div.find('h2')
          if not section_h2:
              continue

          # Check if this is a main section (has specific classes)
          h2_classes = ' '.join(section_h2.get('class', []))

          # Main sections have 'text-3xl' class
          if 'text-3xl' in h2_classes:
              section_data = {
                  "title": clean_text(section_h2.get_text()),
                  "content": [],
                  "examples": [],
                  "tables": [],
                  "subsections": []
              }

              # Get all siblings after this section until the next section
              current = section_div
              while current:
                  current = current.find_next_sibling()

                  if not current:
                      break

                  # Stop if we hit another section div
                  if current.get('id', '').startswith('b-') and current.find('h2', class_='text-3xl'):
                      break

                  # Process different types of content
                  self._extract_from_element(current, section_data)

              self.data["sections"].append(section_data)
              self.logger.info(f"Processed section: {section_data['title']}")

      self.logger.info(f"Parsing complete with {len(self.data['sections'])} sections")

    def _extract_from_element(self, element, target_data):
      """Extract content from an element and add to target data structure"""
      if not isinstance(element, Tag):
          return

      # Check for subsection (div with b- id containing h2 with font-bold class)
      if element.get('id', '').startswith('b-'):
          subsection_h2 = element.find('h2', class_='font-bold')
          if subsection_h2:
              subsection_data = {
                  "title": clean_text(subsection_h2.get_text()),
                  "content": [],
                  "examples": [],
                  "tables": []
              }
              target_data["subsections"].append(subsection_data)
              # Update target to this subsection for nested content
              target_data = subsection_data

      # Extract paragraphs with font-serif class
      paragraphs = element.find_all('p', class_='font-serif')
      for p in paragraphs:
          text = clean_text(p.get_text())
          if text and len(text) > 5:
              # Determine where to add content
              if target_data.get("subsections"):
                  target_data["subsections"][-1]["content"].append(text)
              else:
                  target_data["content"].append(text)

      # Extract examples (divs with 'example' class)
      if 'example' in element.get('class', []):
          example_content = element.find('div', class_='wysiwyg')
          if example_content:
              example_text = clean_text(example_content.get_text())
              if example_text:
                  if target_data.get("subsections"):
                      target_data["subsections"][-1]["examples"].append(example_text)
                  else:
                      target_data["examples"].append(example_text)

      # Extract tables
      tables = element.find_all('table')
      for table in tables:
          table_data = self.parse_table(table)
          if table_data:
              if target_data.get("subsections"):
                  target_data["subsections"][-1]["tables"].append(table_data)
              else:
                  target_data["tables"].append(table_data)

      # Recursively check child elements
      if element.name == 'div':
          for child in element.children:
              if hasattr(child, 'name'):
                  self._extract_from_element(child, target_data)

    def parse_table(self, table):
        """Parse HTML table into structured data"""
        table_data = {
            "type": "table",
            "headers": [],
            "rows": []
        }

        # Get headers (if any)
        headers = table.find_all('th')
        for h in headers:
            table_data["headers"].append(clean_text(h.get_text()))

        # Get rows
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            row_data = []
            for cell in cells:
                row_data.append(clean_text(cell.get_text()))
            if row_data and not all(cell == "" for cell in row_data):
                table_data["rows"].append(row_data)

        return table_data if table_data["rows"] else None

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