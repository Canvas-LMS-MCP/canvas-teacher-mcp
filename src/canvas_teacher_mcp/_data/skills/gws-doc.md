---
name: gws-doc
description: Read and format Google Docs using gws CLI. Use when reading a Google Doc's content, or creating/reformatting a Google Doc with proper heading styles, bold text, or structured content.
type: skill
---

# Google Doc Skill (gws-doc)

Covers two operations: **reading** a Google Doc's content, and **formatting/updating** it.

---

## Reading a Google Doc

### Plain text (default — use for text answers, essays, written work)
```bash
gws drive files export \
  --fileId {DOC_ID} \
  --mimeType text/plain
```

### HTML (use when content has tables, structured layout, or images matter)
```bash
gws drive files export \
  --fileId {DOC_ID} \
  --mimeType text/html
```

### When to use which
| Content type | Use |
|---|---|
| Written answers, paragraphs | `text/plain` |
| Tables, multi-column layout | `text/html` |
| Slides / presentations | `text/plain` first; `text/html` if layout matters |

### Getting the file ID
- From a Google Doc URL: `https://docs.google.com/document/d/{DOC_ID}/edit`
- From a submission link — extract the ID segment between `/d/` and `/edit`

---

## Formatting a Google Doc

Use the `gws docs documents batchUpdate` command to apply formatting to Google Docs.

## Command Syntax

```bash
gws docs documents batchUpdate \
  --params '{"documentId": "DOC_ID"}' \
  --json '{"requests": [...]}'
```

## Step 1 — Read Doc Structure

Always read the doc first to get paragraph indices:

```bash
gws docs documents get --params '{"documentId": "DOC_ID"}' | python3 -c "
import json, sys
doc = json.load(sys.stdin)
for elem in doc.get('body', {}).get('content', []):
    if 'paragraph' in elem:
        p = elem['paragraph']
        style = p.get('paragraphStyle', {}).get('namedStyleType', 'NORMAL_TEXT')
        text = ''.join(r.get('textRun', {}).get('content', '') for r in p.get('elements', []))
        print(f'[{elem.get(\"startIndex\",\"?\")}–{elem.get(\"endIndex\",\"?\")}] {style}: {repr(text[:60])}')
"
```

## Step 2 — Batch Requests

### Reset all body text to NORMAL_TEXT
```json
{
  "updateParagraphStyle": {
    "range": {"startIndex": START, "endIndex": END},
    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
    "fields": "namedStyleType"
  }
}
```

### Apply heading style
```json
{
  "updateParagraphStyle": {
    "range": {"startIndex": START, "endIndex": END},
    "paragraphStyle": {"namedStyleType": "HEADING_1"},
    "fields": "namedStyleType"
  }
}
```

### Bold a text run
```json
{
  "updateTextStyle": {
    "range": {"startIndex": START, "endIndex": END},
    "textStyle": {"bold": true},
    "fields": "bold"
  }
}
```

### Monospace (code) text
```json
{
  "updateTextStyle": {
    "range": {"startIndex": START, "endIndex": END},
    "textStyle": {"weightedFontFamily": {"fontFamily": "Courier New"}},
    "fields": "weightedFontFamily"
  }
}
```

### Paragraph shading (gray code-block background)
```json
{
  "updateParagraphStyle": {
    "range": {"startIndex": START, "endIndex": END},
    "paragraphStyle": {"shading": {"backgroundColor": {"color": {"rgbColor": {"red":0.945,"green":0.945,"blue":0.945}}}}},
    "fields": "shading"
  }
}
```

### Indentation (stepped indent — content/code sits UNDER its heading)
The house docs **indent** body + code paragraphs under their heading (not at the page margin). Do it with
paragraph `indentStart`, never with spaces.
```json
{
  "updateParagraphStyle": {
    "range": {"startIndex": START, "endIndex": END},
    "paragraphStyle": {"indentStart": {"magnitude": 18, "unit": "PT"}},
    "fields": "indentStart"
  }
}
```
- `indentStart` = left indent of the whole paragraph (pt). One step ≈ **18pt**, two ≈ 36pt. (`indentFirstLine` = first line only — rarely needed.)
- **Headings/labels at the margin (indentStart 0); body + code blocks indented under them.**

### A house "code block" = THREE things on one paragraph
NORMAL_TEXT  +  **gray shading** (above)  +  **same `indentStart` as the surrounding body**  +  run = **Courier New, 9pt**.
A code line at indentStart 0 (page margin) while the body around it is indented = the bug to avoid.

### Bullet list (real bullets, not a literal "•")
```json
{
  "createParagraphBullets": {
    "range": {"startIndex": START, "endIndex": END},
    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"
  }
}
```
- One level auto-sets **indentStart 36** (= body-indent 18 + one step) — don't set indent yourself.
- The range covers **all** paragraphs in it → keep the bullet lines contiguous, one request.
- Reset to NORMAL_TEXT first if the lines inherited a heading style.

### Match the heading LEVEL, not just "a heading"
A doc nests: e.g. `HEADING_3` sub-sections (`2.1`, `2.2`) with `HEADING_4` items under them (`Step 1`, `Step 2`).
When you add a section, **read a sibling's `namedStyleType` and use the SAME level** — a `HEADING_3` where the
peers are `HEADING_4` will look like a too-big top-level header in the wrong place.

### House style — this doc family (verified values, reuse)
| Element | Value |
|---|---|
| Heading text color | navy `#1F3864` = rgb `{0.122, 0.220, 0.392}` |
| Code-block shading | gray `{0.945, 0.945, 0.945}` |
| Indent step | body `18pt`, bullets `36pt`, headings `0` |
| **Body font** | **`Lato`, `12pt`** (the house body face — set it explicitly; never leave default Arial) |
| **Heading font + sizes** | All headings **`Arial`** (NOT Lato): **Heading 2 = 18pt · Heading 3 = 14pt · Heading 4 = 12pt** (Title/Subtitle keep their own). Section-badge title text = **`Arial 12` bold**. |
| Code font | `Consolas` **bold** (inline + boxes). (Older docs used Courier New 9pt — Consolas is current.) |
| **Table cell text** | **`contentAlignment: MIDDLE` + padding `0.1in`** — else box/badge text jams to the cell top. |
| **Space ABOVE headings** (clear section breaks) | `HEADING_2` **`spaceAbove ~28–30pt`** · `HEADING_3` **`~20–22pt`** · `spaceBelow ~6pt`. A heading with only the body-gap above it (≤14pt) reads as cramped — give it real air. **EXCEPTION — a sub-heading directly under its parent** (e.g. `HEADING_3` "Option 1" immediately after `HEADING_2` "Choose ONE"): use **`spaceAbove ~8pt`**, NOT 22 — a parent→first-child gap of 22 reads as a "Pacific Ocean". Tighten only when prev element is the parent heading; later siblings keep 22. |
| Line spacing (install/how-to guides) | `lineSpacing 150` (1.5) — spacious + scannable |

## Named Style Types

| Style | Use For |
|---|---|
| `TITLE` | Document title (one per doc) |
| `SUBTITLE` | Subtitle below title |
| `HEADING_1` | Major section headers |
| `HEADING_2` | Subsection headers |
| `HEADING_3` | Sub-subsection |
| `NORMAL_TEXT` | Body text (default) |

## Workflow

1. Get doc → parse `[startIndex–endIndex]` for each paragraph
2. Plan: title stays TITLE, steps → HEADING_1, body → NORMAL_TEXT
3. One batchUpdate: first reset all to NORMAL_TEXT, then apply headings
4. Optionally bold labels (e.g., "Windows:", "Mac:") and monospace commands

## Rules

- **Range end index is exclusive** — use the `endIndex` from the doc (includes the `\n`)
- **Order matters** — put NORMAL_TEXT reset before heading overrides in the same request
- **Never re-read after** every small change — batch all style changes into one request
- Use `gws docs documents get` again only if you need to find exact character positions for inline bold/code styling
- **Inserting into an EXISTING doc — match the neighbors, don't eyeball.** First read an adjacent paragraph's
  FULL style (`namedStyleType`, `indentStart`, `shading`, run `weightedFontFamily`/`fontSize`/`foregroundColor`)
  and replicate it on your inserted paragraphs. **Text inserted at the start of a paragraph INHERITS that
  paragraph's style** (e.g. inserting before a HEADING makes your text HEADING too) → reset to NORMAL_TEXT,
  then re-apply per-line.

## Beginner-guide structure (MANDATORY — flat headings are the #1 confusion)

A beginner must, at a glance, know **which steps are a choice vs. required**. Flat same-level headings fail —
beginners then do ALL options. Encode the logic in **visible hierarchy + explicit words**:

- **Hierarchy via indent, not just heading size.** Parent section = `HEADING_2` at the margin (`indentStart 0`).
  Its sub-items (the alternative options) = `HEADING_3` **indented one step in**; their steps = bullets indented
  **further still**. The indentation itself signals "these belong under, and are sub-choices of, the parent."
  Don't leave option sub-headings at the margin (flat) — that reads as "do them all."
- **Options must scream "pick ONE."** Label them literally **"Option 1 — …" / "Option 2 — …"** (not bare ①/②),
  nest them under a parent like **"Choose ONE way to install"**, and put a one-line overview: **"Do ONE of the
  options below, then Verify."** Without the word *Option* + nesting, beginners run both.
- **Required/closing sections get their OWN top-level heading** (`HEADING_2` at margin), labeled so it reads as
  mandatory — e.g. **"Verify — do this after either option (required)"**. Never tuck a must-do step under one
  option (it then looks optional). The closing must read "everyone does this," not "another choice."
- **ALL code = Consolas BOLD — in code boxes AND inline in prose.** A command sitting in a normal sentence
  (e.g. `which brew`, `brew install --cask temurin@21`) must be bold monospace so it never melts into the
  surrounding text. Don't rely on the source HTML having wrapped it — **after import, scan each prose paragraph
  for command/identifier substrings and force `weightedFontFamily: Consolas` + `bold: true` on those ranges**
  (find the literal substring → style that `[start,end]`). UI labels (menu names like *Apple menu*,
  *About This Mac*) are bold-normal, NOT code — don't monospace those.

## ★ GOLDEN spec — beginner install-guide (measured from the user's hand-tuned sample)

The user hand-formatted the "Choose ONE way to install" section of the Windows JDK doc
(`1n_LDkPsgW7u3ZQ_ynE2Eax3MlBq-9FRdwDWMjl2xGk0`) to exactly their taste. **Match these measured values —
do NOT eyeball from screenshots.** Re-measure that section if in doubt (it is the live template).

| Element | indentStart | firstLine | spaceAbove | spaceBelow | lineSpacing |
|---|---|---|---|---|---|
| `HEADING_2` (top option group) | 0 | 0 | **30** | **0** | 150 |
| `HEADING_3` **first** sub-heading, directly under its parent H2 | 18 | 18 | **0** | 6 | 150 |
| `HEADING_3` later sibling (Option 2, …) | 18 | 18 | **22** | 6 | 150 |
| numbered / list step | **36** | **18** | 4 | 8 | 150 |
| step **immediately after a box/table** | 36 | 18 | **10** | 0 | 150 |
| `●` sub-note under the steps ("Done with… go to Verify") | **54** | 36 | 4 | 8 | 150 |

- **Number→text gap = indentStart − firstLine = 18** everywhere (one clean space).
- **Parent H2 → first child H3 = touching** (H2 `spaceBelow 0` + H3 `spaceAbove 0`; the 1.5 line spacing is the
  only gap). 22pt there is the "Pacific Ocean" mistake. Later siblings get `spaceAbove 22`.
- **A ● sub-note sits one indent step deeper (54) than the numbered steps (36)** — it's a comment under them.
- **Callout box (table):** cell padding **9pt** all sides; box indented ~36 from the margin; **inside the box
  every paragraph is `spaceAbove 0 / spaceBelow 0`** (tight) with the title run at `fontSize 14`.
- After-box step uses `spaceAbove 10` (NOT 24 — 24 reads as detached here).

## Bullets vs numbers, and first-line indent (the two list bugs)

**Marker choice — default is the DISC, numbers are the exception.**
- Default list marker = **black disc ●** (`createParagraphBullets` → `BULLET_DISC_CIRCLE_SQUARE`).
- Use **numbers ONLY for a genuine ordered, multi-step procedure** (install step 1 → 2 → 3). `NUMBERED_DECIMAL_ALPHA_ROMAN`.
- A **lone single item, or a pointer line** ("Go to Verify below", "Done with Option 2 — go to Verify") must be a
  **disc**, never a dangling "1." — a one-item numbered list reads as "where are 2, 3?". Rule of thumb:
  **contiguous bullet group of size 1 → disc.**

**First-line indent — set it EXPLICITLY on every paragraph, or wraps misbehave.**
- **List item:** marker hangs one step left of the text → `indentFirstLine = indentStart − 18`.
  Bug to avoid: you deepen `indentStart` (e.g. 54 to nest under an option) but leave `indentFirstLine` at the
  list default (~12) → a **40pt+ gap** between the number and its text. Always move `indentFirstLine` with it.
- **Non-list paragraph:** `indentFirstLine = indentStart` (explicit). A paragraph that was once a bullet keeps a
  **phantom first-line offset** the API reports as `None` but the renderer still applies → the *wrapped* (2nd+)
  lines jut out further than the first. Writing `indentFirstLine = indentStart` explicitly kills it.

## No image placeholders
Never leave `[ Screenshot: … ]` placeholder lines in a delivered doc — the user does not fill them and they read
as an error. Either insert a real image or omit the line. (Same rule removed from gws-richdoc's building blocks.)
