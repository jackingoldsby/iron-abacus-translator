#!/usr/bin/env python3
"""Benchmark OCR accuracy against Wikisource ground truth.

Tests multiple preprocessing strategies on a set of body text pages,
runs OCR, applies postprocessing, and compares against known-good text.

No LLM calls — everything is local PaddleOCR + OpenCC.

Usage:
    python scripts/benchmark_ocr.py --pdf /path/to/vol1.pdf --pages 81,82,83,84
    python scripts/benchmark_ocr.py --pdf /path/to/vol1.pdf --pages 81,82,83,84 --report /tmp/benchmark.txt
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root.parent) not in sys.path:
    sys.path.insert(0, str(_project_root.parent))

from vermilion_brush.ocr.paddle_engine import OcrEngine
from vermilion_brush.ocr.postprocessor import process_page_boxes

# Wikisource chapter 1 ground truth (first ~2 pages of body text)
# This is the text from zh.wikisource.org/wiki/三俠五義/第001回
GROUND_TRUTH_CH1 = """話說宋朝自陳橋兵變，眾將立太祖為君，江山一統，相傳至太宗，又至真宗，四海昇平，萬民樂業，真是風調雨順，君正臣良。
一日，早朝，文武班齊，有西台御史兼欽天監文彥博出班奏道：「臣夜觀天象，見天狗星犯闕、恐於儲君不利。恭繪形圖一張，謹皇御覽。」承奉接過，陳於御案之上。天子看罷，笑曰：「朕觀此圖，雖則是上天垂象，但朕並無儲君，有何不利之處？卿且歸班，朕自有道理。」早期已畢，眾臣皆散。
轉向宮內，真宗悶悶不久，暗自忖道：「自御妻薨後，正宮之位久虛，幸有李、劉二妃現今俱各有娠，難道上天垂象就應於她二人身不成？」才要宣召二妃見駕，誰想二妃不宣而至，參見已畢，跪而奏曰：「今日乃中秋佳節，妾妃等已將酒宴預備在御同之內，特請聖駕今夕賞月，作個不夜之歡。」天子大喜，即同二妃來到園中，但見秋色蕭蕭，花香馥馥，又搭著金風瑟瑟，不禁心曠神怕。真宗玩賞，進了寶殿，歸了御座，李、劉二妃陪恃。宮娥獻茶己畢。
大多道：「今日文彥博具奏，他道現時夭狗星犯闕，主儲君不利。朕雖乏嗣，且喜二妃俱各有孕，不知將來誰先誰後，是男是女。上天既然垂兆，朕賜汝二人工璽龍袱各一個，鎮壓天狗衝犯；再朕有金九一對，內藏九曲珠於一顆，係上皇所賜，無價之寶，朕幼時隨身佩帶，如今每人各賜一枚，將妃子等姓名宮名刻在上面，隨身佩帶。」李、劉二妃聽了，望上謝恩。大子即將金九解下，命太監陳林拿到尚寶監，立時刻字去了。
這裡二位妃子吩咐擺酒，安席進酒。登時鼓樂迭奏，彩戲俱陳，皇家富貴自不必說。到了晚間，皓月當空，照得滿園如同白晝，君妃快樂，共賞冰輪，星斗齊輝，觥籌交錯。天子飲至半酣，只見陳林手捧金丸，跪呈御前，天子接來細看，見金丸上面，一個刻著「玉宸宮李妃」，一個刻著「金華宮劉妃」，鐫的甚是精巧。天子深喜，即賞了二妃。二妃跪領，欽遵佩帶後，每人又各獻金爵二杯，大子並不推辭，一連飲了，不覺大醉，哈哈大笑，道：「二妃子如有生太子者，立為正宮。」二妃又謝了恩。
天子酒後說了此話不知緊要，誰知生出無限風波。你道為何？皆出劉妃心地不良，久懷嫉妒之心，今一聞此言，惟恐李妃生下太子立了正宮；自那日歸宮之後，便與總管都堂郭槐暗暗鋪謀定計，要害李妃，誰知一旁有個宮人名喚寇珠，乃劉妃承御的宮人。此女雖是劉妃心腹，她卻為人正直，素懷忠義，見劉妃與郭槐討議，好生不樂。從此後各處留神，悄地窺探。"""

import re
def normalize(t):
    return re.sub(r'\s+', '', t)

GT_NORMALIZED = normalize(GROUND_TRUTH_CH1)


@dataclass
class PreprocessConfig:
    name: str
    dpi: int
    apply_clahe: bool = False
    clahe_clip: float = 2.0
    clahe_grid: int = 8
    apply_binarize: bool = False
    binarize_block: int = 31
    binarize_c: int = 10
    apply_sharpen: bool = False
    sharpen_kernel: str = "gentle"  # "gentle" or "strong"
    crop_margin_pct: float = 0.02
    apply_denoise: bool = False
    denoise_h: int = 10


def extract_page_image(pdf_path: Path, page_num: int, dpi: int) -> np.ndarray:
    """Extract a single page as a numpy array."""
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    page = doc[page_num]
    pix = page.get_pixmap(matrix=mat)
    # Convert to numpy
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    elif pix.n == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    doc.close()
    return img


def preprocess_image(img: np.ndarray, config: PreprocessConfig) -> np.ndarray:
    """Apply preprocessing based on config."""
    result = img.copy()

    # Crop margins
    if config.crop_margin_pct > 0:
        h, w = result.shape[:2]
        mh = int(h * config.crop_margin_pct)
        mw = int(w * config.crop_margin_pct)
        result = result[mh:h-mh, mw:w-mw]

    # Convert to grayscale for processing
    if len(result.shape) == 3:
        gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    else:
        gray = result

    # CLAHE (Contrast Limited Adaptive Histogram Equalization)
    if config.apply_clahe:
        clahe = cv2.createCLAHE(clipLimit=config.clahe_clip,
                                 tileGridSize=(config.clahe_grid, config.clahe_grid))
        gray = clahe.apply(gray)

    # Denoise
    if config.apply_denoise:
        gray = cv2.fastNlMeansDenoising(gray, h=config.denoise_h)

    # Sharpen
    if config.apply_sharpen:
        if config.sharpen_kernel == "gentle":
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
        else:
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
        gray = cv2.filter2D(gray, -1, kernel)

    # Binarize
    if config.apply_binarize:
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, config.binarize_block, config.binarize_c
        )

    # Convert back to BGR for PaddleOCR
    result = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return result


# Define preprocessing strategies to test
STRATEGIES = [
    PreprocessConfig(name="baseline_150", dpi=150),
    PreprocessConfig(name="baseline_200", dpi=200),
    PreprocessConfig(name="clahe_150", dpi=150, apply_clahe=True, clahe_clip=2.0, clahe_grid=8),
    PreprocessConfig(name="clahe_200", dpi=200, apply_clahe=True, clahe_clip=2.0, clahe_grid=8),
    PreprocessConfig(name="clahe_strong_150", dpi=150, apply_clahe=True, clahe_clip=4.0, clahe_grid=4),
    PreprocessConfig(name="sharpen_150", dpi=150, apply_sharpen=True, sharpen_kernel="gentle"),
    PreprocessConfig(name="sharpen_strong_150", dpi=150, apply_sharpen=True, sharpen_kernel="strong"),
    PreprocessConfig(name="clahe_sharpen_150", dpi=150, apply_clahe=True, apply_sharpen=True),
    PreprocessConfig(name="denoise_150", dpi=150, apply_denoise=True, denoise_h=10),
    PreprocessConfig(name="denoise_clahe_150", dpi=150, apply_denoise=True, apply_clahe=True),
    PreprocessConfig(name="binarize_150", dpi=150, apply_binarize=True),
    PreprocessConfig(name="clahe_binarize_150", dpi=150, apply_clahe=True, apply_binarize=True),
    PreprocessConfig(name="nocrop_150", dpi=150, crop_margin_pct=0.0),
    PreprocessConfig(name="bigcrop_150", dpi=150, crop_margin_pct=0.05),
    PreprocessConfig(name="kitchen_sink_150", dpi=150, apply_clahe=True, apply_denoise=True,
                     apply_sharpen=True, clahe_clip=2.0),
    PreprocessConfig(name="kitchen_sink_200", dpi=200, apply_clahe=True, apply_denoise=True,
                     apply_sharpen=True, clahe_clip=2.0),
]


def run_benchmark(pdf_path: Path, pages: list[int], report_path: Path | None = None):
    lines = []
    def log(msg):
        print(msg)
        lines.append(msg)

    log("=" * 80)
    log("VERMILION BRUSH OCR BENCHMARK")
    log(f"PDF: {pdf_path.name}")
    log(f"Pages: {pages}")
    log(f"Strategies: {len(STRATEGIES)}")
    log(f"Ground truth: {len(GT_NORMALIZED)} chars (Wikisource ch1)")
    log("=" * 80)

    engine = OcrEngine()
    log("Engine loaded")

    results = []

    for strategy in STRATEGIES:
        log(f"\n--- Strategy: {strategy.name} ---")
        all_ocr_text = []
        total_boxes = 0
        total_time = 0

        for page_num in pages:
            t0 = time.time()

            # Extract
            img = extract_page_image(pdf_path, page_num, strategy.dpi)

            # Preprocess
            processed = preprocess_image(img, strategy)

            # Save to temp file for OCR
            tmp_path = f"/tmp/benchmark_{strategy.name}_p{page_num}.png"
            cv2.imwrite(tmp_path, processed)

            # OCR
            boxes = engine.recognize(tmp_path)
            text = process_page_boxes(boxes)

            elapsed = time.time() - t0
            total_time += elapsed
            total_boxes += len(boxes)
            all_ocr_text.append(text)

            log(f"  p{page_num}: {len(boxes)} boxes, {len(text)} chars, {elapsed:.1f}s")

        # Join all pages and compare to ground truth
        combined = normalize("".join(all_ocr_text))
        # Find the overlap with ground truth (OCR may have more or less text)
        sm = SequenceMatcher(None, combined, GT_NORMALIZED)
        accuracy = sm.ratio()

        # Also measure character coverage (how much of GT is found in OCR)
        matching_blocks = sm.get_matching_blocks()
        matched_gt_chars = sum(b.size for b in matching_blocks)
        coverage = matched_gt_chars / len(GT_NORMALIZED) if GT_NORMALIZED else 0

        result = {
            "strategy": strategy.name,
            "dpi": strategy.dpi,
            "accuracy": accuracy,
            "coverage": coverage,
            "ocr_chars": len(combined),
            "gt_chars": len(GT_NORMALIZED),
            "total_boxes": total_boxes,
            "total_time": total_time,
        }
        results.append(result)

        log(f"  RESULT: accuracy={accuracy:.1%}  coverage={coverage:.1%}  "
            f"chars={len(combined)}/{len(GT_NORMALIZED)}  "
            f"boxes={total_boxes}  time={total_time:.1f}s")

    # Summary table
    log("\n" + "=" * 80)
    log("SUMMARY (sorted by accuracy)")
    log("=" * 80)
    log(f"{'Strategy':<25} {'Acc':>6} {'Cov':>6} {'Chars':>8} {'Boxes':>6} {'Time':>6}")
    log("-" * 65)

    for r in sorted(results, key=lambda x: x["accuracy"], reverse=True):
        log(f"{r['strategy']:<25} {r['accuracy']:>5.1%} {r['coverage']:>5.1%} "
            f"{r['ocr_chars']:>5}/{r['gt_chars']:<5} {r['total_boxes']:>5} {r['total_time']:>5.1f}s")

    # Best strategy
    best = max(results, key=lambda x: x["accuracy"])
    log(f"\nBEST: {best['strategy']} at {best['accuracy']:.1%} accuracy")

    # Write report
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        log(f"\nReport written to: {report_path}")

    # Also save JSON results for machine parsing
    json_path = report_path.with_suffix(".json") if report_path else Path("/tmp/benchmark_results.json")
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"JSON results: {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark OCR preprocessing strategies")
    parser.add_argument("--pdf", required=True, help="Path to PDF")
    parser.add_argument("--pages", default="81,82,83,84", help="Comma-separated page numbers")
    parser.add_argument("--report", default="/tmp/ocr_benchmark_report.txt", help="Report output path")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    pages = [int(p) for p in args.pages.split(",")]
    report_path = Path(args.report) if args.report else None

    run_benchmark(pdf_path, pages, report_path)


if __name__ == "__main__":
    main()
