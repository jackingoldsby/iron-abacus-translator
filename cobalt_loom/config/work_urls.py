"""Static mapping from work_number to source URL(s).

Hand-maintained because catalog titles may differ from wiki page titles
(e.g., 濟公傳 vs 濟公全傳). Each entry maps to a dict with 'wikisource'
and/or 'ctext' keys pointing to the page title or URL path.
"""

WORK_URLS = {
    "A005": {
        "wikisource": "說岳全傳",
    },
    "A006": {
        "wikisource": "隋唐演義",
    },
    "A007": {
        "wikisource": "東周列國志",
    },
    "A008": {
        "wikisource": "施公案",
    },
    "A009": {
        "wikisource": "彭公案",
    },
    "A010": {
        "wikisource": "包公案",
        "ctext": "baigongan",
    },
    "A011": {
        "wikisource": "狄公傳",  # Listed as 狄公案 in catalog but 狄公傳 on Wikisource
    },
    "A012": {
        "wikisource": "北遊記",  # Single-page work (no subpages)
    },
    "A013": {
        "wikisource": "南遊記",
        "ctext": "nanyouji",
    },
    "A014": {
        "wikisource": "東遊記",
        "ctext": "dongyouji",
    },
    "A015": {
        "wikisource": "濟公全傳",
        "ctext": "jigongzhuan",
    },
    "A016": {
        "wikisource": "楊家將演義",
    },
    "A017": {
        "wikisource": "水滸後傳",
    },
    "A018": {
        "wikisource": "兒女英雄傳",
    },
    # A019 (七俠五義): Not available on Wikisource or ctext.org with full text.
    # 七俠五義 is 俞樾's revision of 三俠五義 (A002). Only A002 is on Wikisource.
    # Omitted from WORK_URLS — requires EPUB or OCR source.
    "A020": {
        "wikisource": "官場現形記",
    },
    "A021": {
        "wikisource": "二十年目睹之怪現狀",
    },
    "A022": {
        "wikisource": "醒世姻緣傳",
        "ctext": "xingshiyinyuanzhuan",
    },
    "A023": {
        "wikisource": "野叟曝言",
        "ctext": "yesoupuyan",
    },
    # --- New classical works (A286–A292) ---
    "A286": {
        "wikisource": "三遂平妖傳",  # Catalog: 平妖傳; Wikisource uses full title 三遂平妖傳
    },
    "A287": {
        "wikisource": "鏡花緣",
    },
    "A288": {
        "wikisource": "綠野仙蹤",  # No disambiguation needed — novel is the primary page
    },
    "A289": {
        "wikisource": "初刻拍案驚奇",
    },
    "A290": {
        "wikisource": "二刻拍案驚奇",
    },
    "A291": {
        "wikisource": "孽海花",  # 35 chapters; also on ctext wiki.pl but Wikisource preferred
    },
    # A292 (隋煬帝艷史): Not on Wikisource under any character variant; ctext.org has
    # only a catalog stub (wiki.pl?res=338052) with no full text. Requires EPUB or OCR source.
}
