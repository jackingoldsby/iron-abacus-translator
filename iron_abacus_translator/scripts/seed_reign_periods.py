#!/usr/bin/env python3
"""
Seed the reign_periods table in the works catalog DuckDB.

Phase 1: Structural data — dynasty, reign name, years, emperor, wiki_url.
Phase 2 (optional): Enrich notes from Wikipedia via MediaWiki API.

Usage:
    cd iron_abacus_translator
    python scripts/seed_reign_periods.py                # Phase 1 only
    python scripts/seed_reign_periods.py --enrich       # Phase 1 + Phase 2
    python scripts/seed_reign_periods.py --enrich-only  # Phase 2 only (table must exist)
    python scripts/seed_reign_periods.py --count        # Show row count
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

import httpx

# Resolve imports from workspace root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Phase 1: Structural reign period data
# ─────────────────────────────────────────────────────────────────────

REIGN_PERIODS: List[dict] = [
    # ═══ QIN DYNASTY 秦 (221–206 BCE) ═══
    {"dynasty": "秦", "dynasty_en": "Qin Dynasty", "reign_name_zh": "始皇", "reign_name_py": "Shǐhuáng", "reign_name_en": "Shihuang", "start_year": -221, "end_year": -210, "emperor_zh": "嬴政", "emperor_py": "Yíng Zhèng", "emperor_en": "Qin Shi Huang", "wiki_url": "https://en.wikipedia.org/wiki/Qin_Shi_Huang"},

    # ═══ WESTERN HAN 西漢 (206 BCE – 9 CE) ═══
    {"dynasty": "西漢", "dynasty_en": "Western Han Dynasty", "reign_name_zh": "建元", "reign_name_py": "Jiànyuán", "reign_name_en": "Jianyuan", "start_year": -140, "end_year": -135, "emperor_zh": "劉徹", "emperor_py": "Liú Chè", "emperor_en": "Emperor Wu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Jianyuan_(Western_Han)"},
    {"dynasty": "西漢", "dynasty_en": "Western Han Dynasty", "reign_name_zh": "元光", "reign_name_py": "Yuánguāng", "reign_name_en": "Yuanguang", "start_year": -134, "end_year": -129, "emperor_zh": "劉徹", "emperor_py": "Liú Chè", "emperor_en": "Emperor Wu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Yuanguang"},
    {"dynasty": "西漢", "dynasty_en": "Western Han Dynasty", "reign_name_zh": "元朔", "reign_name_py": "Yuánshuò", "reign_name_en": "Yuanshuo", "start_year": -128, "end_year": -123, "emperor_zh": "劉徹", "emperor_py": "Liú Chè", "emperor_en": "Emperor Wu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Yuanshuo"},
    {"dynasty": "西漢", "dynasty_en": "Western Han Dynasty", "reign_name_zh": "元狩", "reign_name_py": "Yuánshòu", "reign_name_en": "Yuanshou", "start_year": -122, "end_year": -117, "emperor_zh": "劉徹", "emperor_py": "Liú Chè", "emperor_en": "Emperor Wu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Yuanshou_(Western_Han)"},
    {"dynasty": "西漢", "dynasty_en": "Western Han Dynasty", "reign_name_zh": "元鼎", "reign_name_py": "Yuándǐng", "reign_name_en": "Yuanding", "start_year": -116, "end_year": -111, "emperor_zh": "劉徹", "emperor_py": "Liú Chè", "emperor_en": "Emperor Wu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Yuanding"},
    {"dynasty": "西漢", "dynasty_en": "Western Han Dynasty", "reign_name_zh": "元封", "reign_name_py": "Yuánfēng", "reign_name_en": "Yuanfeng", "start_year": -110, "end_year": -105, "emperor_zh": "劉徹", "emperor_py": "Liú Chè", "emperor_en": "Emperor Wu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Yuanfeng_(Western_Han)"},

    # ═══ EASTERN HAN 東漢 (25–220 CE) ═══
    {"dynasty": "東漢", "dynasty_en": "Eastern Han Dynasty", "reign_name_zh": "建武", "reign_name_py": "Jiànwǔ", "reign_name_en": "Jianwu", "start_year": 25, "end_year": 56, "emperor_zh": "劉秀", "emperor_py": "Liú Xiù", "emperor_en": "Emperor Guangwu of Han", "wiki_url": "https://en.wikipedia.org/wiki/Jianwu_(Eastern_Han)"},
    {"dynasty": "東漢", "dynasty_en": "Eastern Han Dynasty", "reign_name_zh": "建安", "reign_name_py": "Jiàn'ān", "reign_name_en": "Jian'an", "start_year": 196, "end_year": 220, "emperor_zh": "劉協", "emperor_py": "Liú Xié", "emperor_en": "Emperor Xian of Han", "wiki_url": "https://en.wikipedia.org/wiki/Jian%27an_(Eastern_Han)"},

    # ═══ THREE KINGDOMS 三國 (220–280) ═══
    {"dynasty": "魏", "dynasty_en": "Cao Wei", "reign_name_zh": "黃初", "reign_name_py": "Huángchū", "reign_name_en": "Huangchu", "start_year": 220, "end_year": 226, "emperor_zh": "曹丕", "emperor_py": "Cáo Pī", "emperor_en": "Emperor Wen of Wei", "wiki_url": "https://en.wikipedia.org/wiki/Huangchu"},
    {"dynasty": "蜀漢", "dynasty_en": "Shu Han", "reign_name_zh": "章武", "reign_name_py": "Zhāngwǔ", "reign_name_en": "Zhangwu", "start_year": 221, "end_year": 223, "emperor_zh": "劉備", "emperor_py": "Liú Bèi", "emperor_en": "Emperor Zhaolie of Shu Han", "wiki_url": "https://en.wikipedia.org/wiki/Zhangwu_(Shu_Han)"},
    {"dynasty": "蜀漢", "dynasty_en": "Shu Han", "reign_name_zh": "建興", "reign_name_py": "Jiànxīng", "reign_name_en": "Jianxing", "start_year": 223, "end_year": 237, "emperor_zh": "劉禪", "emperor_py": "Liú Shàn", "emperor_en": "Liu Shan", "wiki_url": "https://en.wikipedia.org/wiki/Jianxing_(Shu_Han)"},

    # ═══ JIN DYNASTY 晉 (266–420) ═══
    {"dynasty": "西晉", "dynasty_en": "Western Jin Dynasty", "reign_name_zh": "泰始", "reign_name_py": "Tàishǐ", "reign_name_en": "Taishi", "start_year": 265, "end_year": 274, "emperor_zh": "司馬炎", "emperor_py": "Sīmǎ Yán", "emperor_en": "Emperor Wu of Jin", "wiki_url": "https://en.wikipedia.org/wiki/Taishi_(Jin_dynasty)"},
    {"dynasty": "東晉", "dynasty_en": "Eastern Jin Dynasty", "reign_name_zh": "建武", "reign_name_py": "Jiànwǔ", "reign_name_en": "Jianwu", "start_year": 317, "end_year": 318, "emperor_zh": "司馬睿", "emperor_py": "Sīmǎ Ruì", "emperor_en": "Emperor Yuan of Jin", "wiki_url": "https://en.wikipedia.org/wiki/Jianwu_(Eastern_Jin)"},

    # ═══ SUI DYNASTY 隋 (581–618) ═══
    {"dynasty": "隋", "dynasty_en": "Sui Dynasty", "reign_name_zh": "開皇", "reign_name_py": "Kāihuáng", "reign_name_en": "Kaihuang", "start_year": 581, "end_year": 600, "emperor_zh": "楊堅", "emperor_py": "Yáng Jiān", "emperor_en": "Emperor Wen of Sui", "wiki_url": "https://en.wikipedia.org/wiki/Kaihuang"},
    {"dynasty": "隋", "dynasty_en": "Sui Dynasty", "reign_name_zh": "大業", "reign_name_py": "Dàyè", "reign_name_en": "Daye", "start_year": 605, "end_year": 618, "emperor_zh": "楊廣", "emperor_py": "Yáng Guǎng", "emperor_en": "Emperor Yang of Sui", "wiki_url": "https://en.wikipedia.org/wiki/Daye_(Sui_dynasty)"},

    # ═══ TANG DYNASTY 唐 (618–907) ═══
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "武德", "reign_name_py": "Wǔdé", "reign_name_en": "Wude", "start_year": 618, "end_year": 626, "emperor_zh": "李淵", "emperor_py": "Lǐ Yuān", "emperor_en": "Emperor Gaozu of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Wude_(era)"},
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "貞觀", "reign_name_py": "Zhēnguān", "reign_name_en": "Zhenguan", "start_year": 627, "end_year": 649, "emperor_zh": "李世民", "emperor_py": "Lǐ Shìmín", "emperor_en": "Emperor Taizong of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Zhenguan_(era)"},
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "永徽", "reign_name_py": "Yǒnghuī", "reign_name_en": "Yonghui", "start_year": 650, "end_year": 655, "emperor_zh": "李治", "emperor_py": "Lǐ Zhì", "emperor_en": "Emperor Gaozong of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Yonghui"},
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "開元", "reign_name_py": "Kāiyuán", "reign_name_en": "Kaiyuan", "start_year": 713, "end_year": 741, "emperor_zh": "李隆基", "emperor_py": "Lǐ Lóngjī", "emperor_en": "Emperor Xuanzong of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Kaiyuan"},
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "天寶", "reign_name_py": "Tiānbǎo", "reign_name_en": "Tianbao", "start_year": 742, "end_year": 756, "emperor_zh": "李隆基", "emperor_py": "Lǐ Lóngjī", "emperor_en": "Emperor Xuanzong of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Tianbao_(Tang_dynasty)"},
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "至德", "reign_name_py": "Zhìdé", "reign_name_en": "Zhide", "start_year": 756, "end_year": 758, "emperor_zh": "李亨", "emperor_py": "Lǐ Hēng", "emperor_en": "Emperor Suzong of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Zhide_(Tang_dynasty)"},
    {"dynasty": "唐", "dynasty_en": "Tang Dynasty", "reign_name_zh": "元和", "reign_name_py": "Yuánhé", "reign_name_en": "Yuanhe", "start_year": 806, "end_year": 820, "emperor_zh": "李純", "emperor_py": "Lǐ Chún", "emperor_en": "Emperor Xianzong of Tang", "wiki_url": "https://en.wikipedia.org/wiki/Yuanhe_(Tang_dynasty)"},

    # ═══ FIVE DYNASTIES 五代 (907–960) ═══
    {"dynasty": "後梁", "dynasty_en": "Later Liang", "reign_name_zh": "開平", "reign_name_py": "Kāipíng", "reign_name_en": "Kaiping", "start_year": 907, "end_year": 911, "emperor_zh": "朱溫", "emperor_py": "Zhū Wēn", "emperor_en": "Emperor Taizu of Later Liang", "wiki_url": "https://en.wikipedia.org/wiki/Kaiping_(Later_Liang)"},
    {"dynasty": "後周", "dynasty_en": "Later Zhou", "reign_name_zh": "顯德", "reign_name_py": "Xiǎndé", "reign_name_en": "Xiande", "start_year": 954, "end_year": 960, "emperor_zh": "柴榮", "emperor_py": "Chái Róng", "emperor_en": "Emperor Shizong of Later Zhou", "wiki_url": "https://en.wikipedia.org/wiki/Xiande"},

    # ═══ NORTHERN SONG 北宋 (960–1127) ═══
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "建隆", "reign_name_py": "Jiànlóng", "reign_name_en": "Jianlong", "start_year": 960, "end_year": 963, "emperor_zh": "趙匡胤", "emperor_py": "Zhào Kuāngyìn", "emperor_en": "Emperor Taizu of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jianlong"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "乾德", "reign_name_py": "Qiándé", "reign_name_en": "Qiande", "start_year": 963, "end_year": 968, "emperor_zh": "趙匡胤", "emperor_py": "Zhào Kuāngyìn", "emperor_en": "Emperor Taizu of Song", "wiki_url": "https://en.wikipedia.org/wiki/Qiande_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "開寶", "reign_name_py": "Kāibǎo", "reign_name_en": "Kaibao", "start_year": 968, "end_year": 976, "emperor_zh": "趙匡胤", "emperor_py": "Zhào Kuāngyìn", "emperor_en": "Emperor Taizu of Song", "wiki_url": "https://en.wikipedia.org/wiki/Kaibao"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "太平興國", "reign_name_py": "Tàipíng Xīngguó", "reign_name_en": "Taiping Xingguo", "start_year": 976, "end_year": 984, "emperor_zh": "趙光義", "emperor_py": "Zhào Guāngyì", "emperor_en": "Emperor Taizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Taiping_Xingguo"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "雍熙", "reign_name_py": "Yōngxī", "reign_name_en": "Yongxi", "start_year": 984, "end_year": 987, "emperor_zh": "趙光義", "emperor_py": "Zhào Guāngyì", "emperor_en": "Emperor Taizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Yongxi_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "淳化", "reign_name_py": "Chúnhuà", "reign_name_en": "Chunhua", "start_year": 990, "end_year": 994, "emperor_zh": "趙光義", "emperor_py": "Zhào Guāngyì", "emperor_en": "Emperor Taizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Chunhua_(era)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "至道", "reign_name_py": "Zhìdào", "reign_name_en": "Zhidao", "start_year": 995, "end_year": 997, "emperor_zh": "趙光義", "emperor_py": "Zhào Guāngyì", "emperor_en": "Emperor Taizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Zhidao_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "咸平", "reign_name_py": "Xiánpíng", "reign_name_en": "Xianping", "start_year": 998, "end_year": 1003, "emperor_zh": "趙恆", "emperor_py": "Zhào Héng", "emperor_en": "Emperor Zhenzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Xianping"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "景德", "reign_name_py": "Jǐngdé", "reign_name_en": "Jingde", "start_year": 1004, "end_year": 1007, "emperor_zh": "趙恆", "emperor_py": "Zhào Héng", "emperor_en": "Emperor Zhenzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jingde_(era)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "大中祥符", "reign_name_py": "Dàzhōng Xiángfú", "reign_name_en": "Dazhong Xiangfu", "start_year": 1008, "end_year": 1016, "emperor_zh": "趙恆", "emperor_py": "Zhào Héng", "emperor_en": "Emperor Zhenzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Dazhong_Xiangfu"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "天禧", "reign_name_py": "Tiānxǐ", "reign_name_en": "Tianxi", "start_year": 1017, "end_year": 1021, "emperor_zh": "趙恆", "emperor_py": "Zhào Héng", "emperor_en": "Emperor Zhenzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Tianxi_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "天聖", "reign_name_py": "Tiānshèng", "reign_name_en": "Tiansheng", "start_year": 1023, "end_year": 1032, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Tiansheng"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "明道", "reign_name_py": "Míngdào", "reign_name_en": "Mingdao", "start_year": 1032, "end_year": 1033, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Mingdao_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "景祐", "reign_name_py": "Jǐngyòu", "reign_name_en": "Jingyou", "start_year": 1034, "end_year": 1038, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jingyou_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "寶元", "reign_name_py": "Bǎoyuán", "reign_name_en": "Baoyuan", "start_year": 1038, "end_year": 1040, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Baoyuan_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "慶曆", "reign_name_py": "Qìnglì", "reign_name_en": "Qingli", "start_year": 1041, "end_year": 1048, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Qingli"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "皇祐", "reign_name_py": "Huángyòu", "reign_name_en": "Huangyou", "start_year": 1049, "end_year": 1054, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Huangyou"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "嘉祐", "reign_name_py": "Jiāyòu", "reign_name_en": "Jiayou", "start_year": 1056, "end_year": 1063, "emperor_zh": "趙禎", "emperor_py": "Zhào Zhēn", "emperor_en": "Emperor Renzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jiayou_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "治平", "reign_name_py": "Zhìpíng", "reign_name_en": "Zhiping", "start_year": 1064, "end_year": 1067, "emperor_zh": "趙曙", "emperor_py": "Zhào Shù", "emperor_en": "Emperor Yingzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Zhiping_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "熙寧", "reign_name_py": "Xīníng", "reign_name_en": "Xining", "start_year": 1068, "end_year": 1077, "emperor_zh": "趙頊", "emperor_py": "Zhào Xū", "emperor_en": "Emperor Shenzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Xining_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "元豐", "reign_name_py": "Yuánfēng", "reign_name_en": "Yuanfeng", "start_year": 1078, "end_year": 1085, "emperor_zh": "趙頊", "emperor_py": "Zhào Xū", "emperor_en": "Emperor Shenzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Yuanfeng_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "元祐", "reign_name_py": "Yuányòu", "reign_name_en": "Yuanyou", "start_year": 1086, "end_year": 1094, "emperor_zh": "趙煦", "emperor_py": "Zhào Xù", "emperor_en": "Emperor Zhezong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Yuanyou_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "紹聖", "reign_name_py": "Shàoshèng", "reign_name_en": "Shaosheng", "start_year": 1094, "end_year": 1098, "emperor_zh": "趙煦", "emperor_py": "Zhào Xù", "emperor_en": "Emperor Zhezong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Shaosheng"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "元符", "reign_name_py": "Yuánfú", "reign_name_en": "Yuanfu", "start_year": 1098, "end_year": 1100, "emperor_zh": "趙煦", "emperor_py": "Zhào Xù", "emperor_en": "Emperor Zhezong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Yuanfu"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "建中靖國", "reign_name_py": "Jiànzhōng Jìngguó", "reign_name_en": "Jianzhong Jingguo", "start_year": 1101, "end_year": 1101, "emperor_zh": "趙佶", "emperor_py": "Zhào Jí", "emperor_en": "Emperor Huizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jianzhong_Jingguo"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "崇寧", "reign_name_py": "Chóngníng", "reign_name_en": "Chongning", "start_year": 1102, "end_year": 1106, "emperor_zh": "趙佶", "emperor_py": "Zhào Jí", "emperor_en": "Emperor Huizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Chongning"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "大觀", "reign_name_py": "Dàguān", "reign_name_en": "Daguan", "start_year": 1107, "end_year": 1110, "emperor_zh": "趙佶", "emperor_py": "Zhào Jí", "emperor_en": "Emperor Huizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Daguan_(Song_dynasty)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "政和", "reign_name_py": "Zhènghé", "reign_name_en": "Zhenghe", "start_year": 1111, "end_year": 1118, "emperor_zh": "趙佶", "emperor_py": "Zhào Jí", "emperor_en": "Emperor Huizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Zhenghe_(era)"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "重和", "reign_name_py": "Chónghé", "reign_name_en": "Chonghe", "start_year": 1118, "end_year": 1119, "emperor_zh": "趙佶", "emperor_py": "Zhào Jí", "emperor_en": "Emperor Huizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Chonghe"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "宣和", "reign_name_py": "Xuānhé", "reign_name_en": "Xuanhe", "start_year": 1119, "end_year": 1125, "emperor_zh": "趙佶", "emperor_py": "Zhào Jí", "emperor_en": "Emperor Huizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Xuanhe"},
    {"dynasty": "北宋", "dynasty_en": "Northern Song Dynasty", "reign_name_zh": "靖康", "reign_name_py": "Jìngkāng", "reign_name_en": "Jingkang", "start_year": 1126, "end_year": 1127, "emperor_zh": "趙桓", "emperor_py": "Zhào Huán", "emperor_en": "Emperor Qinzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jingkang"},

    # ═══ SOUTHERN SONG 南宋 (1127–1279) ═══
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "建炎", "reign_name_py": "Jiànyán", "reign_name_en": "Jianyan", "start_year": 1127, "end_year": 1130, "emperor_zh": "趙構", "emperor_py": "Zhào Gòu", "emperor_en": "Emperor Gaozong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jianyan_(Song_dynasty)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "紹興", "reign_name_py": "Shàoxīng", "reign_name_en": "Shaoxing", "start_year": 1131, "end_year": 1162, "emperor_zh": "趙構", "emperor_py": "Zhào Gòu", "emperor_en": "Emperor Gaozong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Shaoxing_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "隆興", "reign_name_py": "Lóngxīng", "reign_name_en": "Longxing", "start_year": 1163, "end_year": 1164, "emperor_zh": "趙昚", "emperor_py": "Zhào Shèn", "emperor_en": "Emperor Xiaozong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Longxing_(Southern_Song)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "乾道", "reign_name_py": "Qiándào", "reign_name_en": "Qiandao", "start_year": 1165, "end_year": 1173, "emperor_zh": "趙昚", "emperor_py": "Zhào Shèn", "emperor_en": "Emperor Xiaozong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Qiandao_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "淳熙", "reign_name_py": "Chúnxī", "reign_name_en": "Chunxi", "start_year": 1174, "end_year": 1189, "emperor_zh": "趙昚", "emperor_py": "Zhào Shèn", "emperor_en": "Emperor Xiaozong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Chunxi_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "紹熙", "reign_name_py": "Shàoxī", "reign_name_en": "Shaoxi", "start_year": 1190, "end_year": 1194, "emperor_zh": "趙惇", "emperor_py": "Zhào Dūn", "emperor_en": "Emperor Guangzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Shaoxi_(Song_dynasty)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "慶元", "reign_name_py": "Qìngyuán", "reign_name_en": "Qingyuan", "start_year": 1195, "end_year": 1200, "emperor_zh": "趙擴", "emperor_py": "Zhào Kuò", "emperor_en": "Emperor Ningzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Qingyuan_(Song_dynasty)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "嘉泰", "reign_name_py": "Jiātài", "reign_name_en": "Jiatai", "start_year": 1201, "end_year": 1204, "emperor_zh": "趙擴", "emperor_py": "Zhào Kuò", "emperor_en": "Emperor Ningzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jiatai_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "開禧", "reign_name_py": "Kāixǐ", "reign_name_en": "Kaixi", "start_year": 1205, "end_year": 1207, "emperor_zh": "趙擴", "emperor_py": "Zhào Kuò", "emperor_en": "Emperor Ningzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Kaixi_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "嘉定", "reign_name_py": "Jiādìng", "reign_name_en": "Jiading", "start_year": 1208, "end_year": 1224, "emperor_zh": "趙擴", "emperor_py": "Zhào Kuò", "emperor_en": "Emperor Ningzong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jiading_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "寶慶", "reign_name_py": "Bǎoqìng", "reign_name_en": "Baoqing", "start_year": 1225, "end_year": 1227, "emperor_zh": "趙昀", "emperor_py": "Zhào Yún", "emperor_en": "Emperor Lizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Baoqing_(Song_dynasty)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "端平", "reign_name_py": "Duānpíng", "reign_name_en": "Duanping", "start_year": 1234, "end_year": 1236, "emperor_zh": "趙昀", "emperor_py": "Zhào Yún", "emperor_en": "Emperor Lizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Duanping"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "嘉熙", "reign_name_py": "Jiāxī", "reign_name_en": "Jiaxi", "start_year": 1237, "end_year": 1240, "emperor_zh": "趙昀", "emperor_py": "Zhào Yún", "emperor_en": "Emperor Lizong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Jiaxi_(era)"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "德祐", "reign_name_py": "Déyòu", "reign_name_en": "Deyou", "start_year": 1275, "end_year": 1276, "emperor_zh": "趙㬎", "emperor_py": "Zhào Xiǎn", "emperor_en": "Emperor Gong of Song", "wiki_url": "https://en.wikipedia.org/wiki/Deyou"},
    {"dynasty": "南宋", "dynasty_en": "Southern Song Dynasty", "reign_name_zh": "祥興", "reign_name_py": "Xiángxīng", "reign_name_en": "Xiangxing", "start_year": 1278, "end_year": 1279, "emperor_zh": "趙昺", "emperor_py": "Zhào Bǐng", "emperor_en": "Emperor Bing of Song", "wiki_url": "https://en.wikipedia.org/wiki/Xiangxing"},

    # ═══ YUAN DYNASTY 元 (1271–1368) ═══
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "至元", "reign_name_py": "Zhìyuán", "reign_name_en": "Zhiyuan", "start_year": 1264, "end_year": 1294, "emperor_zh": "忽必烈", "emperor_py": "Hūbìliè", "emperor_en": "Kublai Khan", "wiki_url": "https://en.wikipedia.org/wiki/Zhiyuan_(Kublai_Khan)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "元貞", "reign_name_py": "Yuánzhēn", "reign_name_en": "Yuanzhen", "start_year": 1295, "end_year": 1297, "emperor_zh": "鐵穆耳", "emperor_py": "Tiěmùěr", "emperor_en": "Emperor Chengzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Yuanzhen_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "大德", "reign_name_py": "Dàdé", "reign_name_en": "Dade", "start_year": 1297, "end_year": 1307, "emperor_zh": "鐵穆耳", "emperor_py": "Tiěmùěr", "emperor_en": "Emperor Chengzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Dade_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "至大", "reign_name_py": "Zhìdà", "reign_name_en": "Zhida", "start_year": 1308, "end_year": 1311, "emperor_zh": "海山", "emperor_py": "Hǎishān", "emperor_en": "Emperor Wuzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Zhida_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "皇慶", "reign_name_py": "Huángqìng", "reign_name_en": "Huangqing", "start_year": 1312, "end_year": 1313, "emperor_zh": "愛育黎拔力八達", "emperor_py": "Àiyùlí Bálìbādá", "emperor_en": "Emperor Renzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Huangqing_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "延祐", "reign_name_py": "Yányòu", "reign_name_en": "Yanyou", "start_year": 1314, "end_year": 1320, "emperor_zh": "愛育黎拔力八達", "emperor_py": "Àiyùlí Bálìbādá", "emperor_en": "Emperor Renzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Yanyou_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "至治", "reign_name_py": "Zhìzhì", "reign_name_en": "Zhizhi", "start_year": 1321, "end_year": 1323, "emperor_zh": "碩德八剌", "emperor_py": "Shuòdébālà", "emperor_en": "Emperor Yingzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Zhizhi_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "泰定", "reign_name_py": "Tàidìng", "reign_name_en": "Taiding", "start_year": 1324, "end_year": 1328, "emperor_zh": "也孫鐵木兒", "emperor_py": "Yěsūn Tiěmùér", "emperor_en": "Yesün Temür", "wiki_url": "https://en.wikipedia.org/wiki/Taiding_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "天曆", "reign_name_py": "Tiānlì", "reign_name_en": "Tianli", "start_year": 1328, "end_year": 1330, "emperor_zh": "圖帖睦爾", "emperor_py": "Tútiēmùěr", "emperor_en": "Emperor Wenzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Tianli_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "至順", "reign_name_py": "Zhìshùn", "reign_name_en": "Zhishun", "start_year": 1330, "end_year": 1333, "emperor_zh": "圖帖睦爾", "emperor_py": "Tútiēmùěr", "emperor_en": "Emperor Wenzong of Yuan", "wiki_url": "https://en.wikipedia.org/wiki/Zhishun"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "元統", "reign_name_py": "Yuántǒng", "reign_name_en": "Yuantong", "start_year": 1333, "end_year": 1335, "emperor_zh": "妥懽帖睦爾", "emperor_py": "Tuǒhuān Tiēmùěr", "emperor_en": "Emperor Huizong of Yuan (Toghon Temür)", "wiki_url": "https://en.wikipedia.org/wiki/Yuantong_(Yuan_dynasty)"},
    {"dynasty": "元", "dynasty_en": "Yuan Dynasty", "reign_name_zh": "至正", "reign_name_py": "Zhìzhèng", "reign_name_en": "Zhizheng", "start_year": 1341, "end_year": 1370, "emperor_zh": "妥懽帖睦爾", "emperor_py": "Tuǒhuān Tiēmùěr", "emperor_en": "Emperor Huizong of Yuan (Toghon Temür)", "wiki_url": "https://en.wikipedia.org/wiki/Zhizheng"},

    # ═══ MING DYNASTY 明 (1368–1644) ═══
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "洪武", "reign_name_py": "Hóngwǔ", "reign_name_en": "Hongwu", "start_year": 1368, "end_year": 1398, "emperor_zh": "朱元璋", "emperor_py": "Zhū Yuánzhāng", "emperor_en": "Hongwu Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Hongwu_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "建文", "reign_name_py": "Jiànwén", "reign_name_en": "Jianwen", "start_year": 1399, "end_year": 1402, "emperor_zh": "朱允炆", "emperor_py": "Zhū Yǔnwén", "emperor_en": "Jianwen Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Jianwen_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "永樂", "reign_name_py": "Yǒnglè", "reign_name_en": "Yongle", "start_year": 1403, "end_year": 1424, "emperor_zh": "朱棣", "emperor_py": "Zhū Dì", "emperor_en": "Yongle Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Yongle_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "洪熙", "reign_name_py": "Hóngxī", "reign_name_en": "Hongxi", "start_year": 1425, "end_year": 1425, "emperor_zh": "朱高熾", "emperor_py": "Zhū Gāochì", "emperor_en": "Hongxi Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Hongxi_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "宣德", "reign_name_py": "Xuāndé", "reign_name_en": "Xuande", "start_year": 1426, "end_year": 1435, "emperor_zh": "朱瞻基", "emperor_py": "Zhū Zhānjī", "emperor_en": "Xuande Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Xuande_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "正統", "reign_name_py": "Zhèngtǒng", "reign_name_en": "Zhengtong", "start_year": 1436, "end_year": 1449, "emperor_zh": "朱祁鎮", "emperor_py": "Zhū Qízhèn", "emperor_en": "Zhengtong Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Zhengtong_(era)"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "景泰", "reign_name_py": "Jǐngtài", "reign_name_en": "Jingtai", "start_year": 1450, "end_year": 1457, "emperor_zh": "朱祁鈺", "emperor_py": "Zhū Qíyù", "emperor_en": "Jingtai Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Jingtai_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "天順", "reign_name_py": "Tiānshùn", "reign_name_en": "Tianshun", "start_year": 1457, "end_year": 1464, "emperor_zh": "朱祁鎮", "emperor_py": "Zhū Qízhèn", "emperor_en": "Zhengtong Emperor (restored)", "wiki_url": "https://en.wikipedia.org/wiki/Tianshun_(Ming_dynasty)"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "成化", "reign_name_py": "Chénghuà", "reign_name_en": "Chenghua", "start_year": 1465, "end_year": 1487, "emperor_zh": "朱見深", "emperor_py": "Zhū Jiànshēn", "emperor_en": "Chenghua Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Chenghua_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "弘治", "reign_name_py": "Hóngzhì", "reign_name_en": "Hongzhi", "start_year": 1488, "end_year": 1505, "emperor_zh": "朱祐樘", "emperor_py": "Zhū Yòuchēng", "emperor_en": "Hongzhi Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Hongzhi_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "正德", "reign_name_py": "Zhèngdé", "reign_name_en": "Zhengde", "start_year": 1506, "end_year": 1521, "emperor_zh": "朱厚照", "emperor_py": "Zhū Hòuzhào", "emperor_en": "Zhengde Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Zhengde_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "嘉靖", "reign_name_py": "Jiājìng", "reign_name_en": "Jiajing", "start_year": 1522, "end_year": 1566, "emperor_zh": "朱厚熜", "emperor_py": "Zhū Hòucōng", "emperor_en": "Jiajing Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Jiajing_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "隆慶", "reign_name_py": "Lóngqìng", "reign_name_en": "Longqing", "start_year": 1567, "end_year": 1572, "emperor_zh": "朱載坖", "emperor_py": "Zhū Zǎijì", "emperor_en": "Longqing Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Longqing_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "萬曆", "reign_name_py": "Wànlì", "reign_name_en": "Wanli", "start_year": 1573, "end_year": 1620, "emperor_zh": "朱翊鈞", "emperor_py": "Zhū Yìjūn", "emperor_en": "Wanli Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Wanli_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "泰昌", "reign_name_py": "Tàichāng", "reign_name_en": "Taichang", "start_year": 1620, "end_year": 1620, "emperor_zh": "朱常洛", "emperor_py": "Zhū Chángluò", "emperor_en": "Taichang Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Taichang_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "天啟", "reign_name_py": "Tiānqǐ", "reign_name_en": "Tianqi", "start_year": 1621, "end_year": 1627, "emperor_zh": "朱由校", "emperor_py": "Zhū Yóuxiào", "emperor_en": "Tianqi Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Tianqi_Emperor"},
    {"dynasty": "明", "dynasty_en": "Ming Dynasty", "reign_name_zh": "崇禎", "reign_name_py": "Chóngzhēn", "reign_name_en": "Chongzhen", "start_year": 1628, "end_year": 1644, "emperor_zh": "朱由檢", "emperor_py": "Zhū Yóujiǎn", "emperor_en": "Chongzhen Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Chongzhen_Emperor"},

    # ═══ QING DYNASTY 清 (1644–1912) ═══
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "順治", "reign_name_py": "Shùnzhì", "reign_name_en": "Shunzhi", "start_year": 1644, "end_year": 1661, "emperor_zh": "愛新覺羅·福臨", "emperor_py": "Àixīnjuéluó Fúlín", "emperor_en": "Shunzhi Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Shunzhi_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "康熙", "reign_name_py": "Kāngxī", "reign_name_en": "Kangxi", "start_year": 1662, "end_year": 1722, "emperor_zh": "愛新覺羅·玄燁", "emperor_py": "Àixīnjuéluó Xuányè", "emperor_en": "Kangxi Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Kangxi_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "雍正", "reign_name_py": "Yōngzhèng", "reign_name_en": "Yongzheng", "start_year": 1723, "end_year": 1735, "emperor_zh": "愛新覺羅·胤禛", "emperor_py": "Àixīnjuéluó Yìnzhēn", "emperor_en": "Yongzheng Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Yongzheng_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "乾隆", "reign_name_py": "Qiánlóng", "reign_name_en": "Qianlong", "start_year": 1736, "end_year": 1795, "emperor_zh": "愛新覺羅·弘曆", "emperor_py": "Àixīnjuéluó Hónglì", "emperor_en": "Qianlong Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Qianlong_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "嘉慶", "reign_name_py": "Jiāqìng", "reign_name_en": "Jiaqing", "start_year": 1796, "end_year": 1820, "emperor_zh": "愛新覺羅·顒琰", "emperor_py": "Àixīnjuéluó Yóngyǎn", "emperor_en": "Jiaqing Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Jiaqing_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "道光", "reign_name_py": "Dàoguāng", "reign_name_en": "Daoguang", "start_year": 1821, "end_year": 1850, "emperor_zh": "愛新覺羅·旻寧", "emperor_py": "Àixīnjuéluó Mínníng", "emperor_en": "Daoguang Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Daoguang_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "咸豐", "reign_name_py": "Xiánfēng", "reign_name_en": "Xianfeng", "start_year": 1851, "end_year": 1861, "emperor_zh": "愛新覺羅·奕詝", "emperor_py": "Àixīnjuéluó Yìzhǔ", "emperor_en": "Xianfeng Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Xianfeng_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "同治", "reign_name_py": "Tóngzhì", "reign_name_en": "Tongzhi", "start_year": 1862, "end_year": 1874, "emperor_zh": "愛新覺羅·載淳", "emperor_py": "Àixīnjuéluó Zǎichún", "emperor_en": "Tongzhi Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Tongzhi_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "光緒", "reign_name_py": "Guāngxù", "reign_name_en": "Guangxu", "start_year": 1875, "end_year": 1908, "emperor_zh": "愛新覺羅·載湉", "emperor_py": "Àixīnjuéluó Zǎitián", "emperor_en": "Guangxu Emperor", "wiki_url": "https://en.wikipedia.org/wiki/Guangxu_Emperor"},
    {"dynasty": "清", "dynasty_en": "Qing Dynasty", "reign_name_zh": "宣統", "reign_name_py": "Xuāntǒng", "reign_name_en": "Xuantong", "start_year": 1909, "end_year": 1912, "emperor_zh": "愛新覺羅·溥儀", "emperor_py": "Àixīnjuéluó Pǔyí", "emperor_en": "Xuantong Emperor (Puyi)", "wiki_url": "https://en.wikipedia.org/wiki/Xuantong_Emperor"},
]


# ─────────────────────────────────────────────────────────────────────
# Table creation & seeding
# ─────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reign_periods (
    dynasty         VARCHAR NOT NULL,
    dynasty_en      VARCHAR NOT NULL,
    reign_name_zh   VARCHAR NOT NULL,
    reign_name_py   VARCHAR NOT NULL,
    reign_name_en   VARCHAR,
    start_year      INTEGER NOT NULL,
    end_year        INTEGER NOT NULL,
    emperor_zh      VARCHAR,
    emperor_py      VARCHAR,
    emperor_en      VARCHAR,
    notes           VARCHAR,
    wiki_url        VARCHAR,
    PRIMARY KEY (dynasty, reign_name_zh)
);
"""


def get_db_path() -> Path:
    """Resolve the catalog DuckDB path."""
    default = Path("/Users/jacki/project_files/translation_project/db/works_translator.duckdb")
    if default.exists():
        return default
    # Fallback: try environment config
    try:
        from utils.environment_config import get_or_create_config
        return get_or_create_config().catalog_path
    except Exception:
        return default


def seed_table(db_path: Path, force: bool = False) -> int:
    """Create and populate the reign_periods table.

    Returns the number of rows inserted.
    """
    import duckdb

    conn = duckdb.connect(str(db_path))

    if force:
        conn.execute("DROP TABLE IF EXISTS reign_periods")

    conn.execute(CREATE_TABLE_SQL)

    # Check existing row count
    existing = conn.execute("SELECT COUNT(*) FROM reign_periods").fetchone()[0]
    if existing > 0 and not force:
        logger.info(f"reign_periods already has {existing} rows. Use --force to replace.")
        conn.close()
        return existing

    # Insert all rows
    inserted = 0
    for row in REIGN_PERIODS:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO reign_periods "
                "(dynasty, dynasty_en, reign_name_zh, reign_name_py, reign_name_en, "
                "start_year, end_year, emperor_zh, emperor_py, emperor_en, notes, wiki_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    row["dynasty"], row["dynasty_en"], row["reign_name_zh"],
                    row["reign_name_py"], row.get("reign_name_en", ""),
                    row["start_year"], row["end_year"],
                    row.get("emperor_zh", ""), row.get("emperor_py", ""),
                    row.get("emperor_en", ""), row.get("notes", ""),
                    row.get("wiki_url", ""),
                ]
            )
            inserted += 1
        except Exception as e:
            logger.error(f"Failed to insert {row['reign_name_zh']}: {e}")

    conn.close()
    logger.info(f"Inserted {inserted} reign periods into {db_path}")
    return inserted


# ─────────────────────────────────────────────────────────────────────
# Phase 2: Wikipedia enrichment
# ─────────────────────────────────────────────────────────────────────

MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"


def _extract_title_from_url(url: str) -> Optional[str]:
    """Extract Wikipedia article title from URL."""
    if not url:
        return None
    # https://en.wikipedia.org/wiki/Kangxi_Emperor → Kangxi_Emperor
    if "/wiki/" in url:
        return url.split("/wiki/")[-1]
    return None


def fetch_wikipedia_intro(title: str) -> Optional[str]:
    """Fetch the intro extract of a Wikipedia article via MediaWiki API.

    Returns plain text intro, or None on failure.
    """
    params = {
        "action": "query",
        "titles": title.replace("_", " "),
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "format": "json",
    }

    try:
        resp = httpx.get(MEDIAWIKI_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                return None
            extract = page.get("extract", "")
            if extract:
                # Truncate to ~500 chars for notes field
                if len(extract) > 500:
                    # Cut at last sentence boundary within 500 chars
                    cut = extract[:500]
                    last_period = cut.rfind(". ")
                    if last_period > 200:
                        extract = cut[:last_period + 1]
                    else:
                        extract = cut + "..."
                return extract.strip()
    except Exception as e:
        logger.warning(f"Wikipedia fetch failed for '{title}': {e}")

    return None


def enrich_notes(db_path: Path, delay: float = 0.5) -> int:
    """Fetch Wikipedia intros and populate the notes field.

    Only enriches rows where notes is NULL or empty.
    Returns count of enriched rows.
    """
    import duckdb

    conn = duckdb.connect(str(db_path))

    rows = conn.execute(
        "SELECT dynasty, reign_name_zh, wiki_url FROM reign_periods "
        "WHERE notes IS NULL OR notes = '' "
        "ORDER BY start_year"
    ).fetchall()

    if not rows:
        logger.info("All rows already have notes — nothing to enrich.")
        conn.close()
        return 0

    logger.info(f"Enriching {len(rows)} rows from Wikipedia...")
    enriched = 0

    for dynasty, reign_zh, wiki_url in rows:
        title = _extract_title_from_url(wiki_url)
        if not title:
            continue

        intro = fetch_wikipedia_intro(title)
        if intro:
            conn.execute(
                "UPDATE reign_periods SET notes = ? WHERE dynasty = ? AND reign_name_zh = ?",
                [intro, dynasty, reign_zh],
            )
            enriched += 1
            logger.debug(f"  {reign_zh}: {len(intro)} chars")

        time.sleep(delay)  # Be polite to Wikipedia

    conn.close()
    logger.info(f"Enriched {enriched}/{len(rows)} reign periods with Wikipedia notes")
    return enriched


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed reign_periods table in DuckDB")
    parser.add_argument("--db", type=Path, help="DuckDB path (default: auto-detect)")
    parser.add_argument("--force", action="store_true", help="Drop and recreate table")
    parser.add_argument("--enrich", action="store_true", help="Also fetch Wikipedia notes (Phase 2)")
    parser.add_argument("--enrich-only", action="store_true", help="Only fetch Wikipedia notes (table must exist)")
    parser.add_argument("--count", action="store_true", help="Show row count and exit")
    args = parser.parse_args()

    db_path = args.db or get_db_path()
    logger.info(f"Database: {db_path}")

    if args.count:
        import duckdb
        conn = duckdb.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM reign_periods").fetchone()[0]
            print(f"reign_periods: {count} rows")
            # Show dynasty breakdown
            dynasties = conn.execute(
                "SELECT dynasty_en, COUNT(*) as cnt FROM reign_periods "
                "GROUP BY dynasty_en ORDER BY MIN(start_year)"
            ).fetchall()
            for dynasty_en, cnt in dynasties:
                print(f"  {dynasty_en}: {cnt}")
        except Exception as e:
            print(f"Error: {e}")
        conn.close()
        return 0

    if not args.enrich_only:
        count = seed_table(db_path, force=args.force)
        print(f"Seeded {count} reign periods")

    if args.enrich or args.enrich_only:
        enriched = enrich_notes(db_path)
        print(f"Enriched {enriched} rows with Wikipedia notes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
