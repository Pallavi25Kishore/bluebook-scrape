"""Sequential order scraper that preserves exact page flow"""

"""
BLUEBOOK SCRAPER JSON SCHEMA

{
  "document": {
    "title": "India",                    // Document title
    "subtitle": "(Common Law)",          // Document subtitle
    "number": "T2.18",                   // Table number
    "scraped_at": "ISO_TIMESTAMP",       // When scraped
    "source_url": "https://...",         // Original URL

    "introduction": [                    // Content before first section
      {
        "type": "content",
        "paragraphs": ["Introduction text..."]
      }
    ],

    "content": [                           // Main content in reading order
      {
        "type": "main_section",          // Major section (Cases, Legislation, etc.)
        "title": "Cases",
        "id": "cases",
        "content": [                     // Sequential array - maintains page order
          {
            "type": "content",           // Regular paragraph text
            "paragraphs": ["Citation format: ..."]
          },
          {
            "type": "example",           // Citation examples (blue arrows)
            "citation": "Union Carbide v. India, AIR 1990..."
          },
          {
            "type": "table",             // Tables in exact position
            "headers": ["Reporter", "Date Range", "Format"],
            "rows": [["All India Reporter", "1914–date", "..."]]
          },
          {
            "type": "subsection",        // Nested subsections
            "title": "Statutes and Ordinances",
            "id": "statutes_and_ordinances",
            "content": [                 // Same sequential structure
              {"type": "content", "paragraphs": [...]},
              {"type": "example", "citation": "..."},
              {"type": "table", "headers": [...], "rows": [...]}
            ]
          }
        ]
      }
    ]
  }
}

"""

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

    def extract_formatted_text(self, paragraph):
        """Extract clean text without formatting markers"""
        if not paragraph:
            return ""

        result = clean_text(paragraph.get_text())
        return result

    def classify_element_type(self, element):
        """Classify what type of content element this is"""
        if not element or not hasattr(element, 'name'):
            return 'unknown'

        # Check for example elements (with blue arrow icon)
        if 'example' in element.get('class', []):
            return 'example'
        if element.find('svg') and 'fill-blue-200' in str(element):
            return 'example'

        # Check for tables
        if element.name == 'table' or element.find('table'):
            return 'table'

        # Check for headers
        h2 = element.find('h2')
        if h2:
            if 'text-3xl' in h2.get('class', []):
                return 'main_header'
            elif 'font-bold' in h2.get('class', []):
                # Check if this is a real subheader or just bold text in content
                h2_classes = ' '.join(h2.get('class', []))
                h2_text = clean_text(h2.get_text())

                # Real subheaders have specific patterns:
                # 1. ALL CAPS text (like "STATUTES AND ORDINANCES")
                # 2. Contains 'uppercase' or 'text-xxxxs' classes
                if (h2_text.isupper() or
                    'uppercase' in h2_classes or
                    'text-xxxxs' in h2_classes or
                    'tracking-widest' in h2_classes):
                    return 'sub_header'
                else:
                    # This is just bold text within content, not a header
                    return 'content'

        # Check for content paragraphs
        if element.find('p', class_='font-serif'):
            return 'content'

        # Check if it contains text content
        text = clean_text(element.get_text()) if hasattr(element, 'get_text') else ''
        if text and len(text) > 5:
            return 'content'

        return 'unknown'

    def extract_content_data(self, element, element_type):
        """Extract data based on element type"""
        if element_type == 'main_header':
            h2 = element.find('h2', class_='text-3xl')
            return {
                'type': 'main_header',
                'title': clean_text(h2.get_text()) if h2 else '',
                'id': self.generate_id(clean_text(h2.get_text())) if h2 else ''
            }

        elif element_type == 'sub_header':
            h2 = element.find('h2', class_='font-bold')
            title = clean_text(h2.get_text()) if h2 else ''
            if title.isupper():
                title = title.title()
            return {
                'type': 'sub_header',
                'title': title,
                'id': self.generate_id(title)
            }

        elif element_type == 'content':
            # Extract all text content
            paragraphs = []

            # Try to get from font-serif paragraphs first
            serif_paras = element.find_all('p', class_='font-serif')
            if serif_paras:
                for p in serif_paras:
                    text = clean_text(p.get_text())
                    if text and len(text) > 10:
                        paragraphs.append(text)

            # If no serif paragraphs found, try other paragraph types
            if not paragraphs:
                all_paras = element.find_all('p')
                for p in all_paras:
                    text = clean_text(p.get_text())
                    if text and len(text) > 10:
                        paragraphs.append(text)

            # If still no paragraphs, get direct text from element
            if not paragraphs:
                # Skip if this element contains examples or tables to avoid duplication
                if not element.find('div', class_='example') and not element.find('table'):
                    text = clean_text(element.get_text())
                    if text and len(text) > 10:
                        paragraphs.append(text)

            # Only return if we have actual content
            if paragraphs:
                return {
                    'type': 'content',
                    'paragraphs': paragraphs
                }
            return None

        elif element_type == 'example':
            # Extract citation example
            content_div = element.find('div', class_='wysiwyg')
            if content_div:
                citation = clean_text(content_div.get_text())
                return {
                    'type': 'example',
                    'citation': citation
                }
            return None

        elif element_type == 'table':
            # Extract table data
            table = element if element.name == 'table' else element.find('table')
            if not table:
                return None

            table_data = {
                'type': 'table',
                'headers': [],
                'rows': []
            }

            # Get headers from first row
            first_row = table.find('tr')
            if first_row:
                headers = first_row.find_all(['th', 'td'])
                table_data['headers'] = [clean_text(h.get_text()) for h in headers]

            # Get all data rows
            rows = table.find_all('tr')[1:]  # Skip header row
            for row in rows:
                cells = row.find_all(['td', 'th'])
                row_data = [clean_text(cell.get_text()) for cell in cells]
                if any(cell.strip() for cell in row_data):  # Only non-empty rows
                    table_data['rows'].append(row_data)

            return table_data

        return None

    def generate_id(self, title):
        """Generate a clean ID from title"""
        if not title:
            return 'untitled'

        id_str = title.lower()
        id_str = re.sub(r'[^\w\s-]', '', id_str)
        id_str = re.sub(r'[-\s]+', '_', id_str)
        return id_str.strip('_')

    def process_sequential_content(self, main_content_div):
        """Process content in sequential order as it appears on page"""
        content_structure = []
        current_section = None
        current_subsection = None

        # Find all major section headers first to establish boundaries
        section_headers = main_content_div.find_all('h2', class_='text-3xl')
        section_boundaries = {}

        for i, header in enumerate(section_headers):
            section_title = clean_text(header.get_text())
            next_header = section_headers[i + 1] if i + 1 < len(section_headers) else None
            section_boundaries[section_title] = {
                'start': header.parent,
                'end': next_header.parent if next_header else None
            }

        self.logger.info(f"Found {len(section_headers)} major sections")

        for i, header in enumerate(section_headers):
            section_title = clean_text(header.get_text())
            if not section_title:
                continue

            self.logger.info(f"Processing section: {section_title}")

            # Start new main section
            current_section = {
                'type': 'main_section',
                'title': section_title,
                'id': self.generate_id(section_title),
                'content': []  # This will be the sequential array
            }

            # Process all elements after this section header until next section
            current_element = header.parent
            section_end = section_boundaries[section_title]['end']

            while current_element:
                current_element = current_element.find_next_sibling()

                # Stop if we hit the next section or end of content
                if not current_element or current_element == section_end:
                    break

                # Process this element in order
                self.process_element_sequentially(current_element, current_section)

            content_structure.append(current_section)

        return content_structure

    def process_element_sequentially(self, element, current_section):
        """Process a single element and add it to the sequential content array"""
        element_type = self.classify_element_type(element)

        if element_type == 'unknown':
            return

        # Check if this is a subsection header
        if element_type == 'sub_header':
            extracted_data = self.extract_content_data(element, element_type)
            if extracted_data:
                # Start new subsection
                subsection = {
                    'type': 'subsection',
                    'title': extracted_data['title'],
                    'id': extracted_data['id'],
                    'content': []  # Sequential array for subsection content
                }
                current_section['content'].append(subsection)
            return

        # Extract the content data
        extracted_data = self.extract_content_data(element, element_type)
        if not extracted_data:
            # Debug: log when content extraction fails
            if element_type == 'content':
                element_text = clean_text(element.get_text())[:100]
                self.logger.debug(f"Content extraction failed for element with text: {element_text}")
            return

        # Debug: log successful extractions
        if element_type == 'content' and extracted_data.get('paragraphs'):
            self.logger.debug(f"Extracted {len(extracted_data['paragraphs'])} paragraphs")

        # Add to the appropriate sequential content array
        # If we have subsections, add to the last subsection, otherwise add to main section
        if (current_section['content'] and
            current_section['content'][-1].get('type') == 'subsection'):
            # Add to last subsection
            current_section['content'][-1]['content'].append(extracted_data)
        else:
            # Add directly to main section
            current_section['content'].append(extracted_data)

    def extract_introduction_content(self, soup):
        """Extract introduction content before first main section"""
        introduction_content = []

        # Find main content area
        main_content = soup.find('div', class_='leading-0')
        if not main_content:
            return introduction_content

        # Find first main section header
        first_section = main_content.find('h2', class_='text-3xl')

        if first_section:
            # Get all elements before first section
            for element in main_content.find_all(['div', 'p']):
                # Stop when we reach first section
                if element == first_section.parent or element.find('h2', class_='text-3xl'):
                    break

                element_type = self.classify_element_type(element)
                if element_type in ['content', 'example']:
                    extracted_data = self.extract_content_data(element, element_type)
                    if extracted_data:
                        introduction_content.append(extracted_data)

        return introduction_content

    def parse_content(self, html):
        """Parse HTML content maintaining sequential order"""
        soup = BeautifulSoup(html, 'lxml')
        self.logger.info("Parsing content in sequential order...")

        # Extract metadata
        metadata = self.extract_document_metadata(soup)

        # Find main content area
        main_content = soup.find('div', class_='leading-0')
        if not main_content:
            self.logger.error("Could not find main content area")
            return

        # Extract introduction
        introduction = self.extract_introduction_content(soup)

        # Process all content sequentially
        sequential_content = self.process_sequential_content(main_content)

        # Build final structure
        self.data = {
            'document': {
                **metadata,
                'introduction': introduction,
                'content': sequential_content
            }
        }

        self.logger.info(f"Parsing complete with {len(sequential_content)} main sections")

    def save_results(self):
        """Save scraped data to files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = OUTPUT_DIR / f"bluebook_sequential_{timestamp}.json"

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
        self.logger.info("Starting sequential textbook scraper...")

        try:
            self.setup_driver()
            html = self.fetch_page(TARGET_URL)

            if not html:
                self.logger.error("Failed to fetch page. Exiting.")
                return None

            save_html(html, "bluebook_sequential_rendered.html")
            self.parse_content(html)
            return self.save_results()

        finally:
            self.cleanup()


def main():
    scraper = BluebookScraper()
    return scraper.run()


if __name__ == "__main__":
    main()