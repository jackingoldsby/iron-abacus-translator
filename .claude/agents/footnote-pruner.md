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

The agent (Claude) reads every footnote and uses its own scholarly judgment to evaluate quality. Do NOT use regex pattern matching — read each footnote as a sinologist would and decide if it meets the quality bar.

Implementation:
1. Read the JSON file using the Read tool
2. For each chapter, review all footnotes against the rules below
3. Write a Python script (via Bash) that applies the REMOVE/TRIM/KEEP decisions, renumbers footnotes, and produces the output files
4. Run the script

For each footnote, evaluate:

### REMOVE entirely — with examples:

**Surname footnotes:**
- BAD: `包 — A common Chinese surname. The character Bāo is also the surname of the famous Song dynasty official Bāo Zhěng.`
- WHY: Just explains a surname. The reader doesn't need this.

**Fictional character descriptions:**
- BAD: `苗人鳳 — A martial arts master known for his formidable swordsmanship and his title "Golden-Faced Buddha."`
- WHY: Describes a fictional character — this is dramatis personae, not cultural knowledge.

**Technique motion descriptions:**
- BAD: `拐子腳 — A kicking technique named for its resemblance to striking with a crutch. The leg is swung in a hooking arc.`
- BAD: `雲龍三現 — A technique from the Hú Family Sabre Method, emphasizing swift strikes like a dragon emerging from clouds.`
- WHY: Just describes physical motion or fabricates lineage. The poetic English name is self-explanatory.

**Too short to be useful:**
- BAD: `劍 — A sword.` (under 20 chars, reader already knows)

### TRIM (remove bad sentences, keep good core) — with examples:

**Cross-cultural tangents:**
- BEFORE: `知縣 — A county magistrate, the lowest level of imperial administration... In modern India, the district magistrate serves a comparable administrative function.`
- AFTER: `知縣 — A county magistrate, the lowest level of imperial administration.`

**Pop culture / film references:**
- BEFORE: `點子 — A jiānghú slang term for a target, popularized by the 1986 Hong Kong action film A Better Tomorrow.`
- AFTER: `點子 — A jiānghú slang term for a target or person of interest.`

**Wrong dynasty/era:**
- BEFORE: `紫禁城 — The Forbidden City (1420–1924) in Běijīng...` (story is set in Song dynasty, Forbidden City is Ming/Qing)
- AFTER: Remove the Forbidden City dates, keep only Song-relevant content.

**Self-referential:**
- BEFORE: `龍頭鍘 — An imperial guillotine, popularized in the 1879 novel The Three Heroes and Five Gallants.`
- AFTER: `龍頭鍘 — An imperial guillotine used by Judge Bāo, symbolizing his authority to execute even high-ranking officials.`

**Absurd tangents:**
- BEFORE: `欽天監 — The Imperial Observatory... A Belgian-Brazilian astronomer Ferdinand Verbiest later directed the observatory.`
- AFTER: `欽天監 — The Imperial Observatory, responsible for astronomical observation, calendar computation, and interpreting celestial omens for the court.`

**Vague literary filler:**
- BEFORE: `金龍寺 — A Buddhist temple. Such places often serve as sanctuaries in Chinese fiction.`
- AFTER: Remove — adds nothing cultural.

**Marvel Comics (!!):**
- BEFORE: `星君 — A Star Lord in the Daoist celestial hierarchy. Not to be confused with the Marvel Comics character.`
- AFTER: `星君 — A Star Lord in the Daoist celestial hierarchy, a deity governing a particular star or constellation.`

### KEEP unchanged — with examples:

**Historical institution with dates:**
- GOOD: `舉人 — A provincial graduate under the imperial examination system, the degree awarded to candidates who passed the triennial examinations. Holders were eligible for minor official posts.`

**Geographic with province:**
- GOOD: `佛山 — Fóshān, a major city in Guǎngdōng province, historically one of China's four great martial arts centers.`

**Acupoint with location + martial context:**
- GOOD: `曲池 — Qūchí, the "Pool at the Bend" acupoint, located at the lateral end of the elbow crease. Large Intestine meridian. Striking this point causes numbness and loss of grip strength.`

**Idiom with origin:**
- GOOD: `有眼不識泰山 — Literally "to have eyes but fail to recognize Mount Tai." An idiom for being blind to greatness, alluding to the reverence for Tài Shān as the most sacred of the Five Great Mountains.`

**Real martial school:**
- GOOD: `太極門 — The Tàijí School, practitioners of Tàijíquán, a major internal martial art attributed to the Wǔdāng Mountains tradition.`

**Cultural practice:**
- GOOD: `束脩 — Literally "bundles of dried meat," the traditional tuition gift from student to teacher, dating to the Confucian Analects.`

## After pruning

After all removals and trims:

1. **Sort footnotes by text position** — for each block, find each marker's position in `translated_content` and sort the footnotes array to match
2. **Renumber sequentially per chapter** — [1], [2], [3]... continuous across blocks within a chapter, assigned by text order (leftmost marker = lowest number)
3. **Remove orphan markers** — any `[N]` in text with no matching footnote entry gets stripped
4. **Remove empty footnotes** — any footnote with blank or <20 char explanation after trimming gets removed along with its marker
5. **Verify** — after renumbering, confirm no `[3]` appears before `[2]` in any block

## Output

- `{original_name}_pruned.json` — the cleaned file
- `footnote_prune_report_{work_id}.md` — detailed report with statistics and examples

## Example invocation

```
Process the file /path/to/translated_work.json
```
