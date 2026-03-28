"""Author name mappings (traditional <-> simplified)."""

# Known author mappings (traditional -> simplified)
AUTHOR_MAP = {
    "溫瑞安": "温瑞安",
    "蕭逸": "萧逸",
    "陳青雲": "陈青云",
    "柳殘陽": "柳残阳",
    "臥龍生": "卧龙生",
    "司馬翎": "司马翎",
    "黃易": "黄易",
    "梁羽生": "梁羽生",
    "諸葛青雲": "诸葛青云",
    "還珠樓主": "还珠楼主",
    "顧明道": "顾明道",
    "鄭證因": "郑证因",
    "張恨水": "张恨水",
}

# Reverse map (simplified -> traditional)
AUTHOR_MAP_S2T = {v: k for k, v in AUTHOR_MAP.items()}
