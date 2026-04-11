# Footnote Pruner Agent

Post-translation footnote quality enforcement. Reads a translated JSON file, reviews every footnote, and removes or trims those that fail quality standards.

## When to use

Run after the pipeline completes, as a final quality pass before distributing the EPUB. This is the last line of defense against:
- Hallucinated historical claims
- Pop culture references (films, TV, games, modern media)
- Cross-cultural tangents (irrelevant analogues from India, Korea, Europe)
- Inane surname/character-name footnotes
- Technique footnotes that just describe physical motion
- Wrong dynasty/era references for the story's setting
- Self-referential footnotes ("popularized in the novel being translated")
- Circular/redundant definitions
- Vague literary filler ("such places often serve as...")

## Input

A translated JSON file path. The agent reads the file, processes it, and writes:
1. A pruned JSON file (`_pruned.json` suffix)
2. A markdown report documenting all changes

## Process

For each footnote, the agent evaluates:

### REMOVE entirely if:
- Footnote just explains a surname ("包 — A common Chinese surname")
- Footnote describes a fictional character's traits
- Footnote is for a technique name and only describes the physical motion
- Explanation is under 20 characters (too short to be useful)

### TRIM (remove bad sentences, keep good core) if:
- Good first sentence but hallucinated tangent follows
- Cross-cultural analogue appended (Vietnam, Korea, India, Europe, etc.)
- Pop culture reference in trailing sentences
- Wrong dynasty/era claim for the story's setting
- Self-referential mention of the novel being translated
- Vague literary commentary ("this illustrates...", "it is worth noting...")
- Rayleigh scattering, Tower of Babel, Marvel Comics, or other absurd tangents

### KEEP unchanged if:
- Explains a real historical institution with dates/dynasty
- Provides geographic context with province/region
- Explains an acupoint with body location and martial significance
- Gives the origin of an idiom or proverb
- Names a real verifiable martial school/tradition
- Explains a genuine cultural practice

## After pruning

- Renumber all footnote markers sequentially per chapter (sorted by text position)
- Remove orphan markers from translated_content
- Update the footnotes array to match

## Output

- `{original_name}_pruned.json` — the cleaned file
- `footnote_prune_report_{work_id}.md` — detailed report with statistics and examples

## Example invocation

```
Process the file /path/to/translated_work.json
```
