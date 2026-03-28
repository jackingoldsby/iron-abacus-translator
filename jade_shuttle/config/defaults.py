"""Default paths and constants."""

import re

DEFAULT_EPUB_DIR = "/Users/jacki/project_files/translation_project/for_parsing/"
DEFAULT_OUTPUT_DIR = "/Users/jacki/project_files/translation_project/wuxia_individual_files/"
DEFAULT_DB_PATH = "/Users/jacki/project_files/translation_project/db/works_translator.duckdb"

VOLUME_LETTERS = "abcdefghijklmnopqrstuvwxyz"

# Volume markers to strip when grouping multi-volume works
VOLUME_MARKERS = re.compile(
    r"[（(]?(?:上册?|中册?|下册?|第[一二三四五六七八九十\d]+册|卷[一二三四五六七八九十\d]+)[)）]?$"
)
