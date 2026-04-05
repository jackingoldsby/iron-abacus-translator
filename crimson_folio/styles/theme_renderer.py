"""Generate Kindle CSS from theme.json configuration."""

import json
from pathlib import Path


def render_css(theme_path: Path = None) -> str:
    """Render Kindle CSS from theme config.

    Args:
        theme_path: Path to theme.json. Defaults to config/theme.json.

    Returns:
        Complete CSS string.
    """
    if theme_path is None:
        theme_path = Path(__file__).parent.parent / "config" / "theme.json"

    with open(theme_path, "r", encoding="utf-8") as f:
        t = json.load(f)

    base = t["base"]
    tp = t["title_page"]
    fm = t["front_matter"]
    ch = t["chapter"]
    fn = t["footnotes"]
    vs = t["verse"]

    return f"""/* Generated from theme.json — do not edit directly */
/* Kindle Paperwhite / Oasis optimized, EPUB3 compatible */

/* === Base Typography === */
body {{
  font-family: {base['font_family']};
  line-height: {base['line_height']};
  margin: {base['margin']};
  orphans: 2;
  widows: 2;
  color: {base['text_color']};
}}

/* === Title Page === */
.title-page {{
  text-align: center;
  page-break-after: always;
  margin-top: {tp['margin_top']};
  padding: 0 1em;
}}

.title-page h1 {{
  font-size: {tp['title_font_size']};
  margin-bottom: 0.2em;
  font-weight: {tp['title_font_weight']};
  text-align: center;
  letter-spacing: {tp['title_letter_spacing']};
  line-height: {tp['title_line_height']};
}}

.title-page .title-chinese {{
  font-size: {tp['chinese_title_font_size']};
  margin-bottom: 1.2em;
  color: {tp['chinese_title_color']};
  letter-spacing: {tp['chinese_title_letter_spacing']};
}}

.title-page .series {{
  font-size: {tp['series_font_size']};
  font-style: {tp['series_style']};
  color: {tp['series_color']};
  margin-bottom: 0.3em;
  letter-spacing: 0.05em;
}}

.title-page .author {{
  font-size: {tp['author_font_size']};
  margin-top: {tp['author_margin_top']};
  letter-spacing: {tp['author_letter_spacing']};
}}

.title-page .author-chinese {{
  font-size: 1em;
  color: {tp['chinese_author_color']};
  margin-bottom: 0.5em;
}}

/* === Front Matter (Preface, Introduction) === */
.translators-preface {{
  page-break-after: always;
  margin-top: 2em;
  padding: 0 0.5em;
}}

.translators-preface h2 {{
  page-break-before: avoid;
  text-align: center;
  font-size: {fm['heading_font_size']};
  font-weight: {fm['heading_font_weight']};
  letter-spacing: {fm['heading_letter_spacing']};
  text-transform: {fm['heading_text_transform']};
  margin-bottom: 2em;
  padding-bottom: 0.5em;
  border-bottom: {fm['heading_border_bottom']};
}}

.translators-preface h3 {{
  font-size: {fm['subheading_font_size']};
  font-weight: bold;
  margin-top: 1.8em;
  margin-bottom: 0.8em;
  letter-spacing: 0.04em;
  color: {fm['subheading_color']};
}}

.translators-preface p {{
  text-indent: {fm['body_text_indent']};
  margin-bottom: 0.5em;
  line-height: {fm['body_line_height']};
  font-size: {fm['body_font_size']};
}}

.translators-preface p.first {{
  text-indent: 0;
}}

.translators-preface .signature {{
  text-indent: 0;
  margin-top: 2em;
  font-style: {fm['signature_style']};
  font-size: 1em;
  letter-spacing: 0.05em;
}}

.translators-preface .dateline {{
  text-indent: 0;
  font-style: italic;
  color: {fm['dateline_color']};
  font-size: {fm['dateline_font_size']};
}}

/* === Chapter Headings === */
h2 {{
  font-size: {ch['heading_font_size']};
  margin-top: {ch['heading_margin_top']};
  margin-bottom: {ch['heading_margin_bottom']};
  text-align: center;
  font-weight: bold;
  page-break-before: always;
}}

/* === Body Text === */
p {{
  text-indent: {ch['body_text_indent']};
  margin-bottom: {ch['body_margin_bottom']};
}}

/* === Verse / Poetry === */
.verse, blockquote.verse {{
  font-style: {vs['font_style']};
  margin-left: {vs['margin_left']};
  margin-top: {vs['margin_top']};
  margin-bottom: {vs['margin_bottom']};
  line-height: {vs['line_height']};
  text-indent: 0;
}}

/* === Footnotes (Kindle popup) === */
a[epub|type="noteref"] {{
  color: {fn['marker_color']};
  text-decoration: none;
  font-size: 0.85em;
  vertical-align: super;
}}

aside[epub|type="footnote"] {{
  font-size: {fn['popup_font_size']};
  background: {fn['popup_background']};
  border: {fn['popup_border']};
  padding: {fn['popup_padding']};
  margin: 0.5em 0;
}}

aside[epub|type="footnote"] strong {{
  font-weight: {fn['ideogram_weight']};
}}

aside[epub|type="footnote"] em {{
  font-style: {fn['pinyin_style']};
}}

/* === Table of Contents === */
nav[epub|type="toc"] h2 {{
  font-size: {t['toc']['heading_font_size']};
  text-align: center;
  letter-spacing: {t['toc']['heading_letter_spacing']};
  margin-bottom: 1.5em;
  padding-bottom: 0.5em;
  border-bottom: {t['toc']['heading_border_bottom']};
}}

nav[epub|type="toc"] ol {{
  list-style: none;
  padding-left: 0;
  margin: 0;
}}

nav[epub|type="toc"] li {{
  margin-bottom: 0.6em;
  line-height: {t['toc']['entry_line_height']};
  font-size: {t['toc']['entry_font_size']};
}}

nav[epub|type="toc"] a {{
  color: {t['toc']['entry_color']};
  text-decoration: none;
}}

/* === Glossary === */
.glossary {{
  page-break-before: always;
}}

.glossary h2 {{
  text-align: center;
  margin-bottom: 1.5em;
}}

.glossary-group {{
  margin-bottom: 1.5em;
}}

.glossary-group h3 {{
  font-size: 1.2em;
  border-bottom: 1px solid #ccc;
  padding-bottom: 0.3em;
  margin-bottom: 0.5em;
}}

.glossary-entry {{
  margin-bottom: 0.4em;
  text-indent: 0;
}}
"""
