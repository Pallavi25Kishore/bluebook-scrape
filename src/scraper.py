"""scraper for Bluebook content - india chapter"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import re

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
        chrome_options.add_argument("--headless")
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
            time.sleep(5)
            return self.driver.page_source
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def extract_document_metadata(self, soup):
        """Extract basic document metadata"""
        metadata = {
            'title': '',
            'subtitle': '',
            'number': '',
            'scraped_at': datetime.now().isoformat(),
            'source_url': TARGET_URL
        }

        # Extract title from h1
        title_section = soup.find('div', class_='text-black-100')
        if title_section:
            h1 = title_section.find('h1')
            if h1:
                spans = h1.find_all('span')
                if len(spans) >= 2:
                    metadata['number'] = clean_text(spans[0].get_text())
                    metadata['title'] = clean_text(spans[1].get_text())
                else:
                    metadata['title'] = clean_text(h1.get_text())

            h3 = title_section.find('h3')
            if h3:
                metadata['subtitle'] = clean_text(h3.get_text())

        return metadata

    def is_example_element(self, element):
        """Check if element contains citation examples"""
        if not element:
            return False

        # Check for example class
        if 'example' in element.get('class', []):
            return True

        # Check for visual indicators (arrow icons, etc.)
        if element.find('svg') and 'fill-blue-200' in str(element):
            return True

        return False

    def is_table_element(self, element):
        """Check if element is a table"""
        return element.name == 'table' or element.find('table') is not None

    def extract_table_data(self, table_element):
        """Extract table data as structured information"""
        if not table_element:
            return None

        table = table_element if table_element.name == 'table' else table_element.find('table')
        if not table:
            return None

        table_data = {
            'type': 'table',
            'headers': [],
            'rows': []
        }

        # Get headers
        header_row = table.find('tr')
        if header_row:
            headers = header_row.find_all(['th', 'td'])
            table_data['headers'] = [clean_text(h.get_text()) for h in headers]

        # Get all rows
        rows = table.find_all('tr')
        for row in rows[1:]:  # Skip header row
            cells = row.find_all(['td', 'th'])
            row_data = [clean_text(cell.get_text()) for cell in cells]
            if any(cell.strip() for cell in row_data):  # Only add non-empty rows
                table_data['rows'].append(row_data)

        return table_data

    def extract_examples_from_element(self, element):
        """Extract citation examples from an element"""
        examples = []

        if self.is_example_element(element):
            # This is an example element
            content_div = element.find('div', class_='wysiwyg')
            if content_div:
                example_text = clean_text(content_div.get_text())
                if example_text:
                    examples.append({
                        'text': example_text,
                        'type': 'citation_example'
                    })

        # Also check for example elements within this element
        example_divs = element.find_all('div', class_='example')
        for example_div in example_divs:
            content_div = example_div.find('div', class_='wysiwyg')
            if content_div:
                example_text = clean_text(content_div.get_text())
                if example_text:
                    examples.append({
                        'text': example_text,
                        'type': 'citation_example'
                    })

        return examples

    def extract_content_from_element(self, element):
        """Extract regular content (paragraphs, text) from an element"""
        content = []

        # Skip if this is an example or table
        if self.is_example_element(element) or self.is_table_element(element):
            return content

        # Extract paragraph content
        paragraphs = element.find_all('p', class_='font-serif')
        for p in paragraphs:
            text = clean_text(p.get_text())
            if text and len(text) > 10:  # Ignore very short text
                content.append(text)

        # If no paragraphs found, try to get text directly
        if not content:
            # Get text but skip examples and tables
            for child in element.children:
                if hasattr(child, 'name'):
                    if not self.is_example_element(child) and not self.is_table_element(child):
                        text = clean_text(child.get_text()) if hasattr(child, 'get_text') else clean_text(str(child))
                        if text and len(text) > 10:
                            content.append(text)
                elif isinstance(child, str):
                    text = clean_text(child)
                    if text and len(text) > 10:
                        content.append(text)

        return content

    def process_section_content(self, section_element, next_section_element=None):
        """Process all content between a section header and the next section"""
        section_data = {
            'content': [],
            'examples': [],
            'tables': [],
            'subsections': []
        }

        current = section_element
        while current:
            current = current.find_next_sibling()

            # Stop if we hit the next major section or end of content
            if not current:
                break
            if next_section_element and current == next_section_element:
                break
            if current.find('h2', class_='text-3xl'):
                break

            # Check for subsection header
            subsection_header = current.find('h2', class_='font-bold')
            if subsection_header:
                subsection_title = clean_text(subsection_header.get_text())
                if subsection_title:
                    # Process subsection content
                    subsection_data = self.process_subsection_content(current)
                    subsection_data['title'] = subsection_title
                    subsection_data['id'] = self.generate_id(subsection_title)
                    section_data['subsections'].append(subsection_data)
                continue

            # Extract different types of content
            content = self.extract_content_from_element(current)
            section_data['content'].extend(content)

            examples = self.extract_examples_from_element(current)
            section_data['examples'].extend(examples)

            if self.is_table_element(current):
                table_data = self.extract_table_data(current)
                if table_data:
                    section_data['tables'].append(table_data)

        return section_data

    def process_subsection_content(self, subsection_element):
        """Process content within a subsection"""
        subsection_data = {
            'content': [],
            'examples': [],
            'tables': []
        }

        # Get content from the subsection element itself
        content = self.extract_content_from_element(subsection_element)
        subsection_data['content'].extend(content)

        examples = self.extract_examples_from_element(subsection_element)
        subsection_data['examples'].extend(examples)

        if self.is_table_element(subsection_element):
            table_data = self.extract_table_data(subsection_element)
            if table_data:
                subsection_data['tables'].append(table_data)

        # Look at following siblings until next subsection or section
        current = subsection_element
        while current:
            current = current.find_next_sibling()

            if not current:
                break

            # Stop at next subsection or major section
            if current.find('h2', class_='font-bold') or current.find('h2', class_='text-3xl'):
                break

            content = self.extract_content_from_element(current)
            subsection_data['content'].extend(content)

            examples = self.extract_examples_from_element(current)
            subsection_data['examples'].extend(examples)

            if self.is_table_element(current):
                table_data = self.extract_table_data(current)
                if table_data:
                    subsection_data['tables'].append(table_data)

        return subsection_data

    def generate_id(self, title):
        """Generate a clean ID from title"""
        if not title:
            return 'untitled'

        # Clean and normalize
        id_str = title.lower()
        id_str = re.sub(r'[^\w\s-]', '', id_str)
        id_str = re.sub(r'[-\s]+', '_', id_str)
        return id_str.strip('_')

    def extract_introduction(self, soup):
        """Extract introduction content before first major section"""
        introduction = {
            'content': [],
            'examples': []
        }

        # Find the first major section
        first_section = soup.find('h2', class_='text-3xl')
        if not first_section:
            return introduction

        # Look for content before the first section
        main_content = soup.find('div', class_='leading-0')
        if not main_content:
            return introduction

        # Process elements before first section
        for element in main_content.find_all(['div', 'p']):
            # Stop when we reach the first section
            if element.find('h2', class_='text-3xl'):
                break

            content = self.extract_content_from_element(element)
            introduction['content'].extend(content)

            examples = self.extract_examples_from_element(element)
            introduction['examples'].extend(examples)

        return introduction

    def parse_content(self, html):
        """Parse HTML content into textbook-like structure"""
        soup = BeautifulSoup(html, 'lxml')
        self.logger.info("Parsing content in textbook format...")

        # Extract metadata
        metadata = self.extract_document_metadata(soup)

        # Initialize structure
        self.data = {
            'document': {
                **metadata,
                'introduction': self.extract_introduction(soup),
                'sections': []
            }
        }

        # Find all major sections (h2 with text-3xl class)
        section_headers = soup.find_all('h2', class_='text-3xl')
        self.logger.info(f"Found {len(section_headers)} major sections")

        for i, header in enumerate(section_headers):
            section_title = clean_text(header.get_text())
            if not section_title:
                continue

            self.logger.info(f"Processing section: {section_title}")

            # Get the next section for boundary detection
            next_header = section_headers[i + 1] if i + 1 < len(section_headers) else None

            # Process section content
            section_content = self.process_section_content(
                header.parent,
                next_header.parent if next_header else None
            )

            section_data = {
                'id': self.generate_id(section_title),
                'title': section_title,
                'order': i + 1,
                **section_content
            }

            self.data['document']['sections'].append(section_data)

        self.logger.info(f"Parsing complete with {len(self.data['document']['sections'])} sections")

    def save_results(self):
        """Save scraped data to files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = OUTPUT_DIR / f"bluebook_textbook_{timestamp}.json"

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Results saved to {json_file}")
        return json_file

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()
            self.logger.info("Chrome driver closed")

    def run(self):
        """Main scraping workflow"""
        self.logger.info("Starting generic textbook scraper...")

        try:
            self.setup_driver()
            html = self.fetch_page(TARGET_URL)

            if not html:
                self.logger.error("Failed to fetch page. Exiting.")
                return None

            save_html(html, "bluebook_textbook_rendered.html")
            self.parse_content(html)
            return self.save_results()

        finally:
            self.cleanup()


def main():
    scraper = BluebookScraper()
    return scraper.run()


if __name__ == "__main__":
    main()