#!/usr/bin/env python3
"""
Wuxia Book Discovery & Translation Manager

Streamlit app for browsing the wuxia catalog, viewing book details,
and launching/monitoring translation jobs.

Usage:
    streamlit run app_discover.py
"""

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st
import pandas as pd

# Add iron_abacus_translator to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iron_abacus_translator"))

# --- Config ---
from utils.environment_config import get_or_create_config as _get_config
_env = _get_config()
CATALOG_DB = _env.catalog_path
CLEANED_DIR = _env.source_dir
TRANSLATION_OUTPUT = _env.output_dir
PROJECT_ROOT = Path(__file__).parent


# --- Database ---
@st.cache_data(ttl=60)
def load_catalog():
    """Load the full catalog with consensus translations, series, and URL info."""
    from utils.db import connect_catalog, is_duckdb
    conn = connect_catalog()
    _is_duck = is_duckdb(conn)

    # GROUP_CONCAT (SQLite) vs string_agg (DuckDB)
    _agg = "string_agg(DISTINCT {col}, ',')" if _is_duck else "GROUP_CONCAT(DISTINCT {col})"
    vol_agg = _agg.format(col="wf.volume")
    fn_agg = _agg.format(col="wf.filename")
    dir_agg = _agg.format(col="wf.directory_name")

    query = f"""
        SELECT
            w.work_id,
            w.work_number,
            w.title_chinese,
            w.author_chinese,
            w.title_english,
            w.author_english,
            w.category_english,
            w.summary,
            w.work_link,
            w.publication_year,
            wct.consensus_title_english,
            wct.consensus_author_english,
            {vol_agg} as volumes,
            COUNT(DISTINCT wf.file_id) as file_count,
            SUM(wf.character_count) as total_chars,
            {fn_agg} as filenames,
            {dir_agg} as directories
        FROM works w
        LEFT JOIN works_consensus_translations wct ON w.work_id = wct.work_id
        LEFT JOIN work_files wf ON w.work_id = wf.work_id
        GROUP BY w.work_id, w.work_number, w.title_chinese, w.author_chinese,
                 w.title_english, w.author_english, w.category_english,
                 w.summary, w.work_link, w.publication_year,
                 wct.consensus_title_english, wct.consensus_author_english
        ORDER BY w.author_chinese, w.title_chinese
    """

    if _is_duck:
        df = conn.execute(query).fetchdf()
    else:
        df = pd.read_sql_query(query, conn)

    # Load series data
    _series_q = """
        SELECT ws.work_id, s.name_english as series_name, s.name_chinese as series_name_zh,
               s.series_type, ws.order_in_series, s.series_id
        FROM work_series ws
        JOIN series s ON ws.series_id = s.series_id
    """
    series_df = conn.execute(_series_q).fetchdf() if _is_duck else pd.read_sql_query(_series_q, conn)

    # Build work_id -> series info mapping
    series_map = {}
    for _, srow in series_df.iterrows():
        wid = srow["work_id"]
        if wid not in series_map:
            series_map[wid] = []
        series_map[wid].append({
            "name": srow["series_name"],
            "name_zh": srow.get("series_name_zh", ""),
            "type": srow["series_type"],
            "order": srow["order_in_series"],
            "series_id": srow["series_id"],
        })

    # Load work URLs
    _urls_q = "SELECT work_id, url, url_type FROM work_urls"
    urls_df = conn.execute(_urls_q).fetchdf() if _is_duck else pd.read_sql_query(_urls_q, conn)
    url_map = {}
    for _, urow in urls_df.iterrows():
        wid = urow["work_id"]
        if wid not in url_map:
            url_map[wid] = []
        url_map[wid].append(urow["url"])

    # Load author metadata
    author_df = pd.read_sql_query("""
        SELECT name_chinese, name_english, wikipedia_url, birth_year, death_year, description
        FROM authors
    """, conn)
    author_meta = {r["name_chinese"]: r for _, r in author_df.iterrows()}

    conn.close()

    # Prefer consensus translations, fall back to work-level
    df["title_en"] = df["consensus_title_english"].fillna(df["title_english"]).fillna("")
    df["author_en"] = df["consensus_author_english"].fillna(df["author_english"]).fillna("")

    # Display column: "English Name (中文)" or just "中文" if no English
    df["author_display"] = df.apply(
        lambda r: f"{r['author_en']} ({r['author_chinese']})"
        if r["author_en"] else r["author_chinese"],
        axis=1,
    )

    # Add series info
    df["series_name"] = df["work_id"].map(
        lambda wid: series_map.get(wid, [{}])[0].get("name", "") if wid in series_map else ""
    )
    df["series_order"] = df["work_id"].map(
        lambda wid: series_map.get(wid, [{}])[0].get("order", 0) if wid in series_map else 0
    )
    df["series_type"] = df["work_id"].map(
        lambda wid: series_map.get(wid, [{}])[0].get("type", "") if wid in series_map else ""
    )
    df["series_name_zh"] = df["work_id"].map(
        lambda wid: series_map.get(wid, [{}])[0].get("name_zh", "") if wid in series_map else ""
    )

    # Add Wikipedia URL (first URL per work)
    df["wiki_url"] = df["work_id"].map(
        lambda wid: url_map.get(wid, [""])[0]
    )

    # Add author Wikipedia URL
    df["author_wiki_url"] = df["author_chinese"].map(
        lambda ac: author_meta.get(ac, {}).get("wikipedia_url", "") or ""
    )

    return df


@st.cache_data(ttl=300)
def load_series_list():
    """Load all series with their work counts."""
    from utils.db import connect_catalog, is_duckdb
    conn = connect_catalog(CATALOG_DB)
    _duck = is_duckdb(conn)
    query = """
        SELECT s.series_id, s.name_english, s.name_chinese, s.author_chinese,
               s.series_type, s.historical_period, s.description,
               COUNT(ws.work_id) as work_count
        FROM series s
        LEFT JOIN work_series ws ON s.series_id = ws.series_id
        GROUP BY s.series_id
        ORDER BY s.author_chinese, s.name_english
    """
    df = conn.execute(query).fetchdf() if _duck else pd.read_sql_query(query, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def get_cleaned_files(work_number):
    """Find cleaned JSON files for a work."""
    results = []
    for d in CLEANED_DIR.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob(f"cleaned_{work_number}*.json"):
            results.append(str(f))
    return sorted(results)


@st.cache_data(ttl=300)
def get_book_stats(json_path):
    """Get chapter/block counts from a cleaned JSON file."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
        total_blocks = sum(len(ch.get("content_blocks", [])) for ch in chapters)
        total_chars = sum(
            len(b.get("content", ""))
            for ch in chapters
            for b in ch.get("content_blocks", [])
        )
        return {
            "chapters": len(chapters),
            "blocks": total_blocks,
            "chars": total_chars,
        }
    except Exception:
        return None


@st.cache_data(ttl=600)
def estimate_work_size(work_number, file_count, db_char_count):
    """Estimate character count for a work. Tries cleaned files first, falls back to averages."""
    # Try to get real count from cleaned files
    cleaned = get_cleaned_files(work_number)
    if cleaned:
        total = 0
        for cf in cleaned:
            stats = get_book_stats(cf)
            if stats:
                total += stats["chars"]
        if total > 0:
            return total, False  # (chars, is_estimate)

    # Use DB count if available
    if db_char_count and db_char_count > 0:
        return int(db_char_count), False

    # Estimate: avg ~350,000 chars per volume for wuxia novels
    AVG_CHARS_PER_VOLUME = 350_000
    vols = max(1, file_count) if file_count else 1
    return vols * AVG_CHARS_PER_VOLUME, True


def get_translation_status(work_number):
    """Check if translation outputs exist for a work."""
    results = []
    if TRANSLATION_OUTPUT.exists():
        for d in TRANSLATION_OUTPUT.iterdir():
            if not d.is_dir():
                continue
            for f in d.glob(f"*{work_number}*_cleaned.json"):
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    chapters = data.get("structure", {}).get("body", {}).get("chapters", [])
                    fn_count = sum(
                        len(b.get("footnotes", []))
                        for ch in chapters
                        for b in ch.get("content_blocks", [])
                    )
                    translated_blocks = sum(
                        1 for ch in chapters
                        for b in ch.get("content_blocks", [])
                        if b.get("translated_content")
                    )
                    results.append({
                        "path": str(f),
                        "dir": d.name,
                        "chapters": len(chapters),
                        "translated_blocks": translated_blocks,
                        "footnotes": fn_count,
                    })
                except Exception:
                    results.append({"path": str(f), "dir": d.name, "error": True})
    return results


def get_epub_files(work_number):
    """Find EPUB files for a work."""
    results = []
    if TRANSLATION_OUTPUT.exists():
        for f in TRANSLATION_OUTPUT.rglob(f"*{work_number}*.epub"):
            results.append(f)
    return sorted(results)


# --- Approval tracking ---
APPROVAL_FILE = PROJECT_ROOT / "translation_data" / "approvals.json"


def load_approvals():
    """Load translation approval status."""
    if APPROVAL_FILE.exists():
        with open(APPROVAL_FILE) as f:
            return json.load(f)
    return {}


def save_approval(work_number, status, notes=""):
    """Save approval status for a work. status: 'approved', 'rejected', 'needs_review'"""
    approvals = load_approvals()
    approvals[work_number] = {"status": status, "notes": notes}
    APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(APPROVAL_FILE, "w") as f:
        json.dump(approvals, f, indent=2)


@st.cache_data(ttl=30)
def get_translation_summary_all():
    """Get a quick translation status for all works (for browse table)."""
    summary = {}
    if TRANSLATION_OUTPUT.exists():
        for d in TRANSLATION_OUTPUT.iterdir():
            if not d.is_dir():
                continue
            for f in d.glob("*_cleaned.json"):
                # Extract work number from filename
                name = f.stem
                for part in name.split("_"):
                    if part and part[0] in "DI" and len(part) >= 2:
                        wn = part.rstrip("abcdefgh")
                        if wn not in summary:
                            summary[wn] = {"files": 0, "chapters": 0, "en_chars": 0}
                        summary[wn]["files"] += 1
                        try:
                            with open(f) as fh:
                                data = json.load(fh)
                            chs = data.get("structure", {}).get("body", {}).get("chapters", [])
                            summary[wn]["chapters"] += len(chs)
                            for ch in chs:
                                for b in ch.get("content_blocks", []):
                                    tc = b.get("translated_content", "")
                                    if tc:
                                        summary[wn]["en_chars"] += len(tc)
                        except Exception:
                            pass
                        break

    # Add total source chapter counts from cleaned files
    for wn in summary:
        cleaned = get_cleaned_files(wn)
        total_src = 0
        for cf in cleaned:
            stats = get_book_stats(cf)
            if stats:
                total_src += stats["chapters"]
        summary[wn]["total_chapters"] = total_src

    return summary


# --- UI ---
st.set_page_config(
    page_title="Wuxia Translation Manager",
    page_icon="⚔️",
    layout="wide",
)

st.title("Wuxia Book Discovery & Translation")

# Left-align button text in the browse table
st.markdown("""
<style>
button[kind="secondary"] {
    text-align: left !important;
    justify-content: flex-start !important;
}
button[kind="secondary"] p,
button[kind="secondary"] span,
button[kind="secondary"] div {
    text-align: left !important;
}
div.stButton > button,
div[data-testid="stButton"] > button {
    text-align: left !important;
    justify-content: flex-start !important;
}
div.stButton > button > div,
div[data-testid="stButton"] > button > div {
    text-align: left !important;
    justify-content: flex-start !important;
}
</style>
""", unsafe_allow_html=True)

catalog = load_catalog()

# --- Session state ---
if "selected_author" not in st.session_state:
    st.session_state.selected_author = "All Authors"
if "selected_work" not in st.session_state:
    st.session_state.selected_work = None
if "selected_volume" not in st.session_state:
    st.session_state.selected_volume = None
if "wizard_step" not in st.session_state:
    st.session_state.wizard_step = 0


def select_author(author):
    st.session_state.selected_author = author
    st.session_state.selected_work = None
    st.session_state.wizard_step = 0
    st.session_state.page_num = 1


def select_work(work_number, volume=None):
    st.session_state.selected_work = work_number
    st.session_state.selected_volume = volume  # None = all volumes
    st.session_state.wizard_step = 1


def reset_selection():
    st.session_state.selected_author = "All Authors"
    st.session_state._selected_series = "All Series"
    st.session_state.selected_work = None
    st.session_state.selected_volume = None
    st.session_state.expanded_work = None
    st.session_state.wizard_step = 0
    st.session_state.page_num = 1


# --- Handle pending series selection (from series buttons in main area) ---
if "_pending_series" in st.session_state:
    st.session_state._selected_series = st.session_state._pending_series
    del st.session_state._pending_series
if "_selected_series" not in st.session_state:
    st.session_state._selected_series = "All Series"

# --- Sidebar: Filters ---
st.sidebar.header("Filters")

# Search box at top
search_query = st.sidebar.text_input("Search titles, authors, IDs...")

# Author dropdown (synced with session state)
authors = sorted(catalog["author_display"].dropna().unique())
author_options = ["All Authors"] + authors
author_idx = author_options.index(st.session_state.selected_author) \
    if st.session_state.selected_author in author_options else 0


def _on_author_change():
    st.session_state.selected_author = st.session_state.author_filter
    st.session_state.page_num = 1


st.sidebar.selectbox(
    "Author", author_options, index=author_idx,
    key="author_filter", on_change=_on_author_change,
)
selected_author = st.session_state.selected_author

# Series filter — cascaded from author selection
if selected_author != "All Authors":
    author_catalog = catalog[catalog["author_display"] == selected_author]
    series_list = sorted(author_catalog["series_name"].dropna().unique())
else:
    series_list = sorted(catalog["series_name"].dropna().unique())
series_list = [s for s in series_list if s]  # remove empty strings
series_options = ["All Series"] + series_list

# Reset series selection if it's no longer valid for the current author
if st.session_state._selected_series not in series_options:
    st.session_state._selected_series = "All Series"


def _on_series_change():
    st.session_state._selected_series = st.session_state.series_filter
    st.session_state.page_num = 1


series_idx = series_options.index(st.session_state._selected_series)
st.sidebar.selectbox(
    "Series", series_options, index=series_idx,
    key="series_filter", on_change=_on_series_change,
)
selected_series = st.session_state._selected_series

# Category filter
categories = sorted(catalog["category_english"].dropna().unique())
cat_options = ["All Categories"] + categories
selected_category = st.sidebar.selectbox("Category", cat_options)

if st.sidebar.button("Clear All Filters"):
    reset_selection()
    st.rerun()

# Apply filters
filtered = catalog.copy()
if selected_author != "All Authors":
    filtered = filtered[filtered["author_display"] == selected_author]
if selected_series != "All Series":
    filtered = filtered[filtered["series_name"] == selected_series]
if selected_category != "All Categories":
    filtered = filtered[filtered["category_english"] == selected_category]
if search_query:
    q = search_query.lower()
    mask = (
        filtered["title_chinese"].str.lower().str.contains(q, na=False)
        | filtered["author_chinese"].str.lower().str.contains(q, na=False)
        | filtered["title_en"].str.lower().str.contains(q, na=False)
        | filtered["author_en"].str.lower().str.contains(q, na=False)
        | filtered["work_number"].str.lower().str.contains(q, na=False)
        | filtered["category_english"].str.lower().str.contains(q, na=False)
    )
    filtered = filtered[mask]

# --- Sidebar: Stats ---
st.sidebar.markdown("---")
st.sidebar.metric("Total Works", len(catalog))
st.sidebar.metric("Authors", catalog["author_display"].nunique())
st.sidebar.metric("Series", len(series_list))
st.sidebar.metric("Showing", len(filtered))


# ============================================================
# MAIN AREA — Depends on selection state
# ============================================================

# If a work is selected, show the translation wizard
if st.session_state.selected_work:
    work_row = catalog[catalog["work_number"] == st.session_state.selected_work]
    if work_row.empty:
        st.error(f"Work {st.session_state.selected_work} not found")
        st.session_state.selected_work = None
        st.rerun()
    else:
        work = work_row.iloc[0]
        cleaned = get_cleaned_files(work["work_number"])
        cleaned_paths = [Path(p) for p in cleaned]
        translations = get_translation_status(work["work_number"])
        epubs = get_epub_files(work["work_number"])

        # Back button
        if st.button("< Back to Browse"):
            st.session_state.selected_work = None
            st.session_state.wizard_step = 0
            st.rerun()

        # --- Compact Header ---
        title_display = work['title_en'] or work['title_chinese']
        wiki_url = work.get('wiki_url', '')
        title_zh = work['title_chinese']
        if wiki_url:
            st.markdown(f"## [{title_display}]({wiki_url})")
        else:
            st.markdown(f"## {title_display}")
        if work["title_en"] and title_zh:
            st.caption(f"`{title_zh}`")
        st.code(work["work_number"], language=None)

        # Single metadata line: Author · Series · Year · Category
        meta_parts = []
        author_wiki = work.get('author_wiki_url', '')
        author_cn = work.get('author_chinese', '')
        author_suffix = f" (`{author_cn}`)" if author_cn else ""
        if author_wiki:
            meta_parts.append(f"[{work['author_display']}]({author_wiki}){author_suffix}")
        else:
            meta_parts.append(f"{work['author_display']}{author_suffix}")
        if work.get("series_name"):
            order_text = f" #{int(work['series_order'])}" if work.get("series_order") else ""
            meta_parts.append(f"{work['series_name']}{order_text}")
        if work.get("publication_year") and work["publication_year"] > 0:
            meta_parts.append(str(int(work['publication_year'])))
        if work["category_english"]:
            meta_parts.append(work["category_english"])
        st.markdown(" · ".join(meta_parts))

        if work["summary"]:
            with st.expander("Summary"):
                st.markdown(work["summary"])

        st.markdown("---")

        # --- Wizard Steps (breadcrumb) ---
        step_labels = ["Overview", "Select Chapters", "Review & Launch"]
        wizard_step = st.session_state.wizard_step

        breadcrumb_parts = []
        for i, label in enumerate(step_labels):
            if i < wizard_step:
                breadcrumb_parts.append(f"✓ {label}")
            elif i == wizard_step:
                breadcrumb_parts.append(f"**{label}**")
            else:
                breadcrumb_parts.append(label)
        st.markdown("  →  ".join(breadcrumb_parts))

        # ---- STEP 1: Overview (Tabbed) ----
        if wizard_step == 0:
            tab_names = ["Source Files", "Translations & EPUB", "Quality"]
            tab_source, tab_trans, tab_quality = st.tabs(tab_names)

            with tab_source:
                if not cleaned_paths:
                    st.warning("No cleaned files found. This work needs to be cleaned first.")
                else:
                    file_data = []
                    for cf in cleaned_paths:
                        stats = get_book_stats(str(cf))
                        file_data.append({
                            "File": cf.name,
                            "Chapters": stats["chapters"] if stats else "?",
                            "Blocks": stats["blocks"] if stats else "?",
                            "Characters (source)": f"{stats['chars']:,}" if stats else "?",
                        })
                    st.table(pd.DataFrame(file_data))

            with tab_trans:
                if translations:
                    for t in translations:
                        if t.get("error"):
                            st.warning(f"⚠️ `{t['dir']}`")
                        else:
                            col1, col2 = st.columns([4, 1])
                            with col1:
                                st.success(
                                    f"✅ `{t['dir']}` — "
                                    f"{t['chapters']} chapters, "
                                    f"{t['translated_blocks']} translated blocks, "
                                    f"{t['footnotes']} footnotes"
                                )
                            with col2:
                                json_path = Path(t["path"])
                                if st.button("Convert to EPUB", key=f"epub_{json_path.name}"):
                                    try:
                                        from processors.epub_builder import EpubBuilder
                                        builder = EpubBuilder()
                                        epub_path = builder.build(json_path)
                                        size_kb = epub_path.stat().st_size / 1024
                                        st.success(f"Generated `{epub_path.name}` ({size_kb:.0f} KB)")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed: {e}")
                else:
                    st.info("No translations yet.")

                if epubs:
                    st.markdown("---")
                    for ep in epubs:
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"📖 `{ep.name}`")
                        with col2:
                            with open(ep, "rb") as f:
                                st.download_button(
                                    "Download", f.read(),
                                    file_name=ep.name,
                                    mime="application/epub+zip",
                                    key=f"dl_{ep.name}",
                                )

            with tab_quality:
                if translations:
                    current_approval = load_approvals().get(work["work_number"], {})
                    current_status = current_approval.get("status", "")
                    current_notes = current_approval.get("notes", "")

                    status_options = ["", "approved", "needs_review", "rejected"]
                    status_labels = ["Not reviewed", "Approved", "Needs Review", "Rejected"]
                    current_idx = status_options.index(current_status) if current_status in status_options else 0

                    col1, col2 = st.columns([1, 3])
                    with col1:
                        new_status = st.radio(
                            "Quality verdict",
                            status_options,
                            format_func=lambda x: dict(zip(status_options, status_labels)).get(x, x),
                            index=current_idx,
                            key="approval_radio",
                        )
                    with col2:
                        notes = st.text_area("Notes", value=current_notes, key="approval_notes",
                                             placeholder="What's good/bad about this translation?")

                    if st.button("Save Review"):
                        save_approval(work["work_number"], new_status, notes)
                        st.success("Review saved!")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.info("Translate first, then review quality here.")

            if cleaned_paths:
                st.markdown("")
                if st.button("Translate This Work", type="primary"):
                    st.session_state.wizard_step = 1
                    st.rerun()

        # ---- STEP 2: Select Volume & Chapters ----
        elif wizard_step == 1:
            st.subheader("Configure Translation")

            if not cleaned_paths:
                st.error("No cleaned files available.")
                st.session_state.wizard_step = 0
                st.rerun()

            # Volume selection
            pre_selected_vol = st.session_state.get("selected_volume")

            if len(cleaned_paths) > 1:
                st.markdown("**This work has multiple volumes:**")
                vol_labels = [f.name for f in cleaned_paths]
                vol_stats = []
                for cf in cleaned_paths:
                    stats = get_book_stats(str(cf))
                    vol_stats.append(stats)

                # Show volume cards
                vol_cols = st.columns(min(len(cleaned_paths), 4))
                for i, (col, cf, stats) in enumerate(zip(vol_cols, cleaned_paths, vol_stats)):
                    with col:
                        st.markdown(f"**Volume {i+1}**")
                        st.caption(cf.stem.replace("cleaned_", ""))
                        if stats:
                            st.markdown(
                                f"{stats['chapters']} chapters  \n"
                                f"{stats['blocks']} blocks  \n"
                                f"{stats['chars']:,} chars"
                            )

                # Pre-select volume if chosen from browse table
                default_all = pre_selected_vol is None
                translate_all = st.checkbox("Translate all volumes", value=default_all)

                if translate_all:
                    selected_files = cleaned_paths
                else:
                    # Find pre-selected volume index
                    default_idx = 0
                    if pre_selected_vol:
                        for idx, lbl in enumerate(vol_labels):
                            if pre_selected_vol in lbl:
                                default_idx = idx
                                break
                    sel_vol = st.selectbox("Select volume", vol_labels, index=default_idx)
                    selected_files = [cleaned_paths[vol_labels.index(sel_vol)]]
            else:
                selected_files = cleaned_paths
                stats = get_book_stats(str(selected_files[0]))

            # Chapter range (per file)
            st.markdown("---")
            file_configs = []
            for sf in selected_files:
                fstats = get_book_stats(str(sf))
                if not fstats:
                    continue

                if len(selected_files) > 1:
                    st.markdown(f"**{sf.stem.replace('cleaned_', '')}** — {fstats['chapters']} chapters")

                col1, col2 = st.columns(2)
                with col1:
                    start = st.number_input(
                        "Start chapter", min_value=1,
                        max_value=fstats["chapters"],
                        value=1, key=f"start_{sf.name}"
                    )
                with col2:
                    max_n = fstats["chapters"] - start + 1
                    num = st.number_input(
                        "Number of chapters", min_value=1,
                        max_value=max_n,
                        value=max_n, key=f"num_{sf.name}"
                    )
                file_configs.append({
                    "path": sf,
                    "stats": fstats,
                    "start": start,
                    "num": num,
                })

            # Model & workers
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                model = st.selectbox("Model", ["gpt-4.1-mini", "gpt-4.1-nano"])
            with col2:
                workers = st.number_input("Workers", min_value=1, max_value=12, value=6)
            with col3:
                output_base = st.text_input(
                    "Output directory",
                    value=f"translation_data/{work['work_number']}",
                )

            # Store config and advance
            st.markdown("")
            col_back, col_next = st.columns(2)
            with col_back:
                if st.button("< Back"):
                    st.session_state.wizard_step = 0
                    st.rerun()
            with col_next:
                if st.button("Review Plan", type="primary"):
                    st.session_state.wizard_config = {
                        "files": file_configs,
                        "model": model,
                        "workers": workers,
                        "output_base": output_base,
                    }
                    st.session_state.wizard_step = 2
                    st.rerun()

        # ---- STEP 3: Review & Launch ----
        elif wizard_step == 2:
            st.subheader("Translation Plan")

            config = st.session_state.get("wizard_config", {})
            file_configs = config.get("files", [])
            model = config.get("model", "gpt-4.1-mini")
            workers_count = config.get("workers", 6)
            output_base = config.get("output_base", "translation_data")

            if not file_configs:
                st.error("No configuration. Go back to Step 2.")
                st.session_state.wizard_step = 1
                st.rerun()

            # Summary table
            total_chapters = 0
            total_blocks = 0
            total_chars = 0
            plan_rows = []
            commands = []

            for fc in file_configs:
                fp = fc["path"]
                s = fc["stats"]
                start = fc["start"]
                num = fc["num"]
                end = start + num - 1

                # Estimate blocks in selected range
                est_blocks = int(s["blocks"] * num / s["chapters"]) if s["chapters"] else 0
                est_chars = int(s["chars"] * num / s["chapters"]) if s["chapters"] else 0

                total_chapters += num
                total_blocks += est_blocks
                total_chars += est_chars

                vol_label = fp.stem.replace("cleaned_", "")
                plan_rows.append({
                    "Volume": vol_label,
                    "Chapters": f"{start}-{end} ({num} of {s['chapters']})",
                    "Est. Blocks": est_blocks,
                    "Est. Characters": f"{est_chars:,}",
                })

                cmd = (
                    f"python scripts/test_pipeline_validation.py "
                    f'--input "{fp}" '
                    f"--start-chapter {start} --num-chapters {num} "
                    f"--model {model} --workers {workers_count} "
                    f'--output-dir "{output_base}"'
                )
                commands.append(cmd)

            # Add totals row to plan table
            est_cost = total_blocks * 0.003 if "mini" in model else total_blocks * 0.001
            plan_rows.append({
                "Volume": "**Total**",
                "Chapters": f"**{total_chapters}**",
                "Est. Blocks": f"**{total_blocks}**",
                "Est. Characters": f"**{total_chars:,}**",
            })
            st.table(pd.DataFrame(plan_rows))
            st.caption(f"Model: {model} · Est. cost: ${est_cost:.2f}")

            # Warn if already translated
            if translations:
                existing_chapters = sum(t.get("chapters", 0) for t in translations if not t.get("error"))
                cleaned_total = sum(
                    (get_book_stats(str(fc["path"])) or {}).get("chapters", 0)
                    for fc in file_configs
                )
                if cleaned_total and existing_chapters >= cleaned_total:
                    st.warning(
                        f"This work is fully translated ({existing_chapters}/{cleaned_total} chapters). "
                        "Launching again will overwrite existing output."
                    )
                elif existing_chapters:
                    st.info(
                        f"This work is partially translated ({existing_chapters}/{cleaned_total} chapters). "
                        "New translation will cover the selected chapter range."
                    )
                else:
                    st.warning(
                        f"This work has {len(translations)} translation file(s). "
                        "Launching again will overwrite existing output."
                    )

            st.markdown("---")
            st.markdown("**Commands to execute:**")
            for cmd in commands:
                st.code(cmd, language="bash")

            # Launch
            col_back, col_launch = st.columns(2)
            with col_back:
                if st.button("< Back to Config"):
                    st.session_state.wizard_step = 1
                    st.rerun()
            with col_launch:
                if st.button("Launch Translation", type="primary"):
                    for i, cmd in enumerate(commands):
                        fc = file_configs[i]
                        vol = fc["path"].stem.replace("cleaned_", "")
                        st.info(f"Translating {vol} chapters {fc['start']}-{fc['start']+fc['num']-1}...")
                        with st.spinner(f"Processing {vol}..."):
                            try:
                                result = subprocess.run(
                                    cmd, shell=True,
                                    capture_output=True, text=True,
                                    cwd=str(PROJECT_ROOT),
                                    timeout=1800,
                                )
                                if result.returncode == 0:
                                    st.success(f"{vol}: Translation complete!")
                                else:
                                    st.error(f"{vol}: Failed (exit code {result.returncode})")

                                with st.expander(f"Log: {vol}", expanded=result.returncode != 0):
                                    st.text(result.stdout[-5000:] if result.stdout else "(no output)")
                                    if result.stderr:
                                        st.text(result.stderr[-3000:])
                            except subprocess.TimeoutExpired:
                                st.error(f"{vol}: Timed out after 30 minutes")
                            except Exception as e:
                                st.error(f"{vol}: Error — {e}")

        # Bottom back button (always visible)
        st.markdown("---")
        if st.button("< Back to Browse", key="back_bottom"):
            st.session_state.selected_work = None
            st.session_state.wizard_step = 0
            st.rerun()

# ============================================================
# No work selected — show browse view
# ============================================================
else:
    # Author cards (clickable, collapsed by default)
    if selected_author == "All Authors" and not search_query:
        # Count distinct novels (strip edition prefixes and volume suffixes)
        _fc = filtered.copy()
        _fc["_base_title"] = _fc["title_chinese"].str.replace(
            r"^(舊版|新修版|新版)", "", regex=True
        )
        author_counts = (
            _fc.groupby(["author_display", "author_chinese"])
            .agg(works=("_base_title", "nunique"))
            .reset_index()
            .sort_values("works", ascending=False)
        )

        with st.expander(f"Authors ({len(author_counts)})", expanded=False):
            # Load author metadata for Wikipedia links
            _author_meta = {}
            try:
                from utils.db import connect_catalog
                _conn = connect_catalog(CATALOG_DB)
                _cur = _conn.cursor()
                _cur.execute("SELECT name_chinese, wikipedia_url, birth_year, death_year FROM authors")
                for r in _cur.fetchall():
                    _author_meta[r[0]] = {"url": r[1], "birth": r[2], "death": r[3]}
                _conn.close()
            except Exception:
                pass

            cols_per_row = 5
            for row_start in range(0, len(author_counts), cols_per_row):
                cols = st.columns(cols_per_row)
                for col_idx, col in enumerate(cols):
                    idx = row_start + col_idx
                    if idx >= len(author_counts):
                        break
                    row = author_counts.iloc[idx]
                    with col:
                        if st.button(
                            row["author_display"],
                            key=f"author_{idx}",
                            use_container_width=True,
                        ):
                            select_author(row["author_display"])
                            st.rerun()
                        meta = _author_meta.get(row["author_chinese"], {})
                        life = ""
                        if meta.get("birth"):
                            life = f"{meta['birth']}"
                            if meta.get("death"):
                                life += f"–{meta['death']}"
                            life += " · "
                        caption = f"{life}{row['works']} works"
                        if meta.get("url"):
                            st.caption(f"{caption} · [wiki]({meta['url']})")
                        else:
                            st.caption(caption)

    # Series overview when filtering by author
    if selected_author != "All Authors" and not search_query:
        author_series = filtered[filtered["series_name"] != ""].groupby("series_name").agg(
            works=("work_number", "count"),
            series_type=("series_type", "first"),
            min_order=("series_order", "min"),
            max_order=("series_order", "max"),
        ).reset_index().sort_values("series_name")

        if not author_series.empty:
            st.subheader("Series")
            scols = st.columns(min(len(author_series), 4))
            for si, (col, (_, srow)) in enumerate(zip(scols, author_series.iterrows())):
                with col:
                    stype = srow["series_type"]
                    label = f"{srow['series_name']} ({stype})"
                    if st.button(label, key=f"series_btn_{si}", use_container_width=True):
                        st.session_state._pending_series = srow["series_name"]
                        st.rerun()
                    st.caption(f"{int(srow['works'])} works in catalog")
            st.markdown("---")

    # Works table — count distinct novels (strip edition prefixes)
    _base = filtered["title_chinese"].str.replace(r"^(舊版|新修版|新版)", "", regex=True)
    n_novels = _base.nunique()
    st.subheader(f"Works ({n_novels} novels, {len(filtered)} editions)")

    # Build display dataframe with translation status
    trans_summary = get_translation_summary_all()
    approvals = load_approvals()

    display_df = filtered[
        ["author_display", "title_en", "work_number",
         "file_count", "total_chars", "category_english", "publication_year",
         "series_name", "series_order", "wiki_url", "author_wiki_url",
         "title_chinese", "series_name_zh"]
    ].copy()
    display_df.columns = [
        "Author", "Title", "ID", "Volumes", "db_chars", "Category", "Year",
        "Series", "SeriesOrder", "WikiURL", "AuthorWikiURL",
        "TitleZH", "SeriesZH"
    ]
    display_df["Year"] = display_df["Year"].fillna(0).astype(int)
    display_df["_year_raw"] = display_df["Year"]
    display_df["Year"] = display_df["Year"].apply(lambda y: str(y) if y > 0 else "")

    # Estimate size, English pages, and cost for each work
    # Calibrated against known works: 七劍下天山 (385K chars) ≈ 400-500 pages
    # ~800 Chinese chars per English printed page
    CHINESE_CHARS_PER_EN_PAGE = 800
    COST_PER_CHAR_MINI = 0.000008  # ~$0.008 per 1K chars with gpt-4.1-mini

    # ~1500 English chars per printed page (standard novel formatting)
    EN_CHARS_PER_PAGE = 1500

    def enrich_row(row):
        chars, is_est = estimate_work_size(row["ID"], row["Volumes"], row["db_chars"])
        prefix = "~" if is_est else ""
        en_pages = max(1, chars // CHINESE_CHARS_PER_EN_PAGE)
        cost_mini = chars * COST_PER_CHAR_MINI

        # Use actual translated char count for pages if available
        ts = trans_summary.get(row["ID"], {})
        en_chars = ts.get("en_chars", 0)
        if en_chars > 0:
            actual_pages = max(1, en_chars // EN_CHARS_PER_PAGE)
            pages_display = f"{actual_pages:,} (actual)"
            pages_raw = actual_pages
        else:
            pages_display = f"{prefix}{en_pages:,} (est)"
            pages_raw = en_pages

        return pd.Series({
            "Characters": f"{prefix}{chars:,}",
            "_chars_raw": chars,
            "Pages": pages_display,
            "_pages_raw": pages_raw,
            "Cost (est)": f"${cost_mini:.2f}",
            "_cost_raw": cost_mini,
        })

    enriched = display_df.apply(enrich_row, axis=1)
    display_df = pd.concat([display_df, enriched], axis=1)
    display_df = display_df.drop(columns=["db_chars"])

    # Add status column
    def work_status(work_num):
        approval = approvals.get(work_num, {})
        trans = trans_summary.get(work_num)
        if approval.get("status") == "approved":
            return "Approved"
        elif approval.get("status") == "rejected":
            return "Rejected"
        elif approval.get("status") == "needs_review":
            return "Review"
        elif trans:
            done = trans["chapters"]
            total = trans.get("total_chapters", 0)
            if total and done < total:
                return f"Partial ({done}/{total}ch)"
            return f"Translated ({done}ch)"
        return "Not started"

    display_df["Status"] = display_df["ID"].apply(work_status)

    # --- Controls bar: search, sort, clear, show Chinese ---
    ctrl_cols = st.columns([4, 2, 2, 1, 2])
    with ctrl_cols[0]:
        table_search = st.text_input(
            "Search", key="table_filter", label_visibility="collapsed",
            placeholder="Search works...",
        )
    with ctrl_cols[1]:
        sort_options = ["Author", "Title", "ID", "Volumes", "Pages", "Cost", "Year", "Series", "Category", "Status"]
        if "sort_col" not in st.session_state:
            st.session_state.sort_col = "Author"
        sort_col = st.selectbox(
            "Sort by", sort_options, label_visibility="collapsed",
            index=sort_options.index(st.session_state.sort_col),
            key="sort_select",
        )
        st.session_state.sort_col = sort_col
    with ctrl_cols[2]:
        sort_asc = st.toggle("A-Z / Low-High", value=True, key="sort_asc")
    with ctrl_cols[3]:
        if st.button("Clear", key="clear_filters"):
            reset_selection()
            st.rerun()
    with ctrl_cols[4]:
        show_chinese = st.toggle("Show Chinese", value=False, key="show_chinese")

    page_size = 25

    # Apply table search filter
    if table_search:
        tq = table_search.lower()
        mask = display_df.apply(
            lambda r: any(tq in str(v).lower() for v in r), axis=1
        )
        display_df = display_df[mask]

    # Apply sort
    sort_map = {
        "Author": ["Author"],
        "Title": ["Title"],
        "ID": ["ID"],
        "Volumes": ["Volumes"],
        "Pages": ["_pages_raw"],
        "Cost": ["_cost_raw"],
        "Year": ["_year_raw"],
        "Series": ["Series", "SeriesOrder"],
        "Category": ["Category"],
        "Status": ["Status"],
    }
    # When a series is selected, override sort to series order
    if selected_series != "All Series":
        sort_keys = ["SeriesOrder"]
        sort_asc_applied = True
    else:
        sort_keys = sort_map.get(sort_col, ["Author"])
        sort_asc_applied = sort_asc
    display_df = display_df.sort_values(sort_keys, ascending=sort_asc_applied).reset_index(drop=True)

    # Pagination
    total_pages = max(1, (len(display_df) + page_size - 1) // page_size)
    if "page_num" not in st.session_state:
        st.session_state.page_num = 1
    st.session_state.page_num = min(st.session_state.page_num, total_pages)
    page = st.session_state.page_num
    start_row = (page - 1) * page_size
    end_row = min(start_row + page_size, len(display_df))

    # Pagination bar (top)
    def render_pagination(key_suffix=""):
        if total_pages > 1:
            pcol1, pcol2, pcol3 = st.columns([1, 3, 1])
            with pcol1:
                if st.button("< Prev", disabled=(page <= 1), key=f"page_prev{key_suffix}"):
                    st.session_state.page_num = page - 1
                    st.rerun()
            with pcol2:
                st.markdown(
                    f"<div style='text-align:center; padding-top:0.3em'>"
                    f"Page {page} of {total_pages} &nbsp;&middot;&nbsp; "
                    f"Showing {start_row+1}-{end_row} of {len(display_df)}</div>",
                    unsafe_allow_html=True,
                )
            with pcol3:
                if st.button("Next >", disabled=(page >= total_pages), key=f"page_next{key_suffix}"):
                    st.session_state.page_num = page + 1
                    st.rerun()
        else:
            st.caption(f"Showing {len(display_df)} works")

    render_pagination("_top")

    # Render table
    if display_df.empty:
        st.info("No works match your filters.")
    else:
        # Header row — adjust columns based on Show Chinese toggle
        if show_chinese:
            col_widths = [2, 3, 2, 1, 1, 1, 1, 1, 2, 1]
            headers = ["Author", "Title", "Chinese", "ID", "Vols", "Pages", "Cost", "Year", "Series", "Status"]
        else:
            col_widths = [3, 4, 1, 1, 1, 1, 1, 2, 1]
            headers = ["Author", "Title", "ID", "Vols", "Pages", "Cost", "Year", "Series", "Status"]
        # Map display header to sort key
        header_sort_map = {"Vols": "Volumes", "Chinese": "TitleZH"}
        hcols = st.columns(col_widths)
        for hc, h in zip(hcols, headers):
            sk = header_sort_map.get(h, h)
            label = f"**{h}**" if sk != sort_col else f"**{h} {'▲' if sort_asc else '▼'}**"
            hc.markdown(label)

        # Data rows
        if "expanded_work" not in st.session_state:
            st.session_state.expanded_work = None

        # Column index offset when Chinese column is shown
        c = 1 if show_chinese else 0

        for i in range(start_row, end_row):
            row = display_df.iloc[i]
            rcols = st.columns(col_widths)
            work_num = row["ID"]
            num_vols = int(row["Volumes"]) if row["Volumes"] else 1

            # Author column — clickable button
            if rcols[0].button(row["Author"], key=f"auth_{work_num}_{i}", use_container_width=True):
                select_author(row["Author"])
                st.rerun()

            # Title column — with Wikipedia link if available
            title_text = row["Title"] if row["Title"] else "(untitled)"
            wiki_url = row.get("WikiURL", "")
            if num_vols > 1:
                is_expanded = st.session_state.expanded_work == work_num
                expand_icon = "▾" if is_expanded else "▸"
                if rcols[1].button(f"{expand_icon} {title_text}", key=f"work_{work_num}_{i}", use_container_width=True):
                    if is_expanded:
                        st.session_state.expanded_work = None
                    else:
                        st.session_state.expanded_work = work_num
                    st.rerun()
            else:
                if rcols[1].button(title_text, key=f"work_{work_num}_{i}", use_container_width=True):
                    select_work(work_num)
                    st.rerun()

            # Chinese column (title + series)
            if show_chinese:
                zh_parts = [row.get("TitleZH", "")]
                series_zh = row.get("SeriesZH", "")
                if series_zh:
                    zh_parts.append(f"({series_zh})")
                rcols[2].markdown(" ".join(p for p in zh_parts if p))

            # ID column — with Wikipedia link icon if available
            id_text = f"[{work_num}]({wiki_url})" if wiki_url else work_num
            rcols[2 + c].markdown(id_text)
            rcols[3 + c].markdown(str(num_vols))
            rcols[4 + c].markdown(row["Pages"] if row["Pages"] else "")
            rcols[5 + c].markdown(row["Cost (est)"] if row["Cost (est)"] else "")
            rcols[6 + c].markdown(row["Year"] if row["Year"] else "")
            # Series column
            series_text = row.get("Series", "")
            if series_text:
                order = row.get("SeriesOrder", 0)
                series_text = f"{series_text} #{int(order)}" if order else series_text
            rcols[7 + c].markdown(series_text if series_text else "")
            rcols[8 + c].markdown(row["Status"])

            # Volume sub-rows for expanded multi-volume works
            if num_vols > 1 and st.session_state.expanded_work == work_num:
                cleaned = get_cleaned_files(work_num)
                # "All volumes" option
                sub = st.columns(col_widths)
                sub[0].markdown("")
                if sub[1].button(
                    f"  All {num_vols} volumes", key=f"vol_all_{work_num}",
                    use_container_width=True,
                ):
                    select_work(work_num, volume=None)
                    st.rerun()
                if show_chinese:
                    sub[2].markdown("")
                sub[2 + c].markdown("")
                sub[3 + c].markdown(str(num_vols))
                sub[4 + c].markdown(row["Pages"] if row["Pages"] else "")
                sub[5 + c].markdown(row["Cost (est)"] if row["Cost (est)"] else "")

                # Individual volumes
                for vi, cf in enumerate(cleaned):
                    cf_path = Path(cf)
                    vol_stats = get_book_stats(cf)
                    # Try to get volume letter (last char of the work number part)
                    vol_suffix = ""
                    for part in cf_path.stem.split("_"):
                        if part.startswith(work_num) and len(part) > len(work_num):
                            vol_suffix = part[len(work_num):]
                            break

                    sub = st.columns(col_widths)
                    sub[0].markdown("")
                    vol_label = f"  Vol {vol_suffix.upper() or vi+1}"
                    if vol_stats:
                        vol_label += f" ({vol_stats['chapters']}ch)"
                    if sub[1].button(
                        vol_label, key=f"vol_{work_num}_{vi}",
                        use_container_width=True,
                    ):
                        select_work(work_num, volume=vol_suffix or str(vi+1))
                        st.rerun()
                    if show_chinese:
                        sub[2].markdown("")
                    sub[2 + c].markdown(f"{work_num}{vol_suffix}" if vol_suffix else "")
                    sub[3 + c].markdown("1")
                    if vol_stats:
                        v_pages = max(1, vol_stats["chars"] // CHINESE_CHARS_PER_EN_PAGE)
                        v_cost = vol_stats["chars"] * COST_PER_CHAR_MINI
                        sub[4 + c].markdown(str(v_pages))
                        sub[5 + c].markdown(f"${v_cost:.2f}")

        # Bottom pagination
        render_pagination("_bottom")
