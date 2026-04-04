# Review-Derived Prompt Guidance — D60 Chapters 3–4

**Source**: `review_D60_ch3_4_reviewed.json` — 19 findings from D60 雪山飛狐 (The Flying Fox of Snowy Mountain, Jin Yong), chapters 3–4.
**Purpose**: Reference document for future translation and validation prompt adjustments. No prompts modified.

---

## 1. Translation Prompt Adjustments

Patterns from **accepted** findings — issues the model produced that need correction.

### 1a. Misattributed footnotes / wrong ideogram match

**Finding**: ch3 block_0003
**Source Chinese**: 倒也生不出氣 — model footnoted 清 as "Qing dynasty" when 清 here is part of 清脆 ("clear and crisp"), not the dynasty name. Additionally, 京片子 (Běijīng dialect) warranted a footnote but was missing.

**Principle**: The model must check each ideogram IN CONTEXT before generating a footnote. Single-character ideograms that are part of compound words must not be extracted as standalone terms. 清 inside 清脆 is not 清朝. The surrounding characters must be examined before assigning cultural significance.

### 1b. Hallucinated weapon provenance

**Finding**: ch3 block_0012
**Source Chinese**: 取了當年在江湖上所用的紫金刀 — "retrieved the purple-gold sabre he had used in his jianghu days"
**What the model did**: Claimed the sabre was "the personal weapon of Lǐ Zìchéng" — fabricated historical provenance.
**User comment**: "purple gold sabre is not the personal weapon. It is a similar weapon to that used"

**Principle**: Do NOT invent specific historical provenance for generic weapon types. 紫金刀 is a weapon type (purple-gold sabre), not a named artifact with a known history. Footnotes for weapons should describe the type, not hallucinate ownership lineage.

### 1c. Missing cultural footnotes for genuine allusions

Multiple findings where the model failed to footnote terms that genuinely warrant explanation:

| Finding | Source Chinese | What was missing |
|---------|--------------|------------------|
| ch3 block_0017 | 夜明寶珠 (night-luminous pearl) | Footnote present — correct |
| ch3 block_0080 | 江湖郎中 (itinerant physician) | Missing footnote — should explain the tradition of wandering healers in jianghu society |
| ch4 block_0025 | 貂蟬嫁給了張飛 (Diāochán married Zhāng Fēi) | Classical Three Kingdoms allusion — needs footnote explaining this folk embellishment of the Romance of the Three Kingdoms, where Diāochán's fate after Lǚ Bù's death varies across traditions |
| ch4 block_0117 | 神藏穴 (Shéncáng acupoint) | Needs point-specific medical/martial explanation |

**User comment on 神藏穴**: "explain the location and meaning, but we don't have to explain why acupoint striking is significant in wuxia. It should be point-specific"

**Principle**: Footnote genuine classical allusions and technical martial terms. EVERY acupoint (穴) that appears in the text MUST be footnoted with: (a) the ideogram and pinyin, (b) the literal meaning of the name (e.g. 神藏 = "spirit storehouse"), (c) anatomical location on the body, (d) the associated meridian (e.g. Kidney meridian, Conception vessel). Do NOT include generic wuxia explainers about why acupoint striking is significant in martial arts fiction — the reader will figure that out from context. Each footnote should be point-specific: what it is, what it means, where it is.

### 1d. Pinyin compound spacing inconsistency

**Finding**: ch4 block_0062
**Source Chinese**: 金面佛 rendered as both "Jīnmiàn Fó" (spaced) and "Jīnmiànfó" (joined) within the same chapter.
**User comment**: "can we figure a consistent rule for translation and validation of names (split or not), and inject it into prompts"

**Principle**: See Section 3 (Open Question) for the proposed rule.

---

## 2. Validation Prompt Adjustments

Patterns from **rejected** findings — the reviewer flagged these, but the current translation is correct. Validation prompts should stop generating false positives for these patterns.

### 2a. Wuxia epithets are self-explanatory — don't footnote

**Finding**: ch3 block_0020
**Source Chinese**: 雪山飛狐, 金面佛苗爺 — reviewer wanted cultural footnotes for these epithets.
**User verdict**: "not necessary. this is trivial"

**Principle**: In-story wuxia epithets (Snow Mountain Flying Fox, Golden-Faced Buddha) are self-explanatory in context and part of the narrative. Do not flag them as missing cultural footnotes.

### 2b. Deliberate calques preserve Chinese courtesy register

**Finding**: ch3 block_0024
**Source Chinese**: 姑娘芳名是甚麼 → "What is *Gūniáng's* fragrant name?" (per Principle 38: 姑娘 as direct address → pinyin)
**Reviewer complaint**: "overly literal calque"
**User verdict**: "this is fine as is"

**Principle**: Deliberate calques that preserve Chinese courtesy register are a feature, not a bug. "Fragrant name" (芳名) is idiomatic in wuxia English translation. Validation should not flag register-preserving calques as errors.

### 2c. Moderate variation in names/titles/address is natural

**Findings**: ch3 block_0069, ch3 block_0093-0094, ch4 block_0098
- Reviewer flagged 闖王/Chuáng-Wáng inconsistency
- Reviewer flagged 公公 suffix variations
- Reviewer flagged 胡夫人 vs "the lady" variation

**User comments**:
- "moderate variation is fine"
- "Physician Elder, Beggar Elder makes sense... they are Elders playing roles" → **Superseded**: under the pinyin-honorifics convention, these become e.g. *Qiánbèi* with footnote, not English "Elder"
- "too much consistency of address when reminiscing makes it flat"

**Principle**: Validation should NOT flag moderate address variation. Characters naturally use different forms of address in different contexts — formal vs. familiar, narration vs. dialogue, reminiscence vs. present action. Rigid consistency in forms of address makes prose flat and unnatural. Only flag variation when it causes genuine reader confusion (e.g., two different characters referred to by the same epithet). Note: all honorifics/address forms are now rendered as italicized pinyin per Principle 38 — variation in *which* honorific is used is still natural and should not be flagged.

### 2d. Mildly archaic register is appropriate for wuxia

**Finding**: ch3 block_0112
**Source Chinese**: 鬼鬼祟祟 → "skulk about in the shadows"
**Reviewer complaint**: "anachronistic register"
**User verdict**: "I don't think it is anachronistic. slightly old fashioned works"

**Principle**: Mildly archaic English register is appropriate for wuxia translation. Words like "skulk," "ere," "forthwith" in moderation fit the genre. Do not flag slightly old-fashioned diction as anachronistic unless it is genuinely jarring (e.g., Elizabethan English in modern dialogue).

### 2e. Past perfect in dialogue recounting past events is correct

**Finding**: ch3 block_0086
**Translation**: "Old Beggar had been wounded"
**Reviewer complaint**: tense shift
**User verdict**: "had been works better in dialog"

**Principle**: Past perfect inside dialogue that recounts earlier events is correct English grammar. A character saying "he had been wounded" when narrating a past event within past-tense dialogue is standard usage. Do not flag it.

### 2f. In-story elements are not cultural terms

**Findings**: ch3 block_0119, ch4 block_0012
- 飛天狐狸 (Flying Fox) — fictional character epithet
- 天龍門 (Heavenly Dragon Sect) — fictional faction
- 鐵盒兒 (iron box) — plot MacGuffin

**User comments**: "these are in-story characters" / "iron box is like a spoiler"

**Principle**: Fictional faction names, character epithets, and plot devices are NOT cultural terms. Never footnote them. Additionally, footnotes must never spoil plot significance or telegraph upcoming reveals. If an object's importance is revealed later in the narrative, a footnote that pre-explains its significance ruins the reading experience.

### 2g. 老兄 → pinyin *Lǎoxiōng* (updated)

**Finding**: ch4 block_0005
**Source Chinese**: 老兄
**Original verdict**: "brother works well here... it evokes wary familiarity with a stranger"
**Updated per Principle 38**: All honorifics are now italicized pinyin. Render as *Lǎoxiōng* with a first-occurrence footnote: "老兄 (lǎoxiōng) — literally 'old brother'; a casual, slightly wary form of address between jianghu men of roughly equal standing who are not yet familiar. It signals neither deference nor hostility — a probing, fraternal neutrality."

**Principle**: 老兄 is rendered as *Lǎoxiōng*, not "brother." The footnote carries the register information that "brother" used to convey. The pinyin preserves the Chinese address system; the footnote teaches the reader the social nuance.

### 2h. Mildly unusual but comprehensible collocations are fine

**Finding**: ch3 block_0124
**Source Chinese**: 粗大的刀疤 → "coarse sabre scar"
**Reviewer flagged**: word choice

**Principle**: Slightly unusual but comprehensible English collocations are acceptable. "Coarse scar" evokes texture and roughness — it reads as deliberate. Only flag collocations that are genuinely confusing or ungrammatical.

### 2i. 點子 → "quarry" in jianghu context (→ consolidated into Principle 32)

**Finding**: ch4 block_0012
**User comment**: "Quarry for 點子 works better than mark"

**Principle**: See Principle 32 (general register rule). 點子 = "quarry" not "mark" — "mark" is modern Western slang.

---

## 3. Open Question: Pinyin Compound Spacing

**Issue**: No consistent rule exists for when pinyin compounds are joined vs. spaced. This causes inconsistency within and across chapters (e.g., Jīnmiàn Fó vs. Jīnmiànfó).

**Proposed rule** (for user review):

| Category | Rule | Example |
|----------|------|---------|
| Personal names | Family + given spaced, given name joined | Miáo Ruòlán, Hú Yīdāo |
| Epithets (in direct address only) | Single joined word | *Jīnmiànfó*, *Fēitiānhúli* (narration uses English: Golden-Faced Buddha, Sky-Flying Fox) |
| Place names | Spaced by semantic unit | Xuě Shān, Tiānlóng Mén |
| Honorifics/suffixes | Joined to name, italicized | Miáo-*yé*, Hú-*Dàgē* |

This rule should be injected into both translation and validation prompts once approved.

---

## Summary of Actionable Principles

### For translation prompts:
1. Check ideograms in compound-word context before footnoting
2. Never hallucinate historical provenance for generic weapon types
3. Footnote genuine classical allusions (Three Kingdoms, historical figures) and technical martial terms
4. EVERY acupoint must be footnoted: ideogram, pinyin, literal name meaning, anatomical location, associated meridian. No generic wuxia explainers — point-specific only
4a. Major wuxia sects (Shàolín, Wǔdāng, Kūnlún, etc.) get detailed footnotes: name meaning, religious affiliation, martial philosophy, signature techniques. Cross-canon knowledge, not plot-specific.
4b. Pinyin sound effects must all be italicized consistently — no dropping italics on middle terms in a sequence
4c. Distinctively Chinese material culture objects (炕 kàng, 火摺子 fire-striker, etc.) must be footnoted on first use — translate to English, footnote with what it is and how it works. Universal objects (inn, chair) need no footnote; weapons have their own rules (10-12)
5. General register rule (Principle 32): no modern English for jianghu concepts — 點子 → "quarry" not "mark"; 幫 → "Clan" not "Gang"; 大案 → "ventures" not "heists"
7. Footnote markers MUST be placed on the English word/phrase that corresponds to the footnoted Chinese ideogram, not at arbitrary positions in the sentence. E.g. if the footnote explains 十五個吊桶打水 (the fifteen-buckets idiom), the marker goes on "fifteen buckets being drawn from a well" — NOT on an unrelated word like "Xìnghàn" that happens to be nearby. Similarly, a footnote on 反清 (anti-Qing) must be placed on "anti-Qīng", not on a nearby name like "Fàn *Bāngzhǔ*". The reviewer should flag any footnote whose marker is not adjacent to its corresponding English translation.
8. Pinyin tone marks must NEVER appear on English words. Under the pinyin-honorifics convention (Principle 38), titles and honorifics are always italicized pinyin: "Fàn *Bāngzhǔ*", not "Clan Leader Fàn" or the hybrid "Gāng Leader Fàn." The model must not mix diacritics into English words. If a title appears in English context (e.g. narration explaining a role), the English gloss belongs in the footnote, not inline.
9. Established martial arts loanwords must be preserved, not translated literally. 擒拿 (qínná) is a recognized term in English martial arts writing — translate 大擒拿手 as "Great Qínná Hand" or "Dà Qínná Shǒu", NOT "Great Seizing and Grasping Art." Similarly: 氣功 = qìgōng (not "breath work"), 太極 = tàijí (not "supreme ultimate"), 點穴 = diǎnxué (not "acupoint striking") when used as a named discipline. The model should recognize which martial terms have established English loanword status.
10. 長劍 (chángjiàn) = "sword", not "long sword." In wuxia, 長劍 is the default term for a standard jiàn (as distinct from 短劍 dagger or 匕首 dirk). Translating it as "long sword" implies a specifically oversized weapon, which is misleading. Same applies to 長刀 in most contexts — just "sabre" unless the text is explicitly contrasting weapon sizes.
11. 寶劍 (bǎojiàn) does not always mean "treasured sword." When 寶劍 refers to a weapon already established as a different type (e.g. 匕首/dagger), translate as "treasured blade" or "precious weapon" — the 劍 is being used generically for "edged weapon," not to reclassify the object as a sword. The model must track what weapon a character is actually holding and not let 寶劍 override the established weapon type.
12. 暗器 (ànqì) thrown projectiles: 錐 (zhuī) when used as a thrown hidden weapon should be translated as "dart" not "spike." "Spike" implies a stationary or hand-held implement; "dart" is the established wuxia English term for small thrown projectiles. E.g. 毒龍錐 = "Poison Dragon Darts." The context of being thrown in volleys (十多枚), caught mid-air, and classified as 暗器 confirms projectile usage.
13. Epithets in narration and third-person reference should be translated to English: "the Golden-Faced Buddha drew his sabre," "the Flying Fox had vanished." When shortened in narration (雪山飛狐 → 飛狐), keep the English: "the Flying Fox" — NOT "Fēihú." However, when an epithet is used as **direct address** — speaking TO someone by their epithet — render as italicized pinyin, following the same address-vs-description rule as honorifics (Principle 38): "*Jīnmiànfó*, your sabre technique is formidable"; "Wait, *Fēihú*!" In address, the epithet functions as a title and carries the weight of how jianghu figures actually hail each other. In narration, the English paints the picture.
14. Adjacent footnotes on closely related terms with overlapping content must be consolidated into one. E.g. 滿清[6]韃子[7] should be a single footnote covering both the Manchu Qing dynasty and the derogatory term, not two footnotes the reader must cross-reference. However, adjacent footnotes with genuinely distinct content should remain separate — e.g. Shānxī/Shǎnxī (tonal disambiguation) and Húguǎng (historical geography) explain different things and are correctly kept apart.
15. Four-character compound names spoken as a unit (e.g. 胡苗范田 Hú-Miáo-Fàn-Tián) must be rendered as a fixed epithet, not a plain list. The translation should convey that the four surnames form a single legendary byname — e.g. "known by the byname 'Hú-Miáo-Fàn-Tián'" — and a footnote should explain the significance (these four bodyguards' descendants and feuds drive the entire plot of 雪山飛狐). Simply listing the surnames twice ("surnamed Hú, Miáo, Fàn, and Tián; called 'Hú, Miáo, Fàn, Tián'") misses the point that this is a set phrase.
16. 棒 (bàng) is context-dependent — it means "cudgel" in a weapons context but "stick/rod/poker" in a domestic context. 撥火棒 (bōhuǒ bàng) = "fire poker" or simply "poker," NOT "fire-poking cudgel." The model must read the scene: a young woman delicately stirring embers in a brazier is holding a poker, not a weapon. Wuxia-brain must not override common sense for household objects.
17. When a name, title, or epithet echoes or derives from another established name in the text, the translation must preserve the wordplay/connection. The reader should be able to see the link without knowing Chinese. E.g. 飛天狐狸 ("Sky-Flying Fox") must contain "Flying Fox" so the reader connects the ancestor's epithet to the book's title 雪山飛狐 ("Snowy Mountain Flying Fox") and the descendant's shortened epithet 飛狐. Translating it as "the Soaring Fox" severs that thread. This applies generally: inherited epithets, punning names, title callbacks, and deliberate echoes across generations or factions must be preserved in translation.
18. ALL pinyin must carry tone marks — no exceptions for titles, epithets, or historical figures. 闯王 = Chuǎng-Wáng, not "Chuang-Wang." Unaccented pinyin is Wade-Giles or lazy romanization; this project uses standard Hànyǔ Pīnyīn with full diacritics throughout. The reviewer must flag any pinyin missing tone marks.
19. Verse translation: do NOT force English end-rhymes. Even when the Chinese source is rhyming poetry, the English should be dignified free verse that preserves imagery, parallelism, and meaning. Forced rhymes ("no hold," "dire deed," "savage things") distort meaning and sound like doggerel. Prioritize: (a) accurate imagery, (b) parallel structure matching the Chinese couplet form, (c) natural English register appropriate to the poem's tone. If a natural rhyme falls into place without distortion, keep it — but never contort syntax or pad meaning to hit a rhyme.
20. Do not footnote well-known Chinese cities (Běijīng, Luòyáng, Nánjīng, Xī'ān, etc.) unless the footnote adds non-obvious historical context specific to the narrative. More broadly, footnotes must NEVER contain vacuous literary commentary about what the text "illustrates," "grounds," "conveys," or "signifies narratively." A footnote exists to explain something the reader cannot infer from the text alone — historical facts, cultural context, linguistic nuance. "Its mention here grounds the alliance in a real setting" is not a footnote, it's CliffsNotes. Footnotes are scholarly annotations, not reading comprehension aids. Strip all meta-commentary.
21. Idioms and curses used as dialogue must preserve the speaker's tone and intent, not just the literal meaning. 甘拜下風 ("willingly bow before the stronger wind") in a defiant taunt is sarcastic concession, not genuine surrender — translate to preserve the bravado: "we concede you the upper hand" not "we acknowledge our defeat." Similarly, 有種 in tough-talk = "if you have the guts" not the genteel "if you have any courage." Chinese curses that are literal in Chinese but dead as calques in English must be translated by intent: 短命的 (duǎnmìng de, literally "short-lived") is a curse wishing death on someone — translate as "you accursed wretch!" or "you damnable villain!", NOT "you short-lived villain" (no English speaker curses someone by predicting their lifespan). Similarly: 死 (sǐ) as a prefix/curse intensifier, 該死的 (gāisǐ de, "deserving of death") = "damned/accursed", 挨千刀的 (ái qiāndāo de, "deserving a thousand cuts") = a vicious curse best rendered by tone, not literal translation. Chinese expletive intensifiers must be translated as English expletives, not literally: 他媽的 (tā mā de, "his mother's"), 他奶奶的 (tā nǎinai de, "his grandmother's"), 你奶奶的 (nǐ nǎinai de) are all equivalent to "goddamn" / "fucking" — they are NOT references to actual family members. 操他奶奶的熊 = "Fuck that gutless wretch!" NOT "Fuck his grandmother's bear!" — this is a double calque failure (literal intensifier + literal 熊). The 熊 here is the same insult as 狗熊 (Principle 31) meaning coward/good-for-nothing, not an actual bear. The model must read the emotional register of the scene, not just the dictionary meaning of the idiom.
22. Tense consistency within retrospective narration. When a character is recounting past events in dialogue, the English tense must stay in past throughout. Chinese lacks explicit tense markers, so the model sometimes drifts into present tense mid-anecdote (e.g. "cries so loudly, his face is all covered in hair" when recounting a birth from years ago). A related subtype: plans and predictions within retrospective narration need conditional past ("would rebel," "would be plunged into chaos") not simple future ("will rebel," "will be plunged") — the speaker is recounting what a past strategist expected to happen, not making a present prediction. The reviewer must flag both types of tense drift. Note: this is distinct from the deliberate "historical present" — if the narrator switches to present for dramatic effect, it should be consistent, not accidental drift.
23. Meaningful character names must be footnoted when the text explains their origin. When a character explicitly says "I kill with a single sabre stroke, therefore my name is Hú Yīdāo," the reader needs a footnote: "一刀 (yīdāo) — literally 'one sabre,' meaning his skill is so great that a single stroke suffices." This is especially important for names that ARE the wordplay (the character is explaining a pun on his own name). Applies broadly: any passage where a character's name meaning is revealed or played upon requires an annotation connecting name to meaning.
24. When the text references a specific character count ("seven characters," "three words," "twenty-two large characters"), the footnote must explain the Chinese original with a character-by-character or scholarly breakdown so the English reader understands why the count matters. E.g. 打遍天下無敵手 is seven Chinese characters — the footnote should give the full pinyin, literal character-by-character meaning ("fought-across-all under heaven-without-rival-hand"), and explain the boast. Without this, "seven characters" is meaningless when the English reads "Unrivaled Under Heaven" (three words). This applies to all passages where character count, wordplay on character composition (拆字), or the visual/numerical properties of Chinese text are narratively significant.
25. Inline square-bracket glosses like `sabre[dāo]` and `sword[jiàn]` are NEVER acceptable. If a term warrants a Chinese gloss, it must be a proper numbered footnote with ideogram, pinyin, and explanation — rendered as a popup in the EPUB. Inline brackets break prose flow and look like draft translator's notes, not a published book. The reviewer must flag and convert any inline glosses to proper footnotes.
26. 十八般武藝 (shíbā bān wǔyì, "all eighteen martial arts") should always be footnoted when it appears. The footnote should explain that this is a classical idiom meaning mastery of all weapon disciplines, referencing the canonical eighteen weapons classification (十八般兵器) which varied by dynasty (Song-Yuan vs. Ming lists). This is a high-value cultural footnote that connects the reader to a deep tradition — not trivial.
27. Consistent word choice for the same object within a passage. 鴿 (gē) is one bird — don't switch between "pigeon" and "dove" in the same scene. Pick the register-appropriate term and hold it. For wuxia: 白鴿 = "white dove" (poetic) not "white pigeon" (mundane). This applies broadly: any animal, object, or concept must use one English term consistently once established, unless the text deliberately uses different Chinese words.
28. Classical literary allusions and wordplay in dialogue MUST be footnoted. When Miáo Ruòlán says "the ancients used the History of the Hàn to accompany their wine; this younger sister possesses a Hàn qín," two things need annotation: (a) 以漢書下酒 — the famous anecdote about reading the *Hàn Shū* (Book of Han) as the ideal accompaniment to wine, a symbol of supreme literary refinement; (b) the parallel wordplay on 漢 — the ancients had a Hàn *shū* (book), she offers a Hàn *qín* (zither). This is sophisticated literary banter that defines the character's cultivation. Without footnotes, the English reader gets none of it. The model should actively detect classical allusions in refined dialogue and flag them for annotation.
29. Narrative framing and commentary must be separated from verse/quoted text. When a block contains both a character's speech attribution ("Hú Féi then chanted in response:"), quoted verse, AND narrator's gloss ("These final four lines were a benediction..."), the verse content should stand alone. The attribution and narrator's commentary are narrative, not verse, and should not be formatted as part of the poem. The translator should split these into distinct content segments — or at minimum the EPUB builder should detect and separate the framing narration from the quoted verse.
30. Mythological/folk religion figures used as metaphors require footnotes with genuine cultural depth, not vague summaries. 兇煞太歲 (xiōng shā tàisuì) — the footnote must explain: (a) 太歲 is the God of the Year (personification of Jupiter's orbital cycle), one of the most feared deities in Chinese folk religion; (b) the famous idiom 太歲頭上動土 ("disturbing the earth above Tàisuì's head") = courting disaster by provoking someone far more powerful; (c) 兇煞 intensifies this to a murderous, wrathful Tàisuì. A footnote that merely says "associated with the year's fortune" fails to convey why this metaphor is so vivid and terrifying. Folk religion, Buddhist, and Daoist figures used metaphorically in wuxia always warrant scholarly footnotes.
31. Jianghu slang and underworld idioms need footnotes and register-appropriate translation: (a) 黑道 (hēidào) = the outlaw/criminal side of the jianghu ("dark road"), as opposed to 白道 (báidào, the lawful martial world). "Black path" is acceptable but must be footnoted to explain the 黑道/白道 dichotomy. (b) 狗熊 (gǒuxióng) = literally "dog-bear" (Asiatic black bear), colloquially a contemptuous insult meaning "gutless wretch" or "good-for-nothing coward." "Cowardly bear" is a half-translation that sounds odd in English — translate the insult idiomatically and footnote the Chinese. (c) 開山立櫃 (kāishān lìguì) = "open a mountain and set up a stronghold" — jianghu idiom for establishing a bandit lair or outlaw operation. Should be footnoted.
32. **GENERAL REGISTER RULE: No modern English for jianghu concepts.** When translating jianghu society — its organizations, activities, roles, and targets — choose English that belongs to the pre-modern, chivalric, or archaic register. Modern crime slang, corporate language, and contemporary colloquialisms break the wuxia world. This principle consolidates several specific cases:
   - **Organizations**: 幫 (bāng) → "Clan" not "Gang." 丐幫 = "Beggars' Clan." Reserve "gang" for actual street criminals without martial lineage. (Previously principle 6 — now subsumed here.)
   - **Targets**: 點子 (diǎnzi) → "quarry" not "mark." "Mark" is modern Western con-artist slang; "quarry" has the right connotation of a hunted target. (Previously principle 2i — now subsumed here.)
   - **Activities**: 大案 → "great ventures/exploits" not "heists." Avoid: "gig," "job," "score," "racket," "hustle" for jianghu criminal activity.
   - **Formal/business English**: "Messrs." (as in "Messrs. Táo and Hú"), "aforementioned," "hereby," "pursuant to" — these belong in legal documents and merchant correspondence, not jianghu dialogue. A martial man says "those two, Táo and Hú" or simply names them.
   - **Modern casual idioms**: "a cut above the rest," "top-notch," "spot-on," "on the same page," "level up" — these are contemporary colloquialisms that break period register. Prefer: "in a class of his own," "without equal," "beyond compare."
   - **General test**: if the English word would sound natural in a modern crime thriller, a corporate memo, or a solicitor's letter, it's wrong for wuxia. If it would sound natural in a historical adventure novel or a chivalric romance, it fits. Mildly archaic is always preferable to accidentally modern.
33. Weapon characters used idiomatically as verbs/adverbs must not be translated as literal weapons. 戟指 (jǐ zhǐ) is a fixed idiom meaning "to point angrily/accusingly" — the 戟 describes the aggressive, stabbing quality of the gesture, not an actual halberd. Translate as "jabbed an accusing finger" or "thrust his finger," NOT "pointed with a halberd-like finger." A footnote explaining what a 戟 weapon is completely misses the point. The model must recognize when weapon characters function idiomatically (戟指, 劍眉 "sword-brows," 刀削般 "as if carved by a sabre") and translate the idiom, not the weapon.
34. When the narrator uses deliberately anachronistic or colloquial references (Jin Yong's characteristic wit), preserve the cultural term and footnote it rather than over-translating into clumsy English equivalents. 說相聲的下手 = "the feed in a xiàngsheng act" with a footnote explaining xiàngsheng (traditional Chinese comic crosstalk, a two-person performance art). NOT "the straight man in a crosstalk comedy" — "straight man" and "crosstalk comedy" are both half-translated and the combination is neither Chinese nor natural English. Keep the Chinese term (xiàngsheng), give the reader a footnote, and let the humor land.
35. Ambiguous pronoun reference and dangling modifiers must be caught by the reviewer. "Following Tián *Gūniáng* into the room, she said" — who is "she"? The participial clause implies a different person followed Tián Gūniang, but the Chinese makes clear it IS Tián Gūniang who entered and spoke. The model must ensure English sentence structure makes the subject unambiguous, especially in scenes told from a third-party narrator's perspective where multiple characters are present.
36. Martial technique sequences must preserve combat logic. When translating positional verbs (豎/舉/提/落/沉), choose the English that matches the physical direction of the action. E.g. 豎劍相架 when blocking a low groin strike = "drop his sword to parry" or "commit his sword to block below" — NOT "raise his sword to parry," which reverses the direction and breaks the tactical logic of why the upper body (上盤) becomes exposed.
37. Chinese paratactic comma-chains must be broken into proper English sentence structure. Chinese naturally strings clauses with commas (verb, verb, adjective, adjective) — translating this as one run-on English sentence produces awkward participial pile-ups. E.g. 手裏拿了弓箭，鐵青著臉，神色極是怕人 should NOT become "take up a bow and arrows in his hand, his face ashen and his expression utterly fearsome" (dangling modifiers). Break into separate sentences: "He held bow and arrows in hand. His face was livid, his expression fearsome." Similarly, common four-character idioms used in narration must be rendered as natural English, not word-for-word calques: 翻臉無情 = "turn hostile without mercy" or "turn on me in an instant" — NOT "with a single turn of his face show no mercy." 性命難保 = "my life would be forfeit" — NOT "my life would be hard to preserve." The model must recognize paratactic chains and restructure them into idiomatic English prose with clear subjects and proper sentence boundaries.

38. ALL martial/social honorifics and forms of address are rendered as italicized pinyin — no English substitutions, no exceptions. This includes but is not limited to: 師兄/師姐 (*Shīxiōng*/*Shījiě*), 師父 (*Shīfù*), 前輩 (*Qiánbèi*), 晚輩 (*Wǎnbèi*), 大哥/大姐 (*Dàgē*/*Dàjiě*), 姑娘 (*Gūniáng*), 夫人 (*Fūrén*), 大人 (*Dàrén*), 老兄 (*Lǎoxiōng*), 公公 (*Gōnggōng*), 掌門 (*Zhǎngmén*), 幫主 (*Bāngzhǔ*), 真人 (*Zhēnrén*), 閣下 (*Géxià*), 老爺 (*Lǎoyé*), 莊主 (*Zhuāngzhǔ*), 寨主 (*Zhàizhǔ*), 方丈 (*Fāngzhàng*), 鏢頭 (*Biāotóu*), 總管 (*Zǒngguǎn*). Each must be footnoted on first occurrence with: (a) ideogram, (b) pinyin, (c) literal meaning, (d) the social/martial relationship it encodes. E.g. "師兄 (shīxiōng) — literally 'elder martial-brother'; a fellow disciple who entered training under the same master before the speaker. Implies shared lineage and a fixed seniority that does not change regardless of actual skill." When an honorific is combined with a descriptive role or epithet (not a personal name), the role translates to English while the honorific remains pinyin: Physician *Qiánbèi*, Beggar *Gōnggōng*, Swordsman *Dàgē*. The English word identifies who; the pinyin encodes the social relationship. **Address vs. description**: For social/family honorifics (姑娘, 大哥, 夫人, 老兄, 公公, 老爺), pinyin applies when used as direct address or title (Miáo *Gūniáng*, Hú-*Dàgē*); English is fine in third-person narration ("the young lady turned," "his elder brother nodded"). For martial-lineage terms (師兄, 師姐, 師父, 前輩, 晚輩, 掌門, 幫主, 真人), pinyin is used ALWAYS — even in narration ("his *Shīxiōng* stepped forward," "the *Zhǎngmén* rose from his seat") — because these encode specific relationships that have no clean English equivalent. "Senior fellow disciple" is not natural English; *Shīxiōng* is a term the reader learns once and recognizes thereafter. The reader learns the address system as a *system*, not through ad-hoc English approximations. This supersedes any earlier guidance that allowed English translations for specific honorifics (e.g. 老兄 → "brother", 姑娘 → "Miss", 大哥 → "Elder Brother").

39. Major wuxia sects and martial institutions (少林 Shàolín, 武當 Wǔdāng, 崑崙 Kūnlún, 峨嵋 Éméi, 華山 Huàshān, 點蒼 Diǎncāng, 丐幫 Beggars' Clan, etc.) must receive detailed footnotes on first occurrence. Each footnote should include: (a) ideogram and pinyin, (b) literal meaning of the name (e.g. 武當 = "martial and deserving," named after Wǔdāng Mountain in Húběi), (c) religious/philosophical affiliation — Taoist, Buddhist, or secular — and what this means for their martial philosophy (e.g. Shàolín = Chán Buddhist, external martial arts; Wǔdāng = Taoist, internal arts emphasizing softness overcoming hardness), (d) signature techniques or martial characteristics they are known for across the wuxia canon (e.g. Shàolín's 72 Consummate Arts, Wǔdāng's tàijí swordsmanship). Do NOT reference specific plot points from the current work — treat these as common knowledge within the wuxia tradition. The footnote should read as a brief encyclopaedic entry that any wuxia reader would recognize, grounded in the cross-novel canon, not in this particular story's events. Lesser or fictional sects invented by the author need shorter footnotes or none (per principle 2f — fictional factions are not cultural terms).

40. Chinese place and settlement terms encode a precise administrative and social hierarchy. The model must translate each correctly — flattening them all to "village" or "town" is a category error. Reference table:

   **Administrative divisions (imperial China):**
   - 省 (shěng) — province
   - 府 (fǔ) — prefecture (a major administrative unit below province, governing a city and surrounding counties)
   - 州 (zhōu) — prefecture/department (varies by dynasty; sometimes equivalent to 府, sometimes smaller)
   - 縣 (xiàn) — county (the basic unit of local government, headed by a magistrate 縣令/知縣)
   - 道 (dào) — circuit/region (a supervisory tier, usage varies by dynasty)

   **Settlements:**
   - 城 (chéng) — city / walled city (implies fortifications)
   - 鎮 (zhèn) — market town (larger than a village, has commerce, sometimes a garrison)
   - 村 (cūn) — village (a communal rural settlement)
   - 集 (jí) — market village / periodic market town

   **Private/martial compounds:**
   - 莊 (zhuāng) — manor / estate (a private fortified compound, often the seat of a wealthy martial family; 莊主 *Zhuāngzhǔ* = master of the manor). NEVER translate as "village"
   - 山莊 (shānzhuāng) — mountain manor/lodge (NOT "mountain village")
   - 寨 (zhài) — stockade / stronghold / fortified camp (often a bandit lair or rebel base)
   - 堡 (bǎo/pù) — fort / fortress / fortified settlement
   - 塢 (wù) — walled compound / fortified hamlet

   **Polities and foreign lands:**
   - 朝 (cháo) — dynasty / court (e.g. 明朝 Míng cháo = the Míng dynasty; also used for "the court" as seat of government)
   - 國 (guó) — kingdom / state / country (e.g. 大理國 Dàlǐ Guó = the Dàlǐ Kingdom)
   - 帝國 (dìguó) — empire
   - 汗國 (hánguó) — khanate (Mongol/Turkic polities)
   - 藩 (fān) — vassal state / feudatory
   - 番/蕃 (fān) — foreign / barbarian (classical term for non-Chinese peoples; context-dependent, can be neutral or pejorative)
   - 夷 (yí) — barbarian (specifically eastern barbarians in ancient usage; later generalized as a pejorative for all non-Chinese). Translate the intent: if a character uses 夷 contemptuously, preserve the contempt
   - 胡 (hú) — northern/western barbarian (originally the Xiōngnú and steppe peoples; later generalized). 胡人 = "the Hú" or "northern barbarians" depending on context
   - 韃子 (dázǐ) — Tartar (derogatory term for Mongols, later applied to Manchus). Always footnote — the reader needs to know this is a slur, not a neutral ethnonym
   - 蒙古 (Měnggǔ) — Mongolia / Mongol
   - 西域 (Xīyù) — the Western Regions (Central Asia, the Silk Road territories west of the Jade Gate)
   - 中原 (Zhōngyuán) — the Central Plains (the heartland of Chinese civilization, roughly the Yellow River basin). Footnote on first use — this is a loaded cultural concept, not just geography
   - 關外 (guānwài) — "beyond the pass" (north of the Great Wall / Shānhǎi Pass; Manchuria)
   - 關內 (guānnèi) — "within the pass" (China proper, south of the Great Wall)
   - 塞外 (sàiwài) — "beyond the frontier" (the steppe lands north of China's border fortifications)
   - 江南 (Jiāngnán) — "south of the river" (the prosperous Yangtze delta region; implies wealth, culture, refinement)

   **Religious/institutional:**
   - 寺 (sì) — Buddhist temple/monastery (e.g. 少林寺 Shàolín Sì)
   - 觀 (guàn) — Taoist monastery/temple
   - 庵 (ān) — nunnery / small Buddhist hermitage
   - 宮 (gōng) — palace / Taoist temple (context-dependent)

   Each carries social and narrative meaning — a 莊主 commands a private estate, a 寨主 commands a bandit stronghold, a 方丈 presides over a Buddhist monastery. The model must not flatten these distinctions. Footnote on first occurrence when the English term alone would not convey the Chinese specificity (e.g. the difference between 莊 and 寨 matters for understanding a character's social position).

41. **REINFORCEMENT — gendered collective nouns.** Despite existing hard rules in the prompt, the model continues to translate 二人/兩人 as "the two men" even when one is a woman (e.g. D60 ch10: 胡苗二人 rendered as "the two men, Hú and Miáo" — Miáo Ruòlán is female). This may already be fixed by the existing hard rule in `translation_prompts.py` (lines 108/303) — the D60 output predates that rule. Retranslation needed to confirm. Regardless, reinforce: 人-based group words (二人, 兩人, 三人, 眾人, 幾人) are ALWAYS gender-neutral: "the two of them," "both," "the two," "all of them." NEVER "men" unless the Chinese explicitly uses 男 or the group is confirmed all-male. The reviewer must flag every instance.

42. Chinese surnames must NEVER be translated to English, even when the character is also a common noun. 熊 (Xióng) is a surname — it is NOT "Bear." 馬 (Mǎ) is a surname, not "Horse." 龍 (Lóng) is a surname, not "Dragon." The model must recognize that in a name context (followed by a given name or title), these characters function as proper nouns. 熊元獻 = Xióng Yuánxiàn, not "Bear Yuánxiàn." This error is especially likely when the character also has a common meaning that the model has seen in other contexts (e.g. 熊 as the insult in 狗熊). The reviewer must flag any translated surname.

43. Do NOT import European supernatural creatures into Chinese settings. Chinese has its own supernatural vocabulary — 鬼 (guǐ, ghosts/departed spirits), 妖 (yāo, demons/shapeshifters), 魔 (mó, devils/fiends), 精 (jīng, animal spirits/sprites), 仙 (xiān, immortals) — and none of them are "goblins," "elves," "trolls," "fairies," "ogres," or "sprites" in the European sense. 裝神弄鬼 (zhuāng shén nòng guǐ, "play at gods and ghosts") is an idiom meaning "to put on a mysterious charade / play tricks" — translate the meaning, not the mythology: "playing mysterious tricks" or "putting on a ghostly charade," NOT "playing at ghosts and goblins." More broadly: when translating Chinese supernatural/folk-religion terms, use the Chinese framework (ghosts, demons, immortals, spirits) or plain English equivalents. Never substitute Western folklore creatures that carry their own cultural baggage.

44. Distinctively Chinese idioms with vivid imagery should be preserved AND footnoted, not flattened into generic English. When a Chinese idiom carries a striking image that would enrich the reader's experience, translate it semi-literally to preserve the colour, then add a footnote explaining the idiom's meaning and usage. Examples:
   - 陰溝翻船 (yīngōu fānchuán, "capsized the boat in a sewer ditch") — meaning "brought low by something beneath one's dignity." Keep the image in the prose; footnote explains the idiom's connotation of humiliating defeat by a trivial opponent.
   - 戴高帽子 (dài gāo màozi, "put a tall hat on someone") — meaning "to flatter / butter up." The image is distinctively Chinese and worth preserving with a footnote.
   - 斧鉞 (fǔyuè, "axe and battle-axe") — classical metonymy for execution / imperial punishment. Translate the meaning ("threatened with execution") but footnote the metonymy so the reader learns the Chinese figure of speech.
   - 如蛆附骨 (rú qū fù gǔ, "like maggots clinging to bone") — vivid combat simile, keep it and footnote.
   The test: if the Chinese idiom has a distinctive image that would be lost by translating purely to meaning ("he flattered him"), preserve the image and footnote. If the idiom is dead metaphor with no interesting imagery (e.g. 一石二鳥 "one stone two birds" = kill two birds with one stone), just translate idiomatically — no footnote needed. The goal is to let the reader experience Chinese figurative language, not to annotate every four-character phrase.

   **Special case — canonical strategic/philosophical references**: When an idiom originates from a known classical source — the Thirty-Six Stratagems (三十六計), the Art of War (孫子兵法), the Dao De Jing (道德經), Zhuangzi (莊子), etc. — the footnote must identify the source. E.g. 偷梁換柱 (tōu liáng huàn zhù, "steal the beam, swap the pillar") is Stratagem #25 of the Thirty-Six Stratagems, meaning to secretly substitute one thing for another. 借刀殺人 (jiè dāo shā rén, "borrow a sword to kill") is Stratagem #3 — using a third party to eliminate an enemy. 圍魏救趙 (wéi Wèi jiù Zhào, "besiege Wèi to rescue Zhào") is Stratagem #2, from an actual historical campaign. These are not generic metaphors — they are references to a canonical body of strategic thought that educated Chinese readers recognise instantly. The footnote should give: (a) the idiom with pinyin, (b) literal meaning, (c) the source text and stratagem number where applicable, (d) the strategic principle it describes. This also applies to Buddhist/Taoist philosophical terms used metaphorically, Confucian maxims (論語, 孟子), and historical allusions embedded as four-character idioms (成語).

45. Chinese body-organ metaphors encode a different system from English and must be translated by meaning, with a footnote explaining the Chinese body-metaphor on first occurrence. In Chinese, different organs are the seat of different qualities — this is a fundamental cultural framework, not a one-off idiom. The reader should learn the system. Key mappings:
   - 膽 (dǎn, gall bladder) = courage. 膽大 = bold, 膽小 = cowardly, 嚇破了膽 = terrified beyond measure. "Their gall bladders quivered" is a dead calque — translate as "their courage failed them" and footnote explaining 膽 as the organ of courage in Chinese.
   - 心 (xīn, heart) = mind/thought, not just emotion. 心想 = "thought to himself" not "felt in his heart." 用心 = "with care/diligence" not "with heart."
   - 腸 (cháng, intestines) = emotional disposition / deep feeling. 斷腸 = heartbroken (literally "severed intestines"). 愁腸百結 = "a hundred knots in one's grieving intestines" = consumed by sorrow.
   - 肝 (gān, liver) = sincerity / loyalty. 肝膽相照 = "liver and gall bladder shining upon each other" = utter mutual trust between comrades. This is a high-value idiom in wuxia — always footnote.
   - 肺 (fèi, lungs) = the depths of one's feelings. 肺腑之言 = words from the depths of one's being.
   The general rule: translate the meaning into natural English, then footnote the Chinese organ metaphor so the reader learns that courage lives in the gall bladder, loyalty in the liver, and grief in the intestines. Over time, the reader builds a map of the Chinese body-as-metaphor system.

46. Martial technique names (招式 zhāoshì) are poetic images describing the motion or intent of the move. The English must preserve the image without sounding absurd. The model must understand the physical action being described and choose verbs that convey motion, not bodily functions. E.g. 黃龍轉身吐鬚勢 — 吐鬚 describes a dragon lashing out its whiskers (long, whip-like tendrils used as weapons). "Yellow Dragon Turns and Lashes Its Whiskers" — NOT "Spits Its Whiskers" (dragons do not vomit facial hair). Common pitfalls:
   - 吐 (tǔ) in technique names usually means "project/extend/shoot forth," not "spit/vomit"
   - 探 (tàn) = "probe/reach," not "explore"
   - 撲 (pū) = "pounce/strike," not "throw oneself"
   - 回 (huí) = "return/reverse," not "go back"
   The technique name should read like a martial arts manual caption — dignified, precise, evocative. If the English sounds comical or disgusting, the verb choice is wrong. When in doubt, think about what the body is actually doing and choose the English that matches the physical motion. Technique names should also be consistent: the same 招式 must be translated the same way every time it appears.

47. Chinese units of measurement are rendered as italicized pinyin, NEVER converted to Western units or translated to colonial-era English loanwords (e.g. "catty"). Footnote on first occurrence with the approximate modern equivalent. Reference table:

   **Weight:**
   - 斤 (*jīn*) — approx. 500g / 1.1 lbs (varied by dynasty)
   - 兩 (*liǎng*) — approx. 50g / 1.76 oz (1/10 of a *jīn* in the traditional system; also a unit of silver currency)

   **Distance:**
   - 里 (*lǐ*) — approx. 500m / 0.31 miles (the "Chinese mile")
   - 丈 (*zhàng*) — approx. 3.3m / 10.8 ft (used for heights, weapon lengths, room dimensions)
   - 尺 (*chǐ*) — approx. 33cm / 13 in (1/10 of a *zhàng*)
   - 寸 (*cùn*) — approx. 3.3cm / 1.3 in (1/10 of a *chǐ*; also used for acupoint measurement)

   **Area / land:**
   - 畝 (*mǔ*) — approx. 667 sq m / 0.16 acres

   **Time:**
   - 更 (*gēng*) — a night watch, approx. 2 hours (the night divided into five *gēng*)
   - 時辰 (*shíchén*) — a double-hour (the day divided into twelve *shíchén*)

   Do NOT write "sixteen pounds" for 十六斤, "thirty miles" for 六十里, or "ten feet" for 三丈. The Chinese measurement system is part of the world — converting it erases the setting. The reader learns these quickly, especially with footnotes.

48. Onomatopoeia and sound effects rendered as pinyin must ALL be italicized consistently. When multiple sound effects appear in sequence (e.g. three consecutive onomatopoeic terms), every one must be italicized — not just the first and last. The model sometimes drops italics on middle terms in a series. E.g. *pēng pēng pēng* — not *pēng* pēng *pēng*. This applies to all pinyin sound effects whether single, paired, or in longer chains.

49. Material culture objects that are distinctively Chinese must be footnoted when they would be unfamiliar to a Western reader. The test: would the reader know what this object IS and how it works? A 客棧 (inn) needs no footnote — inns are universal. But a 火摺子 (huǒzhézǐ, fire-striker/tinder cord) does — it's a specific Chinese portable fire-lighting device (a slow-match in a bamboo tube) that the reader has never seen. Similarly: 炕 (kàng) — a heated brick sleeping platform, not a "bed"; 算盤 (suànpán) — an abacus, may need brief context if used metaphorically; 夜壺 (yèhú) — a chamber pot, self-evident but the term itself might appear; 長衫 (chángshān) — a long gown, footnote if the social signaling of the garment matters. The model should translate these objects into clear English (not pinyin) but footnote the first occurrence with: (a) ideogram and pinyin, (b) what the object physically is, (c) how it was used in daily life or why it matters in context. Do NOT footnote universal objects (tables, chairs, bowls, horses) or objects already explained by context. Weapons are handled separately by principles 10-12 and have their own precision rules. The goal is to make the material world vivid and specific, not to annotate every noun.

### For validation prompts — actively scan for:
10. **Character count references**: Any time the translation contains a number + "words" / "characters" / "sentences" referring to something just spoken or written (e.g. "these twelve words"), the reviewer must verify a Principle 24 footnote exists giving the Chinese original with character-by-character breakdown. This is especially important when the quoted speech and the count reference are in different blocks — the translator works block-by-block and cannot verify the count matches the English. The footnote resolves the mismatch for the reader.

### For validation prompts — stop flagging:
1. Wuxia epithets as missing cultural footnotes
2. Register-preserving calques (芳名 → "fragrant name")
3. Moderate variation in forms of address
4. Mildly archaic diction in wuxia register
5. Past perfect in dialogue recounting past events
6. Fictional in-story elements as cultural terms
7. Valid translator honorific choices (per Principle 38, rendered as pinyin — e.g. 老兄 → *Lǎoxiōng*)
8. Unusual but comprehensible collocations
9. Footnotes that would spoil plot reveals
