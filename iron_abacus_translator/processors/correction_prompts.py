#!/usr/bin/env python3
"""
Correction Prompts — Focused specialist prompts for post-translation correction.

Each prompt addresses a specific category of translation issue. The classifier
tags blocks with issue categories; the applicator concatenates only the relevant
prompts for each block.

Usage:
    from processors.correction_prompts import build_correction_prompt, CORRECTION_CATEGORIES

    prompt = build_correction_prompt(["measurement", "register"])
"""

from typing import List

# =============================================================================
# CATEGORY DEFINITIONS (used by both classifier and applicator)
# =============================================================================

CORRECTION_CATEGORIES = {
    "measurement": "Western units (feet, pounds, miles) where Chinese units expected",
    "weapon": "Weapon translation errors: 長劍 as 'long sword', 寶劍 overriding weapon type, 棒 as cudgel in domestic context",
    "register": "Modern/corporate/casual English in jianghu period context",
    "footnote_placement": "Footnote markers on wrong words, or inline glosses like sabre[dāo]",
    "footnote_consolidation": "Adjacent footnotes on closely related terms that should be merged",
    "footnote_missing": "Missing mandatory footnotes: acupoints, major sects, classical allusions, idiom sources",
    "honorific": "English translations where pinyin honorific expected, or translated surnames",
    "idiom_curse": "Literal calques of Chinese curses/idioms that don't work in English",
    "supernatural": "European supernatural creatures substituted for Chinese ones",
    "technique_name": "Comical or inaccurate verbs in martial technique names",
    "ideogram_leak": "Chinese ideograms (漢字) leaked into translated English text — must be replaced with English or pinyin",
    "char_count": "Reference to number of Chinese characters/words without footnote giving the original ideograms and breakdown",
    "formula_pinyin": "Martial formula, couplet, or mnemonic (口訣) left as pinyin instead of translated to English",
    "organ_metaphor": "Literal body-organ calques where meaning-translation + footnote needed",
    "bare_pinyin": "Common pinyin terms missing tone diacritics (Shifu → Shīfù, Guniang → Gūniáng)",
    "pinyin_sequence": "Repeated pinyin sound effects not italicized (peng peng peng → *pēng pēng pēng*)",
    "suppressed_footnote": "Footnote on a term from the suppress list — should be removed",
    "omission": "Translated text suspiciously short vs Chinese source — content likely omitted",
    "duplicate_text": "Repeated phrases within a block — likely LLM stutter/repetition",
    "unitalicized_honorific": "Honorific pinyin has tone marks but missing *asterisks* for italics",
    "orphan_marker": "Footnote marker [N] with no matching entry, or entry with no marker",
    "western_units": "Western measurement units (feet/miles/pounds) where Chinese units expected",
    "gang_not_clan": "'Gang' used for 幫 organizations — should be 'Clan'",
    "empty_footnote": "Footnote with blank or trivially short explanation",
    "double_space": "Double spaces in body text (cleanup artifact)",
    "gender": "Gender-neutral Chinese (眾人, 二人, 諸位, etc.) translated with masculine English (men, fellows, gentlemen)",
}

# =============================================================================
# SPECIALIST CORRECTION PROMPTS
# =============================================================================

CORRECTION_PROMPTS = {}

CORRECTION_PROMPTS["gender"] = """**GENDER CORRECTION:**
The source Chinese uses gender-neutral terms for groups of people. Check whether the English translation has unnecessarily defaulted to masculine.

Common gender-neutral Chinese → correct English:
- 二人 / 三人 / 眾人 → "the two of them", "the three", "the assembled company", "all present" (NOT "two men", "three men", "the men")
- 諸位 → "all of you", "everyone present" (NOT "gentlemen" unless the speaker is specifically addressing men)
- 大家 → "everyone" (NOT "all men")
- 來人 → "the newcomer", "the arrival" (NOT "the man")
- 旁人 → "bystanders", "onlookers" (NOT "the men nearby")

DO NOT change:
- Deliberately masculine expressions: "no true man", "be a man", "men of the jianghu"
- Cases where context clearly establishes all parties are male (e.g., a scene with only named male characters)
- Honorifics and forms of address that carry gendered meaning (大俠, 女俠, 夫人, etc.)
- Pronouns (he/she) that correctly reflect the Chinese 他/她

Only change the unnecessarily gendered collective nouns. Preserve the register and style of the surrounding prose."""

CORRECTION_PROMPTS["measurement"] = """**MEASUREMENT CORRECTION:**
Chinese units of measurement must be rendered as italicized pinyin with *asterisks*, NEVER converted to Western units. Footnote on first occurrence with the approximate modern equivalent.

Reference:
- 斤 (*jīn*) ≈ 500g / 1.1 lbs
- 兩 (*liǎng*) ≈ 50g (also a unit of silver currency)
- 里 (*lǐ*) ≈ 500m / 0.31 miles
- 丈 (*zhàng*) ≈ 3.3m / 10.8 ft
- 尺 (*chǐ*) ≈ 33cm / 13 in
- 寸 (*cùn*) ≈ 3.3cm / 1.3 in
- 更 (*gēng*) = night watch ≈ 2 hours
- 時辰 (*shíchén*) = double-hour

WRONG: "a good foot" for 一尺 → RIGHT: "a good *chǐ*" with footnote
WRONG: "sixteen pounds" for 十六斤 → RIGHT: "sixteen *jīn*" with footnote
WRONG: "thirty miles" for 六十里 → RIGHT: "sixty *lǐ*" with footnote

The Chinese measurement system is part of the world — converting it erases the setting.

**ITALICIZATION**: All measurement pinyin MUST be wrapped in *asterisks* for italics: *lǐ*, *jīn*, *chǐ*, *zhàng*, *cùn*, *gēng*. NOT plain text li or jin.

**ONOMATOPOEIA**: Pinyin sound effects MUST also be italicized: *sōu sōu sōu*, *pēng pēng pēng*, *dāng*, *chī*. All pinyin in a sequence must be italicized — never drop italics on middle terms. Find every pinyin sound effect in the block and ensure it has asterisks around it."""

CORRECTION_PROMPTS["weapon"] = """**WEAPON CORRECTION — MANDATORY CHANGES:**
You MUST make these substitutions wherever they appear in the text:

1. **"long sword" → "sword"**: Every instance. 長劍 (chángjiàn) is the DEFAULT jiàn in wuxia — not an oversized weapon. "Long sword" implies a specifically large weapon, which is misleading. Find EVERY occurrence of "long sword" or "long swords" and change to "sword" or "swords". This is not optional.

2. **"long sabre" → "sabre"**: Same logic. 長刀 is the default dāo.

3. **寶劍 tracks the ACTUAL weapon**: If the character is holding a dagger (匕首) but the text says 寶劍, translate as "treasured blade" not "treasured sword."

4. **錐 as thrown weapon = "dart" not "spike"**: 毒龍錐 = "Poison Dragon Darts."

5. **棒 in domestic context = "poker" not "cudgel"**: 撥火棒 = "fire poker."

6. **Weapon idioms → translate the idiom**: 戟指 = "jabbed an accusing finger" NOT "pointed with a halberd-like finger."

Scan the ENTIRE block text. Change EVERY instance of "long sword(s)" to "sword(s)"."""

CORRECTION_PROMPTS["register"] = """**REGISTER CORRECTION — MANDATORY CHANGES:**
Find and replace every instance of modern English that breaks the wuxia period setting. These are NOT suggestions — every flagged term MUST be changed:
- **Modern crime slang**: "heist" → "venture/exploit"; "mark" → "quarry"; "gang" → "Clan" (for 幫); "gig/job/score/racket/hustle" → period alternatives
- **Formal/business English**: "Messrs." → "those two, X and Y"; "aforementioned/hereby/pursuant to" → natural speech
- **Modern casual idioms**: "a cut above the rest" → "in a class of his own"; "top-notch/spot-on/level up" → period equivalents
- **Cold War/military jargon**: "mutually assured destruction" → "a desperate gambit to take both lives" or "perishing together"
- **Corporate/legal tone**: any phrasing that sounds like a boardroom, courtroom, or Pentagon briefing

**Test**: if the word would sound natural in a modern crime thriller, a corporate memo, or a solicitor's letter, it's wrong for wuxia. If it would sound natural in a historical adventure novel or a chivalric romance, it fits."""

CORRECTION_PROMPTS["footnote_placement"] = """**FOOTNOTE MARKER PLACEMENT CORRECTION:**
Every footnote marker [N] MUST appear immediately after the English word/phrase that corresponds to the footnoted Chinese ideogram. Not on a nearby word, not at end of sentence.

WRONG: a footnote on 反清 (anti-Qing) placed on "Gāng Leader Fàn" → RIGHT: placed on "anti-Qīng"
WRONG: a footnote on 吳越 placed on "barked" → RIGHT: placed on "Wú-Yuè"

**MISMATCHED FOOTNOTES**: If a marker is on a word but the footnote explains a DIFFERENT term entirely (e.g. marker on *Shīxiōng* but footnote explains 師妹 shīmèi — wrong term), this is a mismatch. Fix by:
1. If the correct term for the footnote appears elsewhere in the block, move the marker there
2. If the correct term is NOT in this block, REMOVE the footnote entirely (it belongs to a different block)
3. Check every [N] marker: does the word it's attached to match the ideogram/pinyin in the footnote? If not, fix or remove.

Also fix:
- Inline glosses like `sabre[dāo]` or `sword[jiàn]` → convert to proper numbered footnotes
- Markers with extra spaces: "term [1]" → "term[1]"
- Markers AFTER punctuation: "term.[1]" → "term[1]." / "term,[1]" → "term[1]," — the marker goes before periods, commas, semicolons, not after them

Move each marker to the correct word. Do NOT change the footnote content unless removing a mismatched footnote."""

CORRECTION_PROMPTS["footnote_consolidation"] = """**FOOTNOTE CONSOLIDATION — MANDATORY:**
When two or more footnotes explain the same concept or closely overlapping concepts, you MUST merge them into ONE footnote and REMOVE the redundant ones. Do NOT add new footnotes — REDUCE the count.

Steps:
1. Identify footnotes whose ideograms/explanations overlap (e.g. 吳越 explained in one footnote, and 吳 explained separately in another)
2. MERGE the content into a single, comprehensive footnote
3. REMOVE the redundant footnote(s) entirely
4. Place the surviving marker on the most appropriate term
5. RENUMBER all remaining markers sequentially [1], [2], [3]...

WRONG: 吳越[3] explaining Wú-Yuè rivalry + 吳[4] explaining Wú state separately → RIGHT: ONE footnote on 吳越 covering both, [4] deleted, subsequent markers renumbered
WRONG: 滿清[6]韃子[7] with overlapping content → RIGHT: ONE footnote on 滿清韃子, renumber
WRONG: 越王[7] explaining King of Yuè + 越國[8] explaining State of Yuè in same block → RIGHT: ONE footnote on 越王 covering Gōujiàn and his state, [8] deleted

Also look for: a person's name footnoted AND their title/role footnoted separately with overlapping content. If 勾踐[6] and 越王[7] both explain who Gōujiàn is, merge into one.

The goal is FEWER footnotes, not more. If you started with 4 footnotes and two overlap, the output should have 3."""

CORRECTION_PROMPTS["footnote_missing"] = """**MISSING FOOTNOTE CORRECTION:**
Add footnotes ONLY for terms that actually appear in the source Chinese text of this block. Do NOT add footnotes for related concepts, associated idioms, or background knowledge that isn't in the source text. If 臥薪嘗膽 doesn't appear in the Chinese source, do NOT add a footnote for it even if the passage is about Gōujiàn.

**NEVER add footnotes for SUPPRESSED TERMS.** The following common terms are deliberately NOT footnoted — the reader already knows them: 江湖 (jiānghú), 武林, 氣/氣功, 內功, 輕功, 劍, 刀, and all terms on the suppress list. If a term is already translated clearly in the English, it does not need a footnote.

Add footnotes for these mandatory categories if missing AND the term appears in the source AND is not suppressed:

**Acupoints (穴)**: EVERY acupoint MUST have a footnote with: ideogram, pinyin, literal meaning of the name, anatomical location on the body, associated meridian (e.g. Kidney meridian, LI-20). No generic wuxia explainers.

**Major wuxia sects** (少林, 武當, 崑崙, 峨嵋, 華山, etc.): On first occurrence, footnote with: name meaning, religious/philosophical affiliation (Taoist/Buddhist/secular), martial philosophy, signature techniques. Cross-canon knowledge, not plot-specific.

**Classical allusions and wordplay**: When a character quotes or references classical sources (Three Kingdoms, Book of Han, historical figures), footnote the source and significance.

**Canonical strategic/philosophical references**: If an idiom comes from the Thirty-Six Stratagems, Art of War, Dao De Jing, Zhuangzi, Confucian classics — identify the source and number.

**十八般武藝**: Always footnote (eighteen martial arts / canonical weapons classification).

**Legendary named weapons and artifacts**: When a passage lists or names famous historical/legendary weapons (e.g. 湛盧, 純鈞, 勝邪, 魚腸, 巨闕 — the Five Swords of Yuè), each named weapon should be footnoted with: the ideogram, pinyin, literal meaning of the name, and its legendary significance. These are among the most famous weapons in Chinese history/mythology and the reader needs to know what the names mean.

**Character count references**: When text says "seven characters" or "twelve words" referring to Chinese text, add a footnote with the original Chinese and character-by-character breakdown.

**Reign year dates**: When the text mentions a date in reign-year format (e.g. "the forty-fifth year of the Qiánlóng reign"), add a footnote with the CE conversion. Formula: dynasty_start + reign_year - 1. Common reign periods: 康熙 starts 1662, 雍正 1723, 乾隆 1736, 嘉慶 1796, 道光 1821, 咸豐 1851, 同治 1862, 光緒 1875. E.g. 乾隆四十五年 = 1736 + 45 - 1 = 1780 CE.

**REMOVE trivial footnotes**:
- If a footnote describes a sect, faction, or character as "fictional," "a fictional sect," "invented by the author" — REMOVE it. Fictional in-story elements are NOT cultural terms.
- If a footnote explains the project's own translation conventions ("rendered in pinyin," "martial-lineage honorifics like this are rendered...," "in the jiānghú such honorifics are earned") — REMOVE it. The footnote should explain the TERM, not the translation methodology.
- If a footnote merely restates what the English already says with no added cultural knowledge — REMOVE it.

- If a footnote is REDUNDANT with the surrounding text — the prose already explains or contextualises the term — REMOVE it. A footnote on "the Buddha Śākyamuni" when the text already says "the Buddha Śākyamuni descended into this world" adds nothing the reader can't already see.

Delete the footnote, remove the marker from the text, and renumber remaining markers."""

CORRECTION_PROMPTS["honorific"] = """**HONORIFIC CORRECTION — MANDATORY:**
ALL martial/social honorifics must be italicized pinyin wrapped in *asterisks*, never English translations, never bare pinyin without asterisks.

**English → pinyin (WRONG → RIGHT):**
- "Senior Brother Ruǎn" → "Ruǎn *Shīxiōng*"
- "Clan Leader Fàn" → "Fàn *Bāngzhǔ*"
- "Village Master Dù" → "Dù *Zhuāngzhǔ*" (and 莊 = manor, not village)
- "Elder Physician" → Physician *Qiánbèi*
- "Old Beggar" → Beggar *Gōnggōng*

**Bare pinyin → italicized pinyin (WRONG → RIGHT):**
- "Yīn shīxiōng" → "Yīn *Shīxiōng*" (add asterisks)
- "Miáo gūniáng" → "Miáo *Gūniáng*" (add asterisks)
- "Táo zhàizhǔ" → "Táo *Zhàizhǔ*" (add asterisks)

If you see ANY honorific pinyin without *asterisks* around it, ADD the asterisks. This includes: shīxiōng, shīdì, shīfù, gūniáng, fūrén, dàgē, lǎoxiōng, qiánbèi, zhǎngmén, bāngzhǔ, zhuāngzhǔ, biāotóu, zǒngguǎn, fāngzhàng, dàshī, zhēnrén, and all other honorifics.

**Address vs. description rule:**
- Social/family (姑娘, 大哥, 夫人, 老兄): pinyin in direct address, English ok in narration
- Martial-lineage (師兄, 師父, 前輩, 掌門, 幫主, 真人, 方丈): pinyin ALWAYS, even in narration
- Epithets (金面佛, 飛狐): English in narration, pinyin in direct address

**Translated surnames — NEVER:** 熊 = Xióng not "Bear"; 馬 = Mǎ not "Horse"; 龍 = Lóng not "Dragon."

Each honorific footnoted on first occurrence with: ideogram, pinyin, literal meaning, social relationship encoded."""

CORRECTION_PROMPTS["idiom_curse"] = """**IDIOM AND CURSE CORRECTION:**
Chinese curses and idioms must be translated by INTENT, not literally. Literal calques that mean nothing in English must be replaced.

**Curses:**
- 短命的 = "you accursed wretch!" NOT "you short-lived villain" (no English speaker curses by predicting lifespan)
- 該死的 = "damned/accursed"
- 挨千刀的 = vicious curse, render by tone
- 他媽的 / 他奶奶的 / 你奶奶的 = "goddamn" / "fucking" — NOT "his mother's" / "his grandmother's" (these are expletive intensifiers, not family references)
- 操他奶奶的熊 = "Fuck that gutless wretch!" NOT "Fuck his grandmother's bear!" (熊 = coward per 狗熊, not an actual bear)

**Idioms:**
- 喝錯了醋 = "misdirect your anger" NOT "mistake your vinegar"
- 無毒不丈夫 = "without venom, one is no true man" (footnote the proverb)
- 甘拜下風 in a taunt = "we concede you the upper hand" (sarcastic)

Vivid Chinese idioms with striking imagery: translate semi-literally to preserve the image, then add a footnote. Dead metaphors with no interesting imagery: just translate idiomatically."""

CORRECTION_PROMPTS["supernatural"] = """**SUPERNATURAL TERMINOLOGY CORRECTION:**
Do NOT substitute European supernatural creatures for Chinese ones.

Chinese supernatural vocabulary:
- 鬼 (guǐ) = ghost/departed spirit — NOT "goblin"
- 妖 (yāo) = demon/shapeshifter — NOT "elf"
- 魔 (mó) = devil/fiend — NOT "ogre"
- 精 (jīng) = animal spirit/sprite — NOT "fairy"
- 仙 (xiān) = immortal — NOT "angel"

Idioms: 裝神弄鬼 = "playing mysterious tricks" or "putting on a ghostly charade" — NOT "playing at ghosts and goblins."

Use the Chinese framework (ghosts, demons, immortals, spirits) or plain English equivalents. Never import Western folklore creatures."""

CORRECTION_PROMPTS["technique_name"] = """**TECHNIQUE NAME CORRECTION:**
Martial technique names (招式) are poetic images describing motion. The English must be dignified and physically accurate.

Common verb errors in technique names:
- 吐 (tǔ) = "project/extend/lash forth" — NOT "spit/vomit"
- 探 (tàn) = "probe/reach" — NOT "explore"
- 撲 (pū) = "pounce/strike" — NOT "throw oneself"
- 回 (huí) = "return/reverse" — NOT "go back"

WRONG: "Yellow Dragon Spits Its Whiskers" → RIGHT: "Yellow Dragon Turns and Lashes Its Whiskers"

**Test**: if the English technique name sounds comical or disgusting, the verb choice is wrong. Think about what the body is actually doing and choose the English that matches the physical motion.

**Combat logic**: Positional verbs must match physical direction. 豎劍相架 when blocking a low strike = "drop his sword to parry" NOT "raise his sword to parry."

Same technique MUST be translated identically every time it appears.

**Martial formulae and mnemonics (口訣)**: Combat couplets, rhyming mnemonics, and martial formulae must be TRANSLATED to English, not left as pinyin. These encode meaningful combat instructions or poetic imagery that the reader needs to understand. Render them as dignified English verse, and add a footnote with the pinyin and martial context.

**Technique footnotes**: Do NOT footnote technique names that merely describe the image of the move — "White Rainbow Pierces the Sun" does not need a footnote saying "this technique resembles a rainbow." HOWEVER, if the technique name references a genuine classical allusion (白虹貫日 is a classical omen of assassination — a white rainbow crossing the sun portended an attempt on a ruler's life), then a footnote explaining the allusion IS valuable. The test: does the footnote add cultural knowledge beyond what the English name already conveys? If it just restates the imagery, remove it."""

CORRECTION_PROMPTS["organ_metaphor"] = """**BODY-ORGAN METAPHOR CORRECTION:**
Chinese body-organ metaphors encode a different system from English. Translate by MEANING, add a footnote explaining the Chinese body-metaphor on first occurrence.

Key mappings:
- 膽 (dǎn, gall bladder) = courage. "Their gall bladders quivered" → "their courage failed them" + footnote
- 心 (xīn, heart) = mind/thought. 心想 = "thought to himself" not "felt in his heart"
- 腸 (cháng, intestines) = deep feeling. 斷腸 = "heartbroken" + footnote explaining severed intestines
- 肝 (gān, liver) = sincerity/loyalty. 肝膽相照 = "utter mutual trust" + footnote
- 肺 (fèi, lungs) = depths of feeling. 肺腑之言 = "words from the depths of one's being"

The reader should learn that courage lives in the gall bladder, loyalty in the liver, and grief in the intestines."""

CORRECTION_PROMPTS["ideogram_leak"] = """**IDEOGRAM LEAK CORRECTION — MANDATORY:**
Chinese characters (漢字/ideograms) have been detected in the English translation. This is a critical error — the output must contain ZERO Chinese characters.

For each Chinese term found in the English text:
1. If it is a title, rank, or institution: translate to English with a footnote giving the pinyin. Example: 侍衛班領 → "Guard Captain[N]" with footnote explaining the imperial guard rank.
2. If it is a proper noun (name, place): render as pinyin with tone marks. Example: 商家堡 → "Shāngjiābǎo."
3. If it is a martial formula or couplet: translate to English with a footnote giving the pinyin.
4. If it is a parenthetical gloss like "Guard Captains (侍衛班領)": remove the ideograms entirely — the English translation is sufficient. If a footnote is warranted, move the Chinese to a footnote with pinyin.

Scan the ENTIRE block. Every Chinese character must be eliminated from the body text."""

# =============================================================================
CORRECTION_PROMPTS["formula_pinyin"] = """**MARTIAL FORMULA / COUPLET CORRECTION — MANDATORY:**
Martial formulae, combat couplets, training mnemonics, and rhyming martial instructions (口訣) must be TRANSLATED to English, not left as pinyin. The reader needs to understand the meaning — these encode combat instructions or poetic imagery.

Steps:
1. Find the pinyin formula/couplet in the text
2. Replace it with an English translation that preserves the poetic structure and martial meaning
3. Add a footnote with: the original Chinese ideograms, full pinyin, and a note on the martial context

Example:
WRONG: '*Lùhǎi yíng mén sān bù gù, pī quán tiāo dǎ bù róng kuān*'
RIGHT: 'The Land and Sea greet the gate, three cares cast aside; / The splitting fist lifts and strikes, allowing no quarter.'[N]
With footnote: 陸海迎門三不顧，劈拳挑打不容寬 (lùhǎi yíng mén sān bù gù, pī quán tiāo dǎ bù róng kuān) — A Cháquán mnemonic couplet encoding combat principles."""

CORRECTION_PROMPTS["char_count"] = """**CHARACTER COUNT FOOTNOTE — MANDATORY:**
The text references a count of Chinese characters or words (e.g. "thirteen characters," "seven words"). This is meaningless to an English reader without the original Chinese.

Add a footnote that provides:
1. The original Chinese ideograms being counted
2. A character-by-character or word-by-word breakdown with pinyin

Example: "The thirteen characters" → add footnote: "打遍天下無敵手金面佛苗人鳳 (dǎ biàn tiānxià wú díshǒu Jīnmiànfó Miáo Rénfèng) — 'Fights across the world without meeting his match, the Golden-Faced Buddha Miáo Rénfèng.' Thirteen characters in Chinese, spoken as a single breath to convey the full weight of the epithet."

Look at the Chinese source to find the exact text being referenced. Place the footnote marker on or immediately after the count phrase."""

CORRECTION_PROMPTS["bare_pinyin"] = """**BARE PINYIN CORRECTION — MANDATORY:**
Common pinyin terms are missing tone diacritics. Every pinyin syllable in the output MUST carry correct tone marks. Find and fix ALL instances:

Common fixes:
- Shifu → Shīfù, Shixiong → Shīxiōng, Shimei → Shīmèi, Shige → Shīgē
- Guniang → Gūniáng, Bangzhu → Bāngzhǔ, Zhangmen → Zhǎngmén
- Dashi → Dàshī, Fangzhang → Fāngzhàng, Qianbei → Qiánbèi
- Gongzi → Gōngzǐ, Dage → Dàgē, Laoye → Lǎoyé
- Jianghu → Jiānghú, Wulin → Wǔlín, Qinggong → Qīnggōng

Scan the ENTIRE block. Every pinyin term must have tone marks on every syllable."""

CORRECTION_PROMPTS["pinyin_sequence"] = """**PINYIN SEQUENCE ITALICIZATION — MANDATORY:**
Repeated pinyin sound effects (onomatopoeia) MUST be wrapped in *asterisks* for italics and must carry tone diacritics. Find every sequence of repeated syllables that represents a sound effect and fix it.

WRONG: peng peng peng → RIGHT: *pēng pēng pēng*
WRONG: sou sou sou → RIGHT: *sōu sōu sōu*
WRONG: dang dang → RIGHT: *dāng dāng*
WRONG: *pēng* pēng *pēng* → RIGHT: *pēng pēng pēng* (all inside one italic span)

ALL terms in the sequence must be inside the same italic span with tone marks on every syllable."""

CORRECTION_PROMPTS["suppressed_footnote"] = """**SUPPRESSED FOOTNOTE REMOVAL — MANDATORY:**
This block contains a footnote on a term from the suppress list. These common terms are deliberately NOT footnoted — the reader encounters them frequently and already knows them. Remove the footnote entry and its marker from the text. Renumber remaining footnotes sequentially."""

CORRECTION_PROMPTS["omission"] = """**OMISSION CORRECTION — MANDATORY:**
The English translation appears to be missing significant content from the Chinese source. Compare the source and translation sentence by sentence. Identify what has been omitted and translate the missing content, inserting it at the correct position. Do NOT summarize — translate the missing text in full, matching the style of the surrounding translation."""

CORRECTION_PROMPTS["duplicate_text"] = """**DUPLICATE TEXT REMOVAL — MANDATORY:**
The translated text contains a repeated phrase or sentence (LLM stutter). Find the duplicated passage and remove the repetition, keeping only one instance. Ensure the text reads naturally after the removal."""

CORRECTION_PROMPTS["unitalicized_honorific"] = """**UNITALICIZED HONORIFIC CORRECTION — MANDATORY:**
Honorific pinyin terms MUST be wrapped in *asterisks* for italics. Find every honorific in the text and ensure it has asterisks. Do NOT change the pinyin itself — just add the asterisks.

WRONG: Shīfù → RIGHT: *Shīfù*
WRONG: Gūniáng → RIGHT: *Gūniáng*
WRONG: Bāngzhǔ → RIGHT: *Bāngzhǔ*

Common honorifics: Shīfù, Shīxiōng, Shījiě, Shīmèi, Shīdì, Shīgē, Gūniáng, Bāngzhǔ, Zhǎngmén, Dàshī, Fāngzhàng, Qiánbèi, Dàgē, Gōngzǐ, Lǎoyé, Gōnggōng."""

CORRECTION_PROMPTS["orphan_marker"] = """**ORPHAN MARKER CORRECTION — MANDATORY:**
There is a mismatch between footnote markers [N] in the text and footnote entries. Either:
- A marker [N] exists in the text but no footnote entry has key=N → REMOVE the marker
- A footnote entry exists but no marker appears in the text → REMOVE the footnote entry
After cleanup, renumber all markers and footnotes sequentially starting from [1]."""

CORRECTION_PROMPTS["western_units"] = """**WESTERN UNIT CORRECTION — MANDATORY:**
Western measurement units have been detected. Chinese units must be rendered as italicized pinyin, not converted to Western equivalents. Footnote on first occurrence with the approximate modern equivalent.

- feet/foot → *chǐ* (尺, ≈ 33cm). "three feet" for 三尺 → "three *chǐ*"
- miles → *lǐ* (里, ≈ 500m). "thirty miles" for 六十里 → "sixty *lǐ*"
- pounds → *jīn* (斤, ≈ 500g). "ten pounds" for 十斤 → "ten *jīn*"
- inches → *cùn* (寸, ≈ 3.3cm). "an inch" for 一寸 → "one *cùn*"
- yards → *zhàng* (丈, ≈ 3.3m). "ten yards" for 三丈 → "three *zhàng*"

The Chinese measurement system is part of the world — converting it erases the setting."""

CORRECTION_PROMPTS["gang_not_clan"] = """**GANG → CLAN CORRECTION — MANDATORY:**
The word "Gang" has been used for a 幫 (bāng) organization. In wuxia convention, 幫 is translated as "Clan" — it denotes a structured martial organization with ranks, rules, and lineage. "Gang" implies modern criminality.

WRONG: "Beggar Gang" → RIGHT: "Beggar Clan"
WRONG: "Red Flower Gang" → RIGHT: "Red Flower Clan"

Find every instance of "[Name] Gang" and change to "[Name] Clan"."""

# CORRECTION SYSTEM PROMPT (wraps the specialist sections)
# =============================================================================

_CORRECTION_SYSTEM_TEMPLATE = """You are an exacting translation corrector for Classical Chinese literature. A classifier has identified specific issues in this block. You MUST fix every instance of every flagged issue. Do not leave any flagged issue uncorrected. Do not rewrite prose style or change anything outside the flagged categories.

**CRITICAL — DO NOT TRUNCATE**: You MUST return the COMPLETE text of the translation. Every sentence from the original must appear in your output. You are making surgical corrections to specific words or phrases — the overall text length should remain approximately the same. If the input has 10 sentences, your output must have 10 sentences. Dropping sentences or paragraphs is a critical failure.

**CRITICAL FORMAT RULE**: Footnote markers are [1], [2], [3] — plain square brackets with numbers. NEVER use HTML tags like <sup>1</sup> or superscript formatting. Always [N].

**This block has been flagged for the following issues. Fix ALL of them:**

{specialist_rules}

**IMPORTANT**: You are being called because the classifier detected these issues. They ARE present — find them and fix them. Do not second-guess the classification. If the rules say "long sword" should be "sword" and the text contains "long sword", change it. If the rules say Western units should be pinyin, find every Western unit and convert it.

**FOOTNOTE RULES**: For existing footnotes, you may REMOVE them or MOVE their markers, but NEVER rewrite their explanations. Return existing footnotes with their original ideogram, pinyin, and explanation UNCHANGED. Only create NEW footnote entries for genuinely missing footnotes. If you have nothing to add or remove, return the footnotes exactly as given.

**Output requirements:**
Return ONLY valid JSON:
{{
  "corrected_text": "<the COMPLETE corrected English translation — every sentence must be present, do NOT omit or summarize any part>",
  "corrected_footnotes": [
    {{
      "key": 1,
      "ideogram": "<chinese_characters>",
      "pinyin": "<romanized_pronunciation>",
      "explanation": "<explanation>"
    }}
  ],
  "changes_made": ["brief description of each change — list EVERY change you made"]
}}"""


def build_correction_prompt(tags: List[str]) -> str:
    """Build a focused correction system prompt from issue tags.

    Concatenates only the specialist rules relevant to the given tags.
    Returns the complete system prompt ready for an API call.
    """
    sections = []
    for tag in tags:
        if tag in CORRECTION_PROMPTS:
            sections.append(CORRECTION_PROMPTS[tag])

    if not sections:
        return ""

    specialist_rules = "\n\n".join(sections)
    return _CORRECTION_SYSTEM_TEMPLATE.replace("{specialist_rules}", specialist_rules)
