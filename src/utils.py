"""Utility functions for the bluebook scraper"""

import logging
import sys
from src.config import LOGS_DIR, LOG_LEVEL, LOG_FORMAT, DATA_DIR
from datetime import datetime

def setup_logging(name="bluebook_scraper"):
    """Set up logging configuration"""

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    # Create formatters
    formatter = logging.Formatter(LOG_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"scraper_{timestamp}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def clean_text(text):
    """Clean and normalize text"""
    if not text:
        return ""
    return " ".join(text.strip().split())


def save_html(content, filename):
    """Save HTML content to file"""
    filepath = DATA_DIR / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath