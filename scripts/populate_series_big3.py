#!/usr/bin/env python3
"""
Populate authors, series, and work_series tables for the big 3 wuxia authors:
Jin Yong, Gu Long, Liang Yusheng.

Data sourced from Wikipedia.
"""

from utils.db import connect_catalog
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.environment_config import get_or_create_config
CATALOG_DB = get_or_create_config().catalog_path


def populate():
    conn = connect_catalog(CATALOG_DB)
    cur = conn.cursor()

    # ==================== AUTHORS ====================

    authors = [
        {
            "name_chinese": "金庸",
            "name_english": "Jin Yong",
            "real_name_chinese": "查良鏞",
            "birth_year": 1924,
            "death_year": 2018,
            "nationality": "Chinese (Hong Kong)",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Jin_Yong",
            "description": "One of the most influential wuxia novelists. His 15 novels are among the most widely read Chinese fiction. Known for the Condor Trilogy.",
        },
        {
            "name_chinese": "古龍",
            "name_english": "Gu Long",
            "real_name_chinese": "熊耀華",
            "birth_year": 1938,
            "death_year": 1985,
            "nationality": "Taiwanese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Gu_Long",
            "description": "Taiwanese wuxia novelist influenced by Western detective fiction. Known for short, poetic prose and mysterious plots.",
        },
        {
            "name_chinese": "梁羽生",
            "name_english": "Liang Yusheng",
            "real_name_chinese": "陳文統",
            "birth_year": 1924,
            "death_year": 2009,
            "nationality": "Chinese-Australian",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Liang_Yusheng",
            "description": "Pioneer of the 'new school' wuxia genre. Known for incorporating Chinese history and poetry. Wrote 35 novels.",
        },
        {
            "name_chinese": "倪匡",
            "name_english": "Ni Kuang",
            "birth_year": 1935,
            "death_year": 2022,
            "nationality": "Chinese (Hong Kong)",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Ni_Kuang",
            "description": "Prolific Hong Kong writer of wuxia, science fiction, and screenplays. Created the Wisely series.",
        },
        {
            "name_chinese": "黃易",
            "name_english": "Huang Yi",
            "real_name_chinese": "黃祖強",
            "birth_year": 1952,
            "death_year": 2017,
            "nationality": "Chinese (Hong Kong)",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Huang_Yi_(novelist)",
            "description": "Known for blending wuxia with science fiction and time travel. Best known for A Step into the Past and Legend of the Great Tang.",
        },
        {
            "name_chinese": "臥龍生",
            "name_english": "Wolong Sheng",
            "real_name_chinese": "牛鶴亭",
            "birth_year": 1930,
            "death_year": 1997,
            "nationality": "Taiwanese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Wolong_Sheng",
            "description": "One of the 'Three Swordsmen' of Taiwanese wuxia alongside Zhuge Qingyun and Sima Ling.",
        },
        {
            "name_chinese": "溫瑞安",
            "name_english": "Wen Ruian",
            "birth_year": 1954,
            "nationality": "Malaysian-Chinese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Wen_Rui%27an",
            "description": "Malaysian-born wuxia writer. Known for the Four Famous Catchers series.",
        },
        {
            "name_chinese": "蕭逸",
            "name_english": "Xiao Yi",
            "real_name_chinese": "蕭敬人",
            "birth_year": 1935,
            "death_year": 2018,
            "nationality": "Taiwanese-American",
            "description": "Taiwanese-American wuxia novelist, one of the most prominent after the big three.",
        },
        {
            "name_chinese": "還珠樓主",
            "name_english": "Huanzhu Louzhu",
            "real_name_chinese": "李壽民",
            "birth_year": 1902,
            "death_year": 1961,
            "nationality": "Chinese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Huanzhu_Louzhu",
            "description": "Pre-eminent wuxia-xianxia writer of the Republic era. Best known for Shu Mountain Swordsman.",
        },
        {
            "name_chinese": "司馬翎",
            "name_english": "Sima Ling",
            "real_name_chinese": "吳思明",
            "birth_year": 1933,
            "death_year": 2015,
            "nationality": "Taiwanese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Sima_Ling",
            "description": "One of the 'Three Swordsmen' of Taiwanese wuxia. Known for intricate plots.",
        },
        {
            "name_chinese": "諸葛青雲",
            "name_english": "Zhuge Qingyun",
            "real_name_chinese": "張建新",
            "birth_year": 1929,
            "death_year": 1996,
            "nationality": "Taiwanese",
            "description": "One of the 'Three Swordsmen' of Taiwanese wuxia alongside Wolong Sheng and Sima Ling.",
        },
        {
            "name_chinese": "王度廬",
            "name_english": "Wang Dulu",
            "birth_year": 1909,
            "death_year": 1977,
            "nationality": "Chinese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Wang_Dulu",
            "description": "Known for the Crane-Iron series. Crouching Tiger, Hidden Dragon is based on his novel.",
        },
        {
            "name_chinese": "雲中岳",
            "name_english": "Yun Zhongyue",
            "birth_year": 1930,
            "death_year": 2014,
            "nationality": "Taiwanese",
            "description": "Prolific Taiwanese wuxia novelist with 64 works in the catalog.",
        },
        {
            "name_chinese": "獨孤紅",
            "name_english": "Dugu Hong",
            "birth_year": 1939,
            "nationality": "Taiwanese",
            "description": "Taiwanese wuxia novelist known for historical wuxia set in the Ming dynasty.",
        },
        {
            "name_chinese": "黃鷹",
            "name_english": "Huang Ying",
            "birth_year": 1956,
            "death_year": 1992,
            "nationality": "Chinese (Hong Kong)",
            "description": "Hong Kong wuxia novelist, also known as a ghostwriter for Gu Long's later works.",
        },
        {
            "name_chinese": "東方玉",
            "name_english": "Dongfang Yu",
            "nationality": "Taiwanese",
            "description": "Taiwanese wuxia novelist.",
        },
        {
            "name_chinese": "柳殘陽",
            "name_english": "Liu Canyang",
            "nationality": "Taiwanese",
            "description": "Taiwanese wuxia novelist known for hard-boiled wuxia style.",
        },
        {
            "name_chinese": "慕容美",
            "name_english": "Murong Mei",
            "nationality": "Taiwanese",
            "description": "Taiwanese wuxia novelist.",
        },
        {
            "name_chinese": "司馬紫煙",
            "name_english": "Sima Ziyan",
            "nationality": "Taiwanese",
            "description": "Taiwanese wuxia novelist.",
        },
        {
            "name_chinese": "陳青雲",
            "name_english": "Chen Qingyun",
            "nationality": "Taiwanese",
            "description": "Taiwanese wuxia novelist known for dark, violent storylines.",
        },
        {
            "name_chinese": "平江不肖生",
            "name_english": "Pingjiang Buxiaosheng",
            "real_name_chinese": "向愷然",
            "birth_year": 1890,
            "death_year": 1957,
            "nationality": "Chinese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Pingjiang_Buxiaosheng",
            "description": "Early 20th-century wuxia pioneer. Known for TheErta and other martial arts novels.",
        },
        {
            "name_chinese": "鄭丰",
            "name_english": "Zheng Feng",
            "nationality": "Taiwanese",
            "description": "Contemporary Taiwanese wuxia novelist.",
        },
        {
            "name_chinese": "白羽",
            "name_english": "Bai Yu",
            "birth_year": 1899,
            "death_year": 1966,
            "nationality": "Chinese",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Gong_Baiyu",
            "description": "Republican-era wuxia writer, one of the 'Three Northern School Masters'. Real name Gong Baiyu.",
        },
    ]

    for a in authors:
        cols = ", ".join(a.keys())
        placeholders = ", ".join(["?"] * len(a))
        try:
            cur.execute(
                f"INSERT INTO authors ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                list(a.values()),
            )
        except Exception as e:
            print(f"  Error inserting author {a['name_chinese']}: {e}")

    conn.commit()
    print(f"Inserted {cur.execute('SELECT COUNT(*) FROM authors').fetchone()[0]} authors")

    # ==================== SERIES ====================

    series_data = [
        # === JIN YONG ===
        {
            "name_english": "Condor Trilogy",
            "name_chinese": "射鵰三部曲",
            "author_chinese": "金庸",
            "series_type": "trilogy",
            "historical_period": "Song-Yuan dynasties (12th-14th century)",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Condor_Trilogy",
            "description": "Jin Yong's most famous trilogy spanning three generations.",
            "works": [
                ("射鵰英雄傳", 1),
                ("神鵰俠侶", 2),
                ("倚天屠龍記", 3),
            ],
        },
        {
            "name_english": "Fox Volant Duology",
            "name_chinese": "雪山飛狐系列",
            "author_chinese": "金庸",
            "series_type": "duology",
            "historical_period": "Qing dynasty (18th century)",
            "description": "Connected stories about the Hu family and the treasure of Li Zicheng.",
            "works": [
                ("雪山飛狐", 1),
                ("飛狐外傳", 2),
            ],
        },
        # === GU LONG ===
        {
            "name_english": "Little Li Flying Dagger Series",
            "name_chinese": "小李飛刀系列",
            "author_chinese": "古龍",
            "series_type": "series",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Xiaoli_Feidao",
            "description": "Gu Long's most famous series about Li Xunhuan and his legendary flying daggers.",
            "works": [
                ("多情劍客無情劍", 1),
                ("邊城浪子", 2),
                ("九月鷹飛", 3),
                ("天涯明月刀", 4),  # also 天涯‧明月‧刀
                ("飛刀，又見飛刀", 5),
            ],
        },
        {
            "name_english": "Chu Liuxiang Series",
            "name_chinese": "楚留香系列",
            "author_chinese": "古龍",
            "series_type": "series",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Chu_Liuxiang",
            "description": "Adventures of the fragrant thief Chu Liuxiang.",
            "works": [
                ("血海飄香", 1),
                ("大沙漠", 2),
                ("畫眉鳥", 3),
                ("蝙蝠傳奇", 4),
                ("鬼戀俠情", 5),
                ("桃花傳奇", 6),
                ("新月傳奇", 7),
                ("午夜蘭花", 8),
            ],
        },
        {
            "name_english": "Lu Xiaofeng Series",
            "name_chinese": "陸小鳳系列",
            "author_chinese": "古龍",
            "series_type": "series",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Lu_Xiaofeng",
            "description": "Mysteries solved by the four-browed Lu Xiaofeng.",
            "works": [
                ("陸小鳳傳奇", 1),
                ("繡花大盜", 2),
                ("決戰前後", 3),
                ("銀鈎賭坊", 4),
                ("幽靈山莊", 5),
                ("鳳舞九天", 6),
                ("劍神一笑", 7),
            ],
        },
        {
            "name_english": "Seven Weapons Series",
            "name_chinese": "七種武器系列",
            "author_chinese": "古龍",
            "series_type": "series",
            "description": "Each novel features a different legendary weapon.",
            "works": [
                ("長生劍", 1),
                ("孔雀翎", 2),
                ("碧玉刀", 3),
                ("多情環", 4),
                ("霸王槍", 5),
                ("離別鉤", 6),
                ("拳頭", 7),
            ],
        },
        {
            "name_english": "The Eleventh Son Series",
            "name_chinese": "蕭十一郎系列",
            "author_chinese": "古龍",
            "series_type": "duology",
            "description": "Story of the lone wolf swordsman Xiao Shiyilang.",
            "works": [
                ("蕭十一郎", 1),
                ("火併蕭十一郎", 2),
            ],
        },
        {
            "name_english": "Six Shocking Tales Series",
            "name_chinese": "驚魂六記系列",
            "author_chinese": "古龍",
            "series_type": "series",
            "description": "Horror-tinged wuxia tales.",
            "works": [
                ("血鸚鵡", 1),
                ("天魔刀", 2),
                ("黑蜥蜴", 3),
                ("水晶人", 4),
                ("粉骷髏", 5),
                ("羅剎女", 6),
                ("無翼蝙蝠", 7),
            ],
        },
        {
            "name_english": "Grand Era of Wuxia Series",
            "name_chinese": "大武俠時代",
            "author_chinese": "古龍",
            "series_type": "series",
            "description": "Late-career connected stories.",
            "works": [
                # These may be sub-stories, might not match DB titles
            ],
        },
        # === LIANG YUSHENG ===
        {
            "name_english": "Tianshan Series",
            "name_chinese": "天山系列",
            "author_chinese": "梁羽生",
            "series_type": "series",
            "historical_period": "Late Ming to mid-Qing (17th-19th century)",
            "description": "Liang Yusheng's largest series spanning 14 novels, centered on the Mount Heaven Sect.",
            "works": [
                ("白髮魔女傳", 1),
                ("塞外奇俠傳", 2),
                ("七劍下天山", 3),
                ("江湖三女俠", 4),
                ("冰魄寒光劍", 5),
                ("冰川天女傳", 6),
                ("雲海玉弓緣", 7),
                ("冰河洗劍錄", 8),
                ("風雷震九州", 9),
                ("俠骨丹心", 10),
                ("游劍江湖", 11),
                ("牧野流星", 12),
                ("彈指驚雷", 13),
                ("絕塞傳烽錄", 14),
            ],
        },
        {
            "name_english": "Pingzong Series",
            "name_chinese": "萍蹤系列",
            "author_chinese": "梁羽生",
            "series_type": "series",
            "historical_period": "Ming dynasty (15th century)",
            "description": "Chronicles successive generations of heroes in the Ming dynasty.",
            "works": [
                ("還劍奇情錄", 1),
                ("萍蹤俠影錄", 2),
                ("散花女俠", 3),
                ("聯劍風雲錄", 4),
                ("武林三絕", 5),
                ("廣陵劍", 6),
            ],
        },
        {
            "name_english": "Datang Trilogy",
            "name_chinese": "大唐三部曲",
            "author_chinese": "梁羽生",
            "series_type": "trilogy",
            "historical_period": "Tang dynasty (8th century, An Lushan Rebellion)",
            "description": "Set during the An Lushan rebellion in the Tang dynasty.",
            "works": [
                ("大唐游俠傳", 1),
                ("龍鳳寶釵緣", 2),
                ("慧劍心魔", 3),
            ],
        },
        {
            "name_english": "Song Dynasty Novels",
            "name_chinese": "宋代系列",
            "author_chinese": "梁羽生",
            "series_type": "series",
            "historical_period": "Song-Jin-Mongol wars (12th-13th century)",
            "description": "Interconnected novels set during the Song-Jin wars and rise of the Mongol Empire.",
            "works": [
                ("狂俠天驕魔女", 1),
                ("飛鳳潛龍", 2),
                ("瀚海雄風", 3),
                ("鳴鏑風雲錄", 4),
                ("風雲雷電", 5),
                ("武林天驕", 6),
            ],
        },
        {
            "name_english": "Boxer Rebellion Duology",
            "name_chinese": "義和團系列",
            "author_chinese": "梁羽生",
            "series_type": "duology",
            "historical_period": "Late Qing dynasty (1899-1901)",
            "description": "Set during the Boxer Rebellion at the turn of the 20th century.",
            "works": [
                ("龍虎鬥京華", 1),
                ("草莽龍蛇傳", 2),
            ],
        },
        {
            "name_english": "Jianwang Duology",
            "name_chinese": "劍網系列",
            "author_chinese": "梁羽生",
            "series_type": "duology",
            "historical_period": "Qing dynasty (18th century)",
            "description": "Two connected novels set in the 18th century Qing dynasty.",
            "works": [
                ("劍網塵絲", 1),
                ("幻劍靈旗", 2),
            ],
        },
        # === WANG DULU ===
        {
            "name_english": "Crane-Iron Series",
            "name_chinese": "鶴鐵五部曲",
            "author_chinese": "王度廬",
            "series_type": "series",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Crane%E2%80%93Iron_Series",
            "description": "Five novels including Crouching Tiger, Hidden Dragon. Known for romantic wuxia.",
        },
    ]

    for s in series_data:
        works = s.pop("works", [])
        cols = ", ".join(s.keys())
        placeholders = ", ".join(["?"] * len(s))
        cur.execute(
            f"INSERT INTO series ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            list(s.values()),
        )
        series_id = cur.execute(
            "SELECT series_id FROM series WHERE name_english = ? AND author_chinese = ?",
            (s["name_english"], s["author_chinese"]),
        ).fetchone()[0]

        # Map works to series
        for title_zh, order in works:
            # Find work_id by Chinese title (try exact match, then LIKE)
            row = cur.execute(
                "SELECT work_id FROM works WHERE title_chinese = ?", (title_zh,)
            ).fetchone()
            if not row:
                row = cur.execute(
                    "SELECT work_id FROM works WHERE title_chinese LIKE ?",
                    (f"%{title_zh}%",),
                ).fetchone()
            if row:
                cur.execute(
                    "INSERT INTO work_series (work_id, series_id, order_in_series) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    (row[0], series_id, order),
                )
            else:
                print(f"  WARNING: No work found for '{title_zh}' in series '{s['name_english']}'")

    conn.commit()

    # Report
    n_series = cur.execute("SELECT COUNT(*) FROM series").fetchone()[0]
    n_mappings = cur.execute("SELECT COUNT(*) FROM work_series").fetchone()[0]
    print(f"\nInserted {n_series} series, {n_mappings} work-series mappings")

    # Show series with work counts
    cur.execute("""
        SELECT s.name_english, s.author_chinese, COUNT(ws.work_id) as works
        FROM series s
        LEFT JOIN work_series ws ON s.series_id = ws.series_id
        GROUP BY s.series_id
        ORDER BY s.author_chinese, s.name_english
    """)
    for row in cur.fetchall():
        print(f"  {row[1]} - {row[0]}: {row[2]} works")

    conn.close()


if __name__ == "__main__":
    populate()
