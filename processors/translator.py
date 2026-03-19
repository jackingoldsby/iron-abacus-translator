#!/usr/bin/env python3
"""
Translation Service for Classical Chinese and Wuxia Literature

Provides scholarly, PhD-level translation with comprehensive cultural/historical
annotations. Uses OpenAI GPT-4o-mini with two-pass validation and thread isolation.
"""

import os
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

from utils.clients import get_llm_client, LLMRequest

# Add import for wuxia glossary
import sys
from utils.glossary import TranslationGlossary, GlossaryEntry
from processors.translation_prompts import GENRE_PROMPTS, build_system_prompt

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Legacy TRANSLATION_SYSTEM_PROMPT kept for backward compatibility.
# New code should use GENRE_PROMPTS from processors.translation_prompts.
from processors.translation_prompts import TRANSLATION_SYSTEM_PROMPT  # noqa: F811

VALIDATION_SYSTEM_PROMPT = """You are a validation specialist for Classical Chinese translations. Your role is to verify translation quality and footnote accuracy.

**Validation Criteria:**

1. **Translation Quality**:
   - Accuracy to source text
   - Literary quality and readability
   - Appropriate tone and register
   - Preservation of narrative voice

2. **Footnote Quality**:
   - Pinyin accuracy (standard Hanyu Pinyin)
   - Cultural/historical accuracy
   - Appropriate depth and clarity
   - No character analysis (factual context only)
   - Consistent terminology

3. **Inline Marker Validation** (IMPORTANT):
   - Every footnote in content_footnotes SHOULD have a corresponding [n] marker in annotated_content_text
   - Markers should be sequential: [1], [2], [3], etc.
   - Markers should appear immediately after the annotated term
   - Example: "King Zhou[1] visited Nüwa[2]" is CORRECT
   - Example: "King Zhou [1]" (extra space) is acceptable as MINOR issue
   - Flag as MAJOR error only if 50% or more footnotes lack markers
   - Flag as MINOR warning if markers have spacing issues or are slightly misplaced
   - Be lenient: If most markers are present, accept with minor warnings

4. **Format Compliance**:
   - Valid JSON structure
   - All required fields present
   - Footnote keys sequential and correct
   - Content type appropriate

**Output Format:**

Return ONLY valid JSON (no markdown):

{
  "is_valid": true|false,
  "quality_score": <0-100>,
  "issues": [
    {
      "type": "translation|footnote|format|pinyin",
      "severity": "critical|major|minor",
      "description": "<detailed_issue_description>",
      "location": "<specific_location>"
    }
  ],
  "suggestions": [
    "<improvement_suggestion_1>",
    "<improvement_suggestion_2>"
  ]
}

**Severity Levels:**

- `critical`: Must fix (incorrect translation, invalid format, missing required fields)
- `major`: Should fix (inaccurate footnotes, poor pinyin, inconsistent terminology)
- `minor`: Nice to fix (style improvements, additional context)

Be thorough but fair. Recognize scholarly quality when present.
"""


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class FootnoteDetails:
    """Details for a single footnote"""
    footnote_ideogram: str
    footnote_pinyin: str
    footnote_explanation: str


@dataclass
class ContentFootnote:
    """A single footnote with key and details"""
    footnote_key: int
    footnote_details: FootnoteDetails


@dataclass
class TranslatedAnnotatedContent:
    """Translated and annotated content"""
    annotated_content_text: str
    content_footnotes: List[ContentFootnote]
    content_type: str


@dataclass
class TranslationRequest:
    """Request format for translation"""
    content_text_id: int
    content_source_text: str


@dataclass
class TranslationResponse:
    """Response format for translation"""
    content_text_id: int
    content_source_text: str
    translated_annotated_content: TranslatedAnnotatedContent


@dataclass
class ValidationIssue:
    """Validation issue details"""
    type: str  # translation|footnote|format|pinyin
    severity: str  # critical|major|minor
    description: str
    location: str


@dataclass
class ValidationResult:
    """Validation result"""
    is_valid: bool
    quality_score: int
    issues: List[ValidationIssue]
    suggestions: List[str]


# =============================================================================
# POST-PROCESSING: Trivial Footnote Removal
# =============================================================================

import re as _re

# Words that signal a footnote is just defining a common English concept
_TRIVIAL_DEFINITION_WORDS = {
    "villager", "village", "moss", "firewood", "mountain path", "mountain trail",
    "young woman", "married woman", "fruit", "sigh", "color", "colour",
    "pine tree", "maple", "wildflower", "hunter", "path", "trail",
    "cloth", "skirt", "clothing", "congratulations", "new year",
    "orange", "green", "blue", "red", "hairpin", "jade hairpin",
    "tangerine", "ripe",
}

# Ideograms that are ALWAYS trivial (common words with direct English equivalents)
_TRIVIAL_IDEOGRAMS = {
    "鄉人", "山路", "蒼苔", "苔", "果品", "裙布", "少婦", "柴草",
    "喟然微歎", "嘆息", "荒山僻徑", "雪青", "桔紅的", "桔紅", "蒼松",
    "野花楓葉", "恭喜", "甘淡泊", "玉釵",
}

# Terms that indicate REAL cultural content — never strip these
_CULTURAL_KEYWORDS = {
    "dynasty", "emperor", "reign", "era", "martial", "qi", "qì",
    "neigong", "nèigōng", "wuxia", "jianghu", "jiānghú",
    "confuci", "daois", "buddhis", "taois", "ritual", "ceremony",
    "calligraph", "poet", "scholar", "historical",
    "ming", "tang", "song", "yuan", "qing", "han", "jin",
    "technique", "palm strike", "sword art", "fist",
    "capital", "ancient capital", "painter", "renowned",
}


def _is_trivial_footnote(ideogram: str, explanation: str) -> bool:
    """Check if a footnote is trivial based on its ideogram and explanation text."""
    # Known trivial ideograms
    if ideogram in _TRIVIAL_IDEOGRAMS:
        return True

    expl_lower = explanation.lower()

    # If explanation contains cultural keywords, it's NOT trivial
    for kw in _CULTURAL_KEYWORDS:
        if kw in expl_lower:
            return False

    # Short explanations that just define common English words are trivial
    if len(explanation) < 100:
        for word in _TRIVIAL_DEFINITION_WORDS:
            if word in expl_lower:
                return True

    return False


def strip_trivial_footnotes(response: 'TranslationResponse') -> 'TranslationResponse':
    """
    Remove trivial footnotes from a translation response and renumber remaining ones.
    Fast, deterministic — no API call needed.
    """
    tac = response.translated_annotated_content
    footnotes = tac.content_footnotes
    text = tac.annotated_content_text

    if not footnotes:
        return response

    keep = []
    remove_keys = set()

    for fn in footnotes:
        if _is_trivial_footnote(fn.footnote_details.footnote_ideogram,
                                fn.footnote_details.footnote_explanation):
            remove_keys.add(fn.footnote_key)
        else:
            keep.append(fn)

    if not remove_keys:
        return response

    logger.info(f"Stripping {len(remove_keys)} trivial footnotes, keeping {len(keep)}")

    # Remove markers from text
    for key in remove_keys:
        text = _re.sub(rf'\[{key}\]', '', text)

    # Renumber remaining footnotes 1..N
    old_to_new = {}
    for new_idx, fn in enumerate(keep, 1):
        old_to_new[fn.footnote_key] = new_idx

    # Replace old markers with new (use placeholders to avoid collision)
    for old_key, new_key in sorted(old_to_new.items(), key=lambda x: -x[0]):
        text = text.replace(f'[{old_key}]', f'[__TMP_{new_key}__]')
    for new_key in old_to_new.values():
        text = text.replace(f'[__TMP_{new_key}__]', f'[{new_key}]')

    new_footnotes = [
        ContentFootnote(
            footnote_key=old_to_new[fn.footnote_key],
            footnote_details=fn.footnote_details
        )
        for fn in keep
    ]

    return TranslationResponse(
        content_text_id=response.content_text_id,
        content_source_text=response.content_source_text,
        translated_annotated_content=TranslatedAnnotatedContent(
            annotated_content_text=text,
            content_footnotes=new_footnotes,
            content_type=tac.content_type,
        )
    )


# =============================================================================
# TRANSLATION SERVICE
# =============================================================================

class TranslationService:
    """
    Translation service with two-pass validation and thread isolation.

    Uses OpenAI GPT-4o-mini for scholarly translation of Classical Chinese
    and Wuxia literature with comprehensive cultural annotations.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_retries: int = 2,
        timeout: int = 120,
        glossary_path: Optional[Path] = None,
        llm_client=None,
        genre: str = "wuxia",
        author: str = None,
    ):
        """
        Initialize translation service.

        Args:
            model: Model override (default: resolved by factory — gpt-4.1-mini for translator)
            temperature: Sampling temperature (0.0-1.0, default: 0.3)
            max_retries: Maximum retry attempts (default: 2)
            timeout: Request timeout in seconds (default: 120)
            glossary_path: Path to glossary.duckdb (default: from environment config)
            llm_client: Pre-configured LLMClient (overrides provider lookup)
            genre: Genre key for prompt selection ("wuxia" or "classical")
            author: Author key (author_chinese) for style overlay
        """
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self.genre = genre
        self.author = author

        # Build genre + author system prompt
        self._system_prompt = build_system_prompt(genre=genre, author=author)

        # Initialize LLM client — model resolved by factory if not explicit
        self.llm = llm_client or get_llm_client(component="translator", model=model)
        self.model = self.llm.model
        logger.info(f"Initialized TranslationService with model={self.model}, genre={genre}, author={author or 'default'}, temperature={temperature}")

        # Initialize wuxia glossary
        try:
            self.glossary = TranslationGlossary(glossary_path)
            logger.info(f"Loaded wuxia glossary from {self.glossary.db_path}")
        except FileNotFoundError:
            logger.warning(f"Glossary not found, proceeding without glossary")
            self.glossary = None

    def _scan_glossary_terms(self, source_text: str) -> List[Tuple[str, GlossaryEntry, int]]:
        """
        Scan source text for glossary terms.

        Args:
            source_text: Chinese source text

        Returns:
            List of (term, entry, position) tuples
        """
        if not self.glossary:
            return []

        matches = self.glossary.find_in_text(source_text, max_matches=30)
        logger.info(f"Found {len(matches)} glossary terms in source text")

        for term, entry, pos in matches:
            logger.debug(f"  - {term} ({entry.pinyin}) @ position {pos}")

        return matches

    def _build_glossary_context(self, matches: List[Tuple[str, GlossaryEntry, int]]) -> str:
        """
        Build glossary context to pass to translator.

        Args:
            matches: List of glossary matches

        Returns:
            Formatted glossary context string
        """
        if not matches:
            return ""

        context_parts = [
            "\n\n**GLOSSARY TERMS FOUND IN THIS TEXT:**",
            "\nThe following wuxia/cultural terms appear in this passage. Use EXACTLY these forms and footnotes:\n"
        ]

        for i, (term, entry, _) in enumerate(matches, 1):
            context_parts.append(f"\n{i}. **{term}** ({entry.chinese})")
            context_parts.append(f"   - Pinyin: {entry.pinyin}")
            context_parts.append(f"   - Translation Strategy: {entry.translation_strategy}")
            context_parts.append(f"   - Recommended Form: {entry.recommended_form}")
            context_parts.append(f"   - Footnote Template: {entry.footnote_template}")
            context_parts.append(f"   - Deduplication: {entry.deduplication_strategy}")

        context_parts.append("\n\n**INSTRUCTIONS:**")
        context_parts.append("- Use the EXACT 'Recommended Form' when translating each term")
        context_parts.append("- Use the EXACT 'Footnote Template' for footnotes")
        context_parts.append("- Use the EXACT 'Pinyin' (with tone marks) for consistency")
        context_parts.append("- Add footnotes for ALL occurrences (deduplication happens later)")
        context_parts.append("- Ensure glossary footnotes and custom footnotes use the same JSON structure\n")

        return "".join(context_parts)

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        """
        Translate text with two-pass validation.

        Args:
            request: TranslationRequest object

        Returns:
            TranslationResponse object with translation and annotations

        Raises:
            RuntimeError: If translation fails after all retries
        """
        logger.info(f"Starting translation for content_text_id={request.content_text_id}")

        # Scan for glossary terms
        glossary_matches = self._scan_glossary_terms(request.content_source_text)

        # Pass 1: Translation
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"Translation attempt {attempt}/{self.max_retries}")
                translation_response = self._translate_with_thread(request, glossary_matches)

                # Pass 2: Validation
                logger.info("Validating translation...")
                validation = self._validate_with_thread(translation_response)

                if validation.is_valid:
                    logger.info(f"Translation validated successfully (quality={validation.quality_score}/100)")
                    return strip_trivial_footnotes(translation_response)

                # Check if issues are critical
                critical_issues = [i for i in validation.issues if i.severity == "critical"]
                major_issues = [i for i in validation.issues if i.severity == "major"]

                if critical_issues:
                    logger.warning(f"Critical issues found: {len(critical_issues)}")
                    for issue in critical_issues:
                        logger.warning(f"  - {issue.type}: {issue.description}")

                    if attempt < self.max_retries:
                        logger.info("Retrying translation due to critical issues...")
                        time.sleep(2)
                        continue
                elif major_issues and attempt < self.max_retries:
                    # Try once more for major issues, but don't insist
                    logger.warning(f"Major issues found: {len(major_issues)}")
                    for issue in major_issues:
                        logger.warning(f"  - {issue.type}: {issue.description}")
                    logger.info("Retrying translation once for major issues...")
                    time.sleep(2)
                    continue
                else:
                    # Non-critical/minor issues, or last attempt with major issues - accept with warnings
                    if validation.issues:
                        logger.warning(f"Translation has {len(validation.issues)} issues but is acceptable")
                        for issue in validation.issues:
                            logger.warning(f"  - [{issue.severity}] {issue.type}: {issue.description}")
                    return strip_trivial_footnotes(translation_response)

            except Exception as e:
                logger.error(f"Translation attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"Translation failed after {self.max_retries} attempts: {e}")

        raise RuntimeError(f"Translation failed validation after {self.max_retries} attempts")

    def _translate_with_thread(
        self,
        request: TranslationRequest,
        glossary_matches: List[Tuple[str, GlossaryEntry, int]] = None
    ) -> TranslationResponse:
        """
        Execute translation using Chat Completions API.

        Args:
            request: TranslationRequest object
            glossary_matches: Optional list of glossary term matches

        Returns:
            TranslationResponse object
        """
        # Prepare base message
        message_content = json.dumps({
            "content_text_id": request.content_text_id,
            "content_source_text": request.content_source_text
        }, ensure_ascii=False)

        # Add glossary context if terms found
        if glossary_matches:
            glossary_context = self._build_glossary_context(glossary_matches)
            user_message = message_content + glossary_context
        else:
            user_message = message_content

        # Call LLM
        try:
            response = self.llm.chat(LLMRequest(
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.model,
                temperature=self.temperature,
                json_mode=True,
                timeout=self.timeout,
            ))

            return self._parse_translation_response(response.text)

        except Exception as e:
            raise RuntimeError(f"Translation failed: {e}")

    def _validate_with_thread(self, response: TranslationResponse) -> ValidationResult:
        """
        Validate translation using Chat Completions API.

        Args:
            response: TranslationResponse to validate

        Returns:
            ValidationResult object
        """
        # Prepare validation message
        validation_message = json.dumps(self._response_to_dict(response), ensure_ascii=False)

        # Call LLM
        try:
            response = self.llm.chat(LLMRequest(
                messages=[
                    {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
                    {"role": "user", "content": validation_message}
                ],
                model=self.model,
                temperature=0.1,  # Lower temperature for consistent validation
                json_mode=True,
                timeout=self.timeout,
            ))

            return self._parse_validation_response(response.text)

        except Exception as e:
            raise RuntimeError(f"Validation failed: {e}")

    def _parse_translation_response(self, response_text: str) -> TranslationResponse:
        """
        Parse JSON response from translation assistant.

        Args:
            response_text: JSON string from assistant

        Returns:
            TranslationResponse object
        """
        try:
            # First attempt: parse as-is
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            # Second attempt: Fix common JSON issues
            logger.warning(f"Initial JSON parse failed: {e}. Attempting to fix JSON formatting issues...")
            try:
                import re
                fixed_text = response_text

                # Fix 1: Unquoted Chinese characters in footnote_ideogram
                # Pattern: "footnote_ideogram": 陸高止, -> "footnote_ideogram": "陸高止",
                fixed_text = re.sub(
                    r'"footnote_ideogram":\s*([^",\[\]{}\s][^,\}]*),',
                    r'"footnote_ideogram": "\1",',
                    fixed_text
                )

                # Fix 2: Trailing commas in arrays and objects
                # Remove comma before ] or }
                fixed_text = re.sub(r',(\s*[\]}])', r'\1', fixed_text)

                # Fix 3: Missing quotes around field names (rare but possible)
                # This is a more aggressive fix, only applies if still failing

                data = json.loads(fixed_text)
                logger.info("Successfully fixed JSON formatting issues")
            except json.JSONDecodeError as e2:
                # Try one more aggressive fix: remove all trailing commas
                try:
                    fixed_text = re.sub(r',(\s*[\]}])', r'\1', response_text)
                    data = json.loads(fixed_text)
                    logger.info("Successfully fixed JSON with aggressive trailing comma removal")
                except json.JSONDecodeError as e3:
                    raise RuntimeError(f"Failed to parse translation response even after multiple fix attempts.\nOriginal error: {e}\nSecond error: {e2}\nThird error: {e3}\nResponse: {response_text[:500]}...")

        try:
            # Parse footnotes
            footnotes = []
            for fn in data["translated_annotated_content"]["content_footnotes"]:
                # Handle both nested {"footnote_details": {...}} and flat structure
                if "footnote_details" in fn:
                    details = fn["footnote_details"]
                elif "footnote_ideogram" in fn:
                    # Model flattened the structure — reconstruct
                    details = {
                        "footnote_ideogram": fn.get("footnote_ideogram", ""),
                        "footnote_pinyin": fn.get("footnote_pinyin", ""),
                        "footnote_explanation": fn.get("footnote_explanation", ""),
                    }
                else:
                    logger.warning(f"Skipping malformed footnote: {fn}")
                    continue
                footnote = ContentFootnote(
                    footnote_key=fn["footnote_key"],
                    footnote_details=FootnoteDetails(**details)
                )
                footnotes.append(footnote)

            # Build response
            translated_content = TranslatedAnnotatedContent(
                annotated_content_text=data["translated_annotated_content"]["annotated_content_text"],
                content_footnotes=footnotes,
                content_type=data["translated_annotated_content"]["content_type"]
            )

            return TranslationResponse(
                content_text_id=data["content_text_id"],
                content_source_text=data["content_source_text"],
                translated_annotated_content=translated_content
            )

        except (KeyError, TypeError) as e:
            raise RuntimeError(f"Failed to parse translation response structure: {e}\nResponse: {response_text}")

    def _parse_validation_response(self, response_text: str) -> ValidationResult:
        """
        Parse JSON response from validation assistant.

        Args:
            response_text: JSON string from assistant

        Returns:
            ValidationResult object
        """
        try:
            data = json.loads(response_text)

            # Parse issues
            issues = [ValidationIssue(**issue) for issue in data.get("issues", [])]

            return ValidationResult(
                is_valid=data["is_valid"],
                quality_score=data["quality_score"],
                issues=issues,
                suggestions=data.get("suggestions", [])
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise RuntimeError(f"Failed to parse validation response: {e}\nResponse: {response_text}")

    def _response_to_dict(self, response: TranslationResponse) -> Dict[str, Any]:
        """
        Convert TranslationResponse to dictionary for JSON serialization.

        Args:
            response: TranslationResponse object

        Returns:
            Dictionary representation
        """
        return {
            "content_text_id": response.content_text_id,
            "content_source_text": response.content_source_text,
            "translated_annotated_content": {
                "annotated_content_text": response.translated_annotated_content.annotated_content_text,
                "content_footnotes": [
                    {
                        "footnote_key": fn.footnote_key,
                        "footnote_details": {
                            "footnote_ideogram": fn.footnote_details.footnote_ideogram,
                            "footnote_pinyin": fn.footnote_details.footnote_pinyin,
                            "footnote_explanation": fn.footnote_details.footnote_explanation
                        }
                    }
                    for fn in response.translated_annotated_content.content_footnotes
                ],
                "content_type": response.translated_annotated_content.content_type
            }
        }

    def translate_from_dict(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convenience method for dictionary-based translation.

        Args:
            request_dict: Dictionary with content_text_id and content_source_text

        Returns:
            Dictionary with translation response
        """
        request = TranslationRequest(
            content_text_id=request_dict["content_text_id"],
            content_source_text=request_dict["content_source_text"]
        )

        response = self.translate(request)
        return self._response_to_dict(response)

    def translate_batch(
        self,
        requests: List[Dict[str, Any]],
        output_dir: Optional[Path] = None,
        save_individual: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Translate multiple texts (sequential processing).

        Args:
            requests: List of request dictionaries
            output_dir: Optional directory to save individual results
            save_individual: Whether to save each result individually

        Returns:
            List of response dictionaries
        """
        results = []

        if output_dir and save_individual:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        for i, request_dict in enumerate(requests, 1):
            logger.info(f"Processing batch item {i}/{len(requests)}")

            try:
                result = self.translate_from_dict(request_dict)
                results.append(result)

                if output_dir and save_individual:
                    output_file = output_dir / f"translation_{request_dict['content_text_id']}.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    logger.info(f"Saved individual result to {output_file}")

            except Exception as e:
                logger.error(f"Failed to translate item {i}: {e}")
                results.append({
                    "content_text_id": request_dict.get("content_text_id"),
                    "error": str(e)
                })

        return results


# =============================================================================
# MAIN / TEST
# =============================================================================

def main():
    """Test the translation service"""

    # Sample request
    test_request = {
        "content_text_id": 1,
        "content_source_text": "且言紂王只因進香之後，看見女媧美貌，朝暮思想，寒暑盡忘。"
    }

    try:
        service = TranslationService()
        result = service.translate_from_dict(test_request)

        print("\n=== TRANSLATION RESULT ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(f"Translation test failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
