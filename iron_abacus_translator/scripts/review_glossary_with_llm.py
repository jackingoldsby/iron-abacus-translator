#!/usr/bin/env python3
"""
Review wuxia translation glossary with DeepSeek for accuracy and completeness.

Phase 1: Review existing entries (pinyin, semantics, footnotes, strategy)
Phase 2: Suggest missing wuxia/martial arts terms

Usage:
    cd iron_abacus_translator
    python scripts/review_glossary_with_llm.py
    python scripts/review_glossary_with_llm.py --phase 1       # Review only
    python scripts/review_glossary_with_llm.py --phase 2       # Suggestions only
    python scripts/review_glossary_with_llm.py --batch-size 20 # Custom batch size
    python scripts/review_glossary_with_llm.py --provider openai --model gpt-4.1  # Use different provider
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.clients import LLMRequest, get_llm_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

GLOSSARY_DIR = Path(__file__).parent.parent / "data" / "glossaries"
MAIN_CSV = GLOSSARY_DIR / "translation_glossary.csv"
ADDITIONS_CSV = GLOSSARY_DIR / "translation_glossary_additions.csv"
OUTPUT_PATH = GLOSSARY_DIR / "glossary_review_report.json"

REVIEW_SYSTEM_PROMPT = """\
You are a senior sinologist and wuxia philologist with deep expertise in Classical Chinese \
martial arts literature, Daoist cultivation terminology, and the literary conventions of the \
jiānghú (江湖) tradition from Liang Yusheng (梁羽生), Jin Yong (金庸), and Gu Long (古龍).

You are reviewing a translation glossary that drives an automated Classical Chinese → English \
translation pipeline for wuxia novels. Every entry in this glossary will be applied across \
hundreds of chapters — errors propagate at scale. Your review must be exacting.

For each entry, evaluate:

1. **Pinyin accuracy** — correct tone marks, syllable boundaries, standard romanization. \
Flag missing or incorrect diacritics. Use standard Hànyǔ Pīnyīn.

2. **Semantic precision** — does the English rendering (Recommended_Form) capture the term's \
meaning within wuxia literary tradition? Dictionary definitions are insufficient; terms carry \
genre-specific connotations. E.g., 討教 in jiānghú context means "seek instruction [in combat]" \
not merely "ask for advice."

3. **Footnote template quality** — factual accuracy of historical claims (dynasties, dates, \
attributions), depth of cultural context, classical allusions. Footnotes should have \
philological depth: include dynasty/dates where relevant, attribute to specific texts or \
traditions, note semantic evolution. Shallow or vague explanations are deficient.

4. **Translation strategy** — is PINYIN_ONLY / ENGLISH_ONLY / HYBRID the right call for this \
term's cultural weight and translatability? PINYIN_ONLY for untranslatable cultural concepts \
with no English equivalent; ENGLISH_ONLY for terms with good English renderings; HYBRID for \
terms that benefit from both.

5. **Missing nuance** — are there connotations, register distinctions, or genre-specific usages \
that the current entry fails to capture?

Respond ONLY with a JSON object. Do not include markdown fencing or commentary outside the JSON.

Format:
{
  "issues": [
    {
      "chinese": "罡氣",
      "field": "pinyin|recommended_form|footnote_template|translation_strategy|missing_nuance",
      "severity": "error|suggestion",
      "current": "the current value",
      "suggested": "your correction or improvement",
      "reason": "philological justification"
    }
  ]
}

If all entries in the batch are correct, return {"issues": []}.

Severity guide:
- "error": factually wrong pinyin, incorrect historical claims, misleading translations
- "suggestion": improvements to depth, nuance, or strategy that would strengthen the glossary
"""

SUGGEST_SYSTEM_PROMPT = """\
You are a senior sinologist and wuxia philologist with comprehensive knowledge of Classical \
Chinese martial arts literature across all major authors (金庸, 梁羽生, 古龍, 溫瑞安, etc.).

Below is a list of Chinese terms already in our wuxia translation glossary. Your task: suggest \
additional terms that a comprehensive wuxia translation glossary should include but currently \
does not.

Focus on:
- **High-frequency wuxia terms** that appear across multiple novels and authors
- **Martial arts concepts** (techniques, training methods, combat terminology)
- **Jiānghú social structure** (ranks, organizations, conventions, etiquette)
- **Cultivation and Daoist terminology** used in wuxia context
- **Weapons and equipment** commonly referenced
- **Literary/narrative conventions** specific to the genre

Do NOT suggest:
- Character names (proper nouns specific to one novel)
- Terms already in the existing list
- Extremely rare or author-specific neologisms

Group suggestions by category. For each term provide:
- chinese: the Chinese characters (traditional preferred)
- pinyin: with correct tone marks
- meaning: concise English gloss within wuxia context
- category: one of [technique_category, concept, anatomy, weapon, social_structure, \
cultivation, combat, literary_convention, pathology, location_type]
- reason: why this term belongs in a comprehensive wuxia glossary

Respond ONLY with a JSON object:
{
  "suggested_additions": [
    {
      "chinese": "比武",
      "pinyin": "bǐwǔ",
      "meaning": "martial contest / formal combat challenge",
      "category": "combat",
      "reason": "High-frequency term across all wuxia authors for formal duels and tournaments"
    }
  ]
}
"""


def load_glossary_entries() -> List[Dict[str, str]]:
    """Load all glossary entries from CSV files."""
    entries = []
    for csv_path in [MAIN_CSV, ADDITIONS_CSV]:
        if not csv_path.exists():
            logger.warning(f"Glossary file not found: {csv_path}")
            continue
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["_source"] = csv_path.name
                entries.append(row)
    logger.info(f"Loaded {len(entries)} glossary entries from {len([p for p in [MAIN_CSV, ADDITIONS_CSV] if p.exists()])} files")
    return entries


def format_batch_for_review(entries: List[Dict[str, str]]) -> str:
    """Format a batch of glossary entries for the review prompt."""
    lines = []
    for i, entry in enumerate(entries, 1):
        lines.append(f"--- Entry {i} ---")
        lines.append(f"Chinese: {entry.get('Chinese', '')}")
        lines.append(f"Pinyin: {entry.get('Pinyin', '')}")
        lines.append(f"Translation_Strategy: {entry.get('Translation_Strategy', '')}")
        lines.append(f"Recommended_Form: {entry.get('Recommended_Form', '')}")
        lines.append(f"Footnote_Template: {entry.get('Footnote_Template', '')}")
        lines.append(f"Category: {entry.get('Category', '')}")
        lines.append(f"Rationale: {entry.get('Rationale', '')}")
        lines.append("")
    return "\n".join(lines)


def review_batch(client, entries: List[Dict[str, str]], batch_num: int, total_batches: int) -> List[Dict[str, Any]]:
    """Send a batch of entries to the LLM for review."""
    batch_text = format_batch_for_review(entries)
    user_msg = (
        f"Review the following {len(entries)} glossary entries (batch {batch_num}/{total_batches}). "
        f"Flag any issues with pinyin, semantics, footnotes, or translation strategy.\n\n"
        f"{batch_text}"
    )

    request = LLMRequest(
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        json_mode=True,
        max_tokens=4096,
        timeout=120,
    )

    logger.info(f"  Reviewing batch {batch_num}/{total_batches} ({len(entries)} entries)...")
    response = client.chat(request)

    if response.parsed and "issues" in response.parsed:
        issues = response.parsed["issues"]
        logger.info(f"  Batch {batch_num}: {len(issues)} issues found")
        return issues

    logger.warning(f"  Batch {batch_num}: unexpected response format")
    # Try to parse anyway
    try:
        data = json.loads(response.text)
        return data.get("issues", [])
    except json.JSONDecodeError:
        logger.error(f"  Batch {batch_num}: could not parse response as JSON")
        return []


def suggest_new_terms(client, existing_terms: List[str]) -> List[Dict[str, Any]]:
    """Ask the LLM to suggest missing wuxia terms."""
    terms_list = ", ".join(existing_terms)
    user_msg = (
        f"Here are the {len(existing_terms)} Chinese terms already in our glossary:\n\n"
        f"{terms_list}\n\n"
        f"Suggest additional wuxia/martial arts terms that should be included. "
        f"Aim for 20-40 high-value additions grouped by category."
    )

    request = LLMRequest(
        messages=[
            {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        json_mode=True,
        max_tokens=8192,
        timeout=180,
    )

    logger.info("Requesting new term suggestions...")
    response = client.chat(request)

    if response.parsed and "suggested_additions" in response.parsed:
        suggestions = response.parsed["suggested_additions"]
        logger.info(f"Received {len(suggestions)} term suggestions")
        return suggestions

    try:
        data = json.loads(response.text)
        return data.get("suggested_additions", [])
    except json.JSONDecodeError:
        logger.error("Could not parse suggestions response as JSON")
        return []


def run_phase1(client, entries: List[Dict[str, str]], batch_size: int) -> List[Dict[str, Any]]:
    """Phase 1: Review existing entries for accuracy."""
    logger.info(f"=== Phase 1: Reviewing {len(entries)} entries (batch size {batch_size}) ===")
    all_issues = []

    batches = [entries[i:i + batch_size] for i in range(0, len(entries), batch_size)]
    total_batches = len(batches)

    for batch_num, batch in enumerate(batches, 1):
        issues = review_batch(client, batch, batch_num, total_batches)
        all_issues.extend(issues)
        # Rate limiting between batches
        if batch_num < total_batches:
            time.sleep(1)

    logger.info(f"Phase 1 complete: {len(all_issues)} total issues found across {len(entries)} entries")
    return all_issues


def run_phase2(client, entries: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Phase 2: Suggest new terms."""
    logger.info("=== Phase 2: Suggesting new terms ===")
    existing_terms = [e.get("Chinese", "") for e in entries if e.get("Chinese")]
    suggestions = suggest_new_terms(client, existing_terms)
    logger.info(f"Phase 2 complete: {len(suggestions)} new terms suggested")
    return suggestions


def main():
    parser = argparse.ArgumentParser(description="Review wuxia glossary with LLM")
    parser.add_argument("--phase", type=int, choices=[1, 2], default=None,
                        help="Run specific phase only (1=review, 2=suggestions)")
    parser.add_argument("--batch-size", type=int, default=15,
                        help="Entries per review batch (default: 15)")
    parser.add_argument("--provider", type=str, default="deepseek",
                        help="LLM provider (default: deepseek)")
    parser.add_argument("--model", type=str, default=None,
                        help="LLM model override")
    parser.add_argument("--output", type=str, default=None,
                        help="Output path for report JSON")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else OUTPUT_PATH

    # Load glossary
    entries = load_glossary_entries()
    if not entries:
        logger.error("No glossary entries loaded. Check CSV files exist.")
        return 1

    # Create client
    try:
        client = get_llm_client(provider=args.provider, model=args.model)
        logger.info(f"Using provider={args.provider}, model={client.default_model}")
    except Exception as e:
        logger.error(f"Failed to create LLM client: {e}")
        return 1

    # Run phases
    report: Dict[str, Any] = {
        "provider": args.provider,
        "model": client.default_model,
        "reviewed": 0,
        "issues_found": 0,
        "issues": [],
        "suggested_additions": [],
    }

    run_p1 = args.phase is None or args.phase == 1
    run_p2 = args.phase is None or args.phase == 2

    if run_p1:
        issues = run_phase1(client, entries, args.batch_size)
        report["reviewed"] = len(entries)
        report["issues_found"] = len(issues)
        report["issues"] = issues

    if run_p2:
        suggestions = run_phase2(client, entries)
        report["suggested_additions"] = suggestions

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"Report written to {output_path}")
    logger.info(f"  Entries reviewed: {report['reviewed']}")
    logger.info(f"  Issues found: {report['issues_found']}")
    logger.info(f"  New terms suggested: {len(report['suggested_additions'])}")

    # Print summary of errors (severity=error)
    errors = [i for i in report["issues"] if i.get("severity") == "error"]
    if errors:
        logger.info(f"\n  === {len(errors)} ERRORS (require attention) ===")
        for err in errors:
            logger.info(f"    {err.get('chinese', '?')} [{err.get('field', '?')}]: {err.get('reason', '')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
