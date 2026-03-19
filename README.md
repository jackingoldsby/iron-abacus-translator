# Book Processing Toolkit

Complete toolkit for processing books through the entire pipeline: JSON cleaning, AI-powered structuring, translation, footnote generation, and EPUB building.

## Vision: Full Book Processing Pipeline

```
Raw JSON → Clean → Structure → Translate → Footnotes → EPUB
```

### Current Status

✅ **JSON Cleaner** - Transform raw book JSON into discrete content blocks
✅ **Post-Processing Tools** - Chapter alignment, TOC restructuring, batch processing
✅ **Validation Tools** - Sanity checker, sequence validator, TOC alignment validator
✅ **Content Structurer** - AI-powered semantic analysis (narrative, dialogue, etc.)
🚧 **Translator** - Coming soon
🚧 **Footnote Generator** - Coming soon
🚧 **EPUB Builder** - Coming soon

## Quick Start

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# For development
pip install -r requirements-dev.txt
```

### Usage

#### 1. Clean JSON (No API Required)
```bash
python cli/clean.py --input book.json --output-dir ./output --language zh-Hant
```

#### 2. Post-Processing (No API Required)
```bash
# Fix chapter alignment
python utils/fix_chapter_alignment.py --input cleaned_book.json

# Restructure TOC for EPUB navigation
python utils/restructure_toc.py --input cleaned_book.json

# Or process entire batch (all stages)
python scripts/batch_process_books.py \
  --source-dir ./source_files \
  --output-dir ./output \
  --catalog-path ./works_translator.duckdb \
  --limit 10  # Test on first 10 files
```

#### 3. AI-Powered Structuring (Requires OPENAI_API_KEY)
```bash
export OPENAI_API_KEY=your-key-here
python cli/structure.py --input cleaned.json --output structured.json
```

#### 3. Translation (Coming Soon)
```bash
python cli/translate.py --input structured.json --output translated.json --target-lang en
```

#### 4. Footnotes (Coming Soon)
```bash
python cli/footnotes.py --input translated.json --output with_footnotes.json
```

#### 5. Build EPUB (Coming Soon)
```bash
python cli/build_epub.py --input with_footnotes.json --output book.epub
```

## Project Structure

```
book-processing-toolkit/
├── processors/              # Pipeline processors
│   ├── json_cleaner.py         ✅ Clean raw JSON
│   ├── content_structurer.py   ✅ AI semantic analysis
│   ├── translator.py           🚧 Translation (placeholder)
│   ├── footnote_generator.py   🚧 Footnotes (placeholder)
│   └── epub_builder.py         🚧 EPUB (placeholder)
│
├── utils/                   # Post-processing & utilities
│   ├── topology_analyzer.py         ✅ Structure analysis
│   ├── fix_chapter_alignment.py     ✅ Fix chapter titles
│   ├── restructure_toc.py           ✅ Structured TOC with links
│   ├── sanity_checker.py            ✅ Early validation with metadata
│   ├── catalog_metadata.py          ✅ Extract metadata from catalog DB
│   ├── chapter_sequence_validator.py ✅ Chinese chapter numbering validation
│   ├── toc_alignment_validator.py   ✅ OpenAI-powered TOC validation
│   ├── clients/                API client wrappers
│   │   ├── openai_client.py
│   │   └── anthropic_client.py
│   └── http/                   HTTP & web utilities
│       ├── http.py             Retry logic
│       └── parse.py            HTML parsing
│
├── scripts/                 # Batch processing
│   └── batch_process_books.py  ✅ Complete pipeline
│
├── ai/                      # AI assistant management
│   ├── assistant_manager.py    OpenAI assistant lifecycle
│   └── assistants/             Stored assistant configs
│
├── cli/                     # Command-line interfaces
│   ├── clean.py                JSON cleaning CLI
│   ├── structure.py            Structuring CLI
│   ├── translate.py            Translation CLI (placeholder)
│   ├── footnotes.py            Footnotes CLI (placeholder)
│   └── build_epub.py           EPUB CLI (placeholder)
│
├── schemas/                 # JSON schemas
├── docs/                    # Documentation
├── logs/                    # Processing logs & reports
├── tests/                   # Test suite
│
├── requirements.txt         # Core dependencies
├── requirements-dev.txt     # Dev dependencies
└── README.md               # This file
```

## Features

### JSON Cleaner (Implemented)

✅ **Discrete Content Blocks** - Each paragraph/heading is a separate object
✅ **EPUB IDs** - Every block has unique ID for internal linking
✅ **TOC Auto-Detection** - Identifies table of contents
✅ **Block Types** - heading_1-6, paragraph, text, list elements
✅ **Source References** - Maintains traceability
✅ **Fast Processing** - No API calls, instant results
✅ **Output Structure** - Auto-creates folders matching source structure

### Post-Processing Tools (Implemented)

✅ **Topology Analyzer** - Analyze JSON structure before processing
  - Token estimation for AI processing
  - Nesting depth analysis
  - Content location identification
  - No file modifications

✅ **Sanity Checker** - Early validation with metadata enrichment
  - Extracts metadata from catalog DuckDB database (author, title, volume)
  - Validates Chinese chapter numbering sequences
  - Detects missing, duplicate, or out-of-order chapters
  - Supports Chinese numerals: 一二三...十廿卅...百千
  - Runs after topology analysis, before cleaning

✅ **Chapter Alignment Fixer** - Fix EPUB metadata mismatches
  - Matches chapter titles to actual content headings
  - Supports 第N回 (hui/episode) and 第N章 (zhang/chapter) formats
  - Supports special numerals: 廿 (20), 卅 (30), 卌 (40)
  - Splits combined chapters
  - Handles duplicate headings
  - ⚠️ **Known Issue**: Assumes books start at Chapter 1 (some start at Chapter 2+)

✅ **TOC Restructurer** - Convert TOC to structured navigation
  - Parses text blobs into structured objects
  - Links each TOC entry to chapter by ID
  - Supports Chinese numerals including 廿/卅/卌
  - Handles blob format (space-separated entries)
  - Generates TOC from chapters when missing
  - Fuzzy matching for minor variants

✅ **TOC Alignment Validator** - OpenAI-powered semantic validation
  - Verifies TOC entries match actual chapter titles
  - Uses GPT-4o-mini for semantic comparison
  - Detects mismatches, typos, numbering errors
  - Provides confidence scores and suggested fixes
  - Batch processing to minimize API costs

✅ **Batch Processor** - Process entire dataset
  - **6-stage pipeline**: topology → sanity check → clean (+ metadata) → align → TOC → validate
  - Metadata enrichment from catalog database
  - Comprehensive error logging
  - Non-book file detection
  - Performance metrics
  - **Speed**: ~0.05s per file (deterministic stages), ~35s with AI validation
  - **Validation**: 100% TOC alignment on test set

### Content Structurer (Implemented)

✅ **Semantic Analysis** - Identifies narrative, dialogue, verse, etc.
✅ **OpenAI Assistants** - Uses AI for content classification
✅ **Batch Processing** - Multi-threaded with progress tracking
✅ **Retry Logic** - Robust error handling
✅ **Schema Validation** - Ensures output quality
✅ **Chunking** - Handles large texts (>4000 chars)

### Translator (Planned)

🚧 AI-powered translation
🚧 Multi-language support
🚧 Glossary integration
🚧 Format preservation

### Footnote Generator (Planned)

🚧 Cultural/historical notes
🚧 Pronunciation guides (pinyin)
🚧 Multiple citation styles
🚧 Global deduplication

### EPUB Builder (Planned)

🚧 EPUB 3.0 generation
🚧 Custom CSS styling
🚧 Cover image support
🚧 Navigation documents
🚧 Internal linking via block IDs

## Output Format

All processors maintain a consistent JSON structure:

```json
{
  "meta": {
    "title": "Book Title",
    "author": "Author Name",
    "work_number": "I0929",
    "volume": "a",
    "language": "zh-Hant",
    "schema_version": "2.0.0"
  },
  "structure": {
    "front_matter": {
      "toc": [...]
    },
    "body": {
      "chapters": [
        {
          "id": "chapter_0001",
          "title": "Chapter Title",
          "content_blocks": [
            {
              "id": "block_0000",
              "type": "heading_3",
              "content": "...",
              "epub_id": "heading_0"
            }
          ]
        }
      ]
    },
    "back_matter": {}
  }
}
```

## Environment Variables

```bash
# Required for AI-powered features
export OPENAI_API_KEY=your-openai-key

# Optional: Alternative AI provider
export ANTHROPIC_API_KEY=your-anthropic-key
```

## Development

### Run Tests
```bash
make test
# or
pytest
```

### Code Formatting
```bash
black processors ai utils cli
```

### Linting
```bash
flake8 processors ai utils cli
```

## Complete Processing Pipeline

The toolkit supports a comprehensive multi-stage pipeline for processing books:

```
┌─────────────────────────────────────────────────────────────────┐
│ Stage 1: Topology Analysis (utils/topology_analyzer.py)        │
├─────────────────────────────────────────────────────────────────┤
│ • Analyze JSON structure without modifications                 │
│ • Estimate tokens for AI processing                            │
│ • Identify content locations and nesting depth                 │
│ • Deterministic, no API calls                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 2: Sanity Check (utils/sanity_checker.py)               │
├─────────────────────────────────────────────────────────────────┤
│ • Extract metadata from catalog database (work_number, title,  │
│   author, volume)                                              │
│ • Validate Chinese chapter numbering sequences                 │
│ • Detect missing, duplicate, or out-of-order chapters         │
│ • Supports 一二三...十廿卅卌...百千 numerals                   │
│ • Non-fatal validation (continues on errors)                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 3: JSON Cleaning (processors/json_cleaner.py)            │
├─────────────────────────────────────────────────────────────────┤
│ • Extract discrete content blocks from nested structures       │
│ • Generate block IDs (block_0000, block_0001...)              │
│ • Create EPUB IDs (heading_0, para_1, text_2...)              │
│ • Auto-detect TOC                                              │
│ • Enrich with catalog metadata (work_number, title, author)   │
│ • Deterministic, no API calls                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 4: Chapter Alignment (utils/fix_chapter_alignment.py)    │
├─────────────────────────────────────────────────────────────────┤
│ • Fix EPUB metadata mismatches                                 │
│ • Match titles to actual content headings                      │
│ • Support 第N回 and 第N章 formats                              │
│ • Support special numerals: 廿 (20), 卅 (30), 卌 (40)         │
│ • Split combined chapters                                      │
│ • Deterministic, pattern-based                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 5: TOC Restructuring (utils/restructure_toc.py)          │
├─────────────────────────────────────────────────────────────────┤
│ • Convert TOC from text blob to structured list                │
│ • Create chapter references for EPUB navigation                │
│ • Handle blob format (space-separated entries)                 │
│ • Generate TOC from chapters when missing                      │
│ • Support Chinese numerals including 廿/卅/卌                  │
│ • Fuzzy matching for variants                                  │
│ • Deterministic, pattern-based                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 6: Validation (utils/toc_alignment_validator.py)        │
├─────────────────────────────────────────────────────────────────┤
│ • Verify TOC structure and chapter consistency                 │
│ • OpenAI-powered semantic TOC/chapter title matching           │
│ • Detect mismatches, typos, numbering errors                   │
│ • Batch processing (20 pairs per request)                      │
│ • Confidence scores and suggested fixes                        │
│ • Requires OPENAI_API_KEY                                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Future Stages (Coming Soon)                                    │
├─────────────────────────────────────────────────────────────────┤
│ • AI Structuring - Semantic classification (optional)          │
│ • Translation (AI-powered)                                     │
│ • Footnote generation (cultural/historical notes)             │
│ • EPUB 3.0 generation with navigation links                   │
└─────────────────────────────────────────────────────────────────┘
```

### Batch Processing

Process entire datasets with comprehensive logging:

```bash
# Process all files in directory
python scripts/batch_process_books.py \
  --source-dir /path/to/source_files \
  --output-dir /path/to/output \
  --log-dir ./logs

# Test on subset
python scripts/batch_process_books.py \
  --source-dir /path/to/source_files \
  --output-dir /path/to/output \
  --limit 10
```

**Output**: Detailed JSON report with:
- Stage-by-stage success rates
- Issue categorization (topology errors, TOC mismatches, etc.)
- Performance metrics (time per file, tokens estimated)
- File-level results with warnings and errors

**Performance** (tested on 640 wuxia book files):
- Average: 0.05s per file
- Total: ~30s for 640 files
- Success rate: 90% topology, 100% TOC processing

### Edge Cases Handled

The post-processing pipeline has been tested and optimized for common edge cases:

1. **第N章 vs 第N回 formats** - Both traditional (回/hui) and modern (章/zhang) chapter numbering supported
2. **Special Chinese numerals** - Full support for 廿 (20), 卅 (30), 卌 (40) in chapter parsing, TOC restructuring, and validation
3. **TOC blob parsing** - Handles space-separated TOC entries on one line without over-splitting
4. **Missing TOC** - Automatically generates structured TOC from chapter titles when source TOC absent
5. **Non-book files** - Detects and skips metadata files (missing 'chapters' key)
6. **Title/content mismatches** - Fixes EPUB metadata that doesn't match actual chapter headings
7. **Combined chapters** - Splits when multiple headings found in single chapter
8. **Fuzzy matching** - Handles minor character variants (薄/泊, 到/至) in TOC entries
9. **Nonstandard chapter starts** - Detects books that start at Chapter 2+ instead of Chapter 1

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Architecture guide for Claude Code
- **[docs/AI_ASSISTANT_GUIDE.md](docs/AI_ASSISTANT_GUIDE.md)** - OpenAI assistant management
- **[docs/POST_PROCESSING_GUIDE.md](docs/POST_PROCESSING_GUIDE.md)** - Complete post-processing workflow
- **[logs/FIXES_IMPLEMENTED.md](logs/FIXES_IMPLEMENTED.md)** - Implementation details and test results
- **[logs/EDGE_CASES_INVESTIGATION.md](logs/EDGE_CASES_INVESTIGATION.md)** - Edge case analysis and solutions

## Roadmap

### v0.2.0 (Current)
- ✅ Restructured as toolkit
- ✅ Created placeholders for future processors
- ✅ Proper package structure
- ✅ CLI entry points

### v0.3.0 (Next)
- 🚧 Implement translator processor
- 🚧 Add language detection improvements
- 🚧 Glossary/terminology support

### v0.4.0 (Future)
- 🚧 Implement footnote generator
- 🚧 Citation style support (Chicago, MLA, APA)
- 🚧 Cultural/historical annotations

### v0.5.0 (Future)
- 🚧 Implement EPUB builder
- 🚧 Custom CSS themes
- 🚧 Cover image integration

## Contributing

This project is under active development. Contributions welcome!

## License

MIT
