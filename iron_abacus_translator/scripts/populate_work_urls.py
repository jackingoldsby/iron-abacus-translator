#!/usr/bin/env python3
"""
Populate work_urls table with Wikipedia links for notable works.
Data sourced from Wikipedia author pages (Jin Yong, Gu Long, Liang Yusheng, etc.)
"""

from utils.db import connect_catalog
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.environment_config import get_or_create_config
CATALOG_DB = get_or_create_config().catalog_path


# Map Chinese title (or substring) -> Wikipedia URL
# Extracted from author Wikipedia pages
KNOWN_WORK_URLS = {
    # === JIN YONG ===
    "書劍恩仇錄": ("https://en.wikipedia.org/wiki/The_Book_and_the_Sword", "wikipedia"),
    "碧血劍": ("https://en.wikipedia.org/wiki/Sword_Stained_with_Royal_Blood", "wikipedia"),
    "射鵰英雄傳": ("https://en.wikipedia.org/wiki/The_Legend_of_the_Condor_Heroes", "wikipedia"),
    "雪山飛狐": ("https://en.wikipedia.org/wiki/Fox_Volant_of_the_Snowy_Mountain", "wikipedia"),
    "神鵰俠侶": ("https://en.wikipedia.org/wiki/The_Return_of_the_Condor_Heroes", "wikipedia"),
    "飛狐外傳": ("https://en.wikipedia.org/wiki/The_Young_Flying_Fox", "wikipedia"),
    "倚天屠龍記": ("https://en.wikipedia.org/wiki/The_Heaven_Sword_and_Dragon_Saber", "wikipedia"),
    "天龍八部": ("https://en.wikipedia.org/wiki/Demi-Gods_and_Semi-Devils", "wikipedia"),
    "連城訣": ("https://en.wikipedia.org/wiki/A_Deadly_Secret", "wikipedia"),
    "笑傲江湖": ("https://en.wikipedia.org/wiki/The_Smiling,_Proud_Wanderer", "wikipedia"),
    "鹿鼎記": ("https://en.wikipedia.org/wiki/The_Deer_and_the_Cauldron", "wikipedia"),
    "越女劍": ("https://en.wikipedia.org/wiki/Sword_of_the_Yue_Maiden", "wikipedia"),
    "鴛鴦刀": ("https://en.wikipedia.org/wiki/Blade-dance_of_the_Two_Lovers", "wikipedia"),
    "白馬嘯西風": ("https://en.wikipedia.org/wiki/White_Horse_Neighs_in_the_Western_Wind", "wikipedia"),
    "俠客行": ("https://en.wikipedia.org/wiki/Ode_to_Gallantry", "wikipedia"),

    # === GU LONG ===
    "絕代雙驕": ("https://en.wikipedia.org/wiki/Juedai_Shuangjiao", "wikipedia"),
    "流星蝴蝶劍": ("https://en.wikipedia.org/wiki/Liuxing_Hudie_Jian", "wikipedia"),
    "多情劍客無情劍": ("https://en.wikipedia.org/wiki/Xiaoli_Feidao", "wikipedia"),  # series page
    "楚留香傳奇": ("https://en.wikipedia.org/wiki/Chu_Liuxiang", "wikipedia"),  # series page
    "陸小鳳傳奇": ("https://en.wikipedia.org/wiki/Lu_Xiaofeng", "wikipedia"),  # series page
    "英雄無淚": ("https://en.wikipedia.org/wiki/Ying_Xiong_Wu_Lei", "wikipedia"),
    "蕭十一郎": ("https://en.wikipedia.org/wiki/Xiao_Shi_Yi_Lang", "wikipedia"),

    # === LIANG YUSHENG ===
    "白髮魔女傳": ("https://en.wikipedia.org/wiki/Baifa_Mon%C3%BC_Zhuan", "wikipedia"),
    "七劍下天山": ("https://en.wikipedia.org/wiki/Qijian_Xia_Tianshan", "wikipedia"),
    "萍蹤俠影錄": ("https://en.wikipedia.org/wiki/Pingzong_Xiaying_Lu", "wikipedia"),
    "雲海玉弓緣": ("https://en.wikipedia.org/wiki/Yunhai_Yugong_Yuan", "wikipedia"),
    "龍虎鬥京華": ("https://en.wikipedia.org/wiki/Longhu_Dou_Jinghua", "wikipedia"),
    "草莽龍蛇傳": ("https://en.wikipedia.org/wiki/Caomang_Longshe_Zhuan", "wikipedia"),
    "塞外奇俠傳": ("https://en.wikipedia.org/wiki/Saiwai_Qixia_Zhuan", "wikipedia"),
    "江湖三女俠": ("https://en.wikipedia.org/wiki/Jianghu_San_N%C3%BCxia", "wikipedia"),
    "冰魄寒光劍": ("https://en.wikipedia.org/wiki/Bingpo_Hanguang_Jian", "wikipedia"),
    "冰川天女傳": ("https://en.wikipedia.org/wiki/Bingchuan_Tiann%C3%BC_Zhuan", "wikipedia"),
    "冰河洗劍錄": ("https://en.wikipedia.org/wiki/Binghe_Xijian_Lu", "wikipedia"),
    "風雷震九州": ("https://en.wikipedia.org/wiki/Fenglei_Zhen_Jiuzhou", "wikipedia"),
    "俠骨丹心": ("https://en.wikipedia.org/wiki/Xiagu_Danxin", "wikipedia"),
    "游劍江湖": ("https://en.wikipedia.org/wiki/Youjian_Jianghu", "wikipedia"),
    "牧野流星": ("https://en.wikipedia.org/wiki/Muye_Liuxing", "wikipedia"),
    "彈指驚雷": ("https://en.wikipedia.org/wiki/Tanzhi_Jinglei", "wikipedia"),
    "絕塞傳烽錄": ("https://en.wikipedia.org/wiki/Juesai_Chuanfeng_Lu", "wikipedia"),
    "大唐游俠傳": ("https://en.wikipedia.org/wiki/Datang_Youxia_Zhuan", "wikipedia"),
    "龍鳳寶釵緣": ("https://en.wikipedia.org/wiki/Longfeng_Baochai_Yuan", "wikipedia"),
    "慧劍心魔": ("https://en.wikipedia.org/wiki/Huijian_Xinmo", "wikipedia"),
    "狂俠天驕魔女": ("https://en.wikipedia.org/wiki/Kuangxia_Tianjiao_Mon%C3%BC", "wikipedia"),
    "飛鳳潛龍": ("https://en.wikipedia.org/wiki/Feifeng_Qianlong", "wikipedia"),
    "瀚海雄風": ("https://en.wikipedia.org/wiki/Hanhai_Xiongfeng", "wikipedia"),
    "鳴鏑風雲錄": ("https://en.wikipedia.org/wiki/Mingdi_Fengyun_Lu", "wikipedia"),
    "風雲雷電": ("https://en.wikipedia.org/wiki/Fengyun_Leidian", "wikipedia"),
    "武林天驕": ("https://en.wikipedia.org/wiki/Wulin_Tianjiao", "wikipedia"),
    "還劍奇情錄": ("https://en.wikipedia.org/wiki/Huanjian_Qiqing_Lu", "wikipedia"),
    "散花女俠": ("https://en.wikipedia.org/wiki/Sanhua_N%C3%BCxia", "wikipedia"),
    "聯劍風雲錄": ("https://en.wikipedia.org/wiki/Lianjian_Fengyun_Lu", "wikipedia"),
    "武林三絕": ("https://en.wikipedia.org/wiki/Wulin_Sanjue", "wikipedia"),
    "廣陵劍": ("https://en.wikipedia.org/wiki/Guangling_Jian", "wikipedia"),
    "女帝奇英傳": ("https://en.wikipedia.org/wiki/N%C3%BCdi_Qiying_Zhuan", "wikipedia"),
    "武當一劍": ("https://en.wikipedia.org/wiki/Wudang_Yijian", "wikipedia"),
    "劍網塵絲": ("https://en.wikipedia.org/wiki/Jianwang_Chensi", "wikipedia"),
    "幻劍靈旗": ("https://en.wikipedia.org/wiki/Huanjian_Lingqi", "wikipedia"),

    # === HUANG YI ===
    "尋秦記": ("https://en.wikipedia.org/wiki/A_Step_into_the_Past", "wikipedia"),
    "大唐雙龍傳": ("https://en.wikipedia.org/wiki/Twin_of_Brothers", "wikipedia"),

    # === WANG DULU ===
    # Crouching Tiger is part of the Crane-Iron series
}


def populate():
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()

    inserted = 0
    not_found = []

    for title_zh, (url, url_type) in KNOWN_WORK_URLS.items():
        # Find work by Chinese title - try exact match first
        row = cur.execute(
            "SELECT work_id, title_chinese FROM works WHERE title_chinese = ?",
            (title_zh,)
        ).fetchone()

        if not row:
            # Try LIKE match (for titles with edition prefixes)
            rows = cur.execute(
                "SELECT work_id, title_chinese FROM works WHERE title_chinese LIKE ?",
                (f"%{title_zh}%",)
            ).fetchall()
            if rows:
                # Insert for all matching variants (original, revised editions)
                for r in rows:
                    try:
                        cur.execute(
                            "INSERT INTO work_urls (work_id, url, url_type, description) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                            (r[0], url, url_type, f"English Wikipedia: {r[1]}"),
                        )
                        if cur.rowcount > 0:
                            inserted += 1
                    except Exception as e:
                        print(f"  Error: {r[1]}: {e}")
                continue
            else:
                not_found.append(title_zh)
                continue

        try:
            cur.execute(
                "INSERT INTO work_urls (work_id, url, url_type, description) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (row[0], url, url_type, f"English Wikipedia: {row[1]}"),
            )
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"  Error: {row[1]}: {e}")

    conn.commit()

    # Also add Condor Trilogy series page URL to all three Condor works
    condor_url = "https://en.wikipedia.org/wiki/Condor_Trilogy"
    for title in ["射鵰英雄傳", "神鵰俠侶", "倚天屠龍記"]:
        rows = cur.execute(
            "SELECT work_id FROM works WHERE title_chinese LIKE ?", (f"%{title}%",)
        ).fetchall()
        for r in rows:
            cur.execute(
                "INSERT INTO work_urls (work_id, url, url_type, description) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (r[0], condor_url, "wikipedia", "Condor Trilogy series page"),
            )
            if cur.rowcount > 0:
                inserted += 1

    conn.commit()

    total = cur.execute("SELECT COUNT(*) FROM work_urls").fetchone()[0]
    distinct_works = cur.execute("SELECT COUNT(DISTINCT work_id) FROM work_urls").fetchone()[0]
    print(f"Inserted {inserted} URLs. Total: {total} URLs for {distinct_works} distinct works.")

    if not_found:
        print(f"\nNot found in DB ({len(not_found)}):")
        for t in not_found:
            print(f"  {t}")

    # Show summary by author
    cur.execute("""
        SELECT w.author_chinese, COUNT(DISTINCT wu.work_id) as works_with_url
        FROM work_urls wu
        JOIN works w ON wu.work_id = w.work_id
        GROUP BY w.author_chinese
        ORDER BY works_with_url DESC
    """)
    print("\nWorks with URLs by author:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    conn.close()


if __name__ == "__main__":
    populate()
