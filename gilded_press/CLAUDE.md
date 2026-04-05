# CLAUDE.md — Gilded Press (鍍金印)

**Gilded Press** is the KDP compliance product. It takes Crimson Folio EPUBs and cover images and produces KDP-ready packages for Kindle Direct Publishing submission.

## Architecture

```
gilded_press/
├── converters/
│   ├── epub_validator.py       # Validate EPUB against KDP specs
│   ├── cover_converter.py      # Convert cover to KDP specs (2560×1600 JPEG RGB)
│   └── metadata_injector.py    # Generate KDP metadata (BISAC, keywords, description)
├── validators/
│   └── content_checker.py      # AI disclosure check, copyright compliance
├── config/
│   └── defaults.py             # KDP specs, BISAC codes, defaults
├── cli/
│   └── prepare.py              # CLI entry point
└── tests/
```

## Commands

```bash
cd gilded_press

# Full KDP package
python -m cli.prepare --epub /path/to/book.epub --cover /path/to/cover.jpg

# With back cover
python -m cli.prepare --epub /path/to/book.epub --cover /path/to/cover.jpg --back-cover /path/to/back.jpg

# Validate only
python -m cli.prepare --epub /path/to/book.epub --validate-only

# Custom genre/keywords
python -m cli.prepare --epub /path/to/book.epub --genre gong\'an --keywords "Judge Bao" "detective"
```

## Output

```
kdp_package/
├── manuscript.epub     # Validated EPUB
├── cover.jpg           # 2560×1600 JPEG RGB
├── cover_back.jpg      # Back cover (for print)
├── metadata.json       # KDP upload form data
└── description.html    # Product page description
```

## KDP Specs

- Cover: 2560×1600 JPEG RGB, <50MB, 300 DPI, 1.6:1 ratio
- EPUB: valid structure, TOC, footnote popups
- Content: AI disclosure required, no copyright violations
- Metadata: BISAC codes, 7 keywords max, series info
