"""Default paths and constants."""

DEFAULT_DB_PATH = "/Users/jacki/project_files/translation_project/db/works_translator.duckdb"
DEFAULT_OUTPUT_DIR = "/Users/jacki/project_files/translation_project/work_individual_files/"
DEFAULT_CACHE_DIR = "~/.cobalt_loom/cache/"

# Rate limits (seconds between requests)
WIKISOURCE_RATE_LIMIT = 2.0
CTEXT_RATE_LIMIT = 3.0

WIKISOURCE_BASE_URL = "https://zh.wikisource.org"
WIKISOURCE_API_URL = "https://zh.wikisource.org/w/api.php"

CTEXT_BASE_URL = "https://ctext.org"

USER_AGENT = "CobaltLoom/1.0 (Classical Chinese Novel Scraper; contact: jacki@example.com)"
