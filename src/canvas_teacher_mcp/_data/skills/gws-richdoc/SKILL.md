---
name: gws-richdoc
description: Create a rich-format Google Doc (banner, color section boxes, navy step badges, tip/info/warning callouts, dark syntax-colored code blocks, bullets) DETERMINISTICALLY via the fixed generator build.py. Use when the user asks for a "gws-richdoc / rich-gdoc" doc or a polished, visually-structured Google Doc. ALWAYS run build.py — never hand-author the HTML (that is what made every session look different).
type: skill
tools: [build_rich_doc]
---

# gws-richdoc — Rich Google Doc, ONE fixed look

**Why this exists:** hand-writing the HTML each session made every doc look different (rainbow vs
navy badges, boxes present/absent, no spacing). The fix is a **single deterministic generator**:
`build.py`. You assemble a list of block specs and call build — the blocks, colors, fonts, spacing,
and code coloring are FIXED in code, so every session produces the **same look**.

> **RULE: never hand-author rich-doc HTML.** Build the content as block specs and run `build.py`.
> The only thing that changes between docs is the *text*, never the formatting.

## Files
```
gws-richdoc/
├── SKILL.md       (this — the rules + how to call build.py)
└── build.py       (the fixed generator: block builders + import + refine + code coloring)
```
> **build.py EXISTS and is verified (built 2026-06-22).** Architecture = HYBRID: **AI = WHAT**
> (raw input → block specs + content + post-import QA), **build.py = HOW** (final look; AI never
> restyles — that is what made every doc look different). Two entry points:
> - `make(blocks, name, folder_id, code_mode)` → NEW doc (create gdoc → HTML-import → refine).
>   Verified to match this master template; inline `font-size` survives import.
> - `colorize_code_cell(doc_id, lang, mode, which)` → color code in an EXISTING doc **in place**
>   (no re-import → images/edits preserved). Use for docs with images.
>
> Code coloring: shell (regex) + Python (stdlib `tokenize`, no pygments; robust to broken code).
> Python docstring modes: `mode="correct"` (docstring = ONE string color, real-editor accurate)
> vs `mode="pretty"` (docstring inner re-tokenized & colored — reads like live code).
> New `.py` creation is blocked by the code-gate hook → open via `~/.claude/.code-gate`.
> gws call shape: `--params` = URL/query (`documentId`), `--json` = body (`requests`).
- **Visual master reference (Drive):** `1UzJhVARxgVB_49KcJg5BxyqIxeKPTiJnf1iRDBEVt6I` ("스킬 템플릿").
  Open it to SEE the canonical look. `build.py` reproduces it.

## The block catalog (the ONLY blocks; fixed styles)
| Block | Look | Color |
|---|---|---|
| **banner** | full-width box, big white title + `·` summary + small italic descriptor | navy `#1F3864` |
| **section_box** | full-width box, big white title + italic subtitle. **UNIFORM color (no rotation)** | indigo `#283593` (the `color` arg is ignored — every section box is the same indigo) |
| **step_badge** | number square + light title bar. **Uniform navy** (NOT rotating) | navy `#1F3864` number / `#ECEFF1` bar / `#1F3864` text |
| **overview / info** | light-blue box, blue bold title + body | `#E3F2FD` / text `#1565C0` |
| **tip** | green box (💡) | `#E8F5E9` / text `#2E7D32` |
| **warning** | orange box (⚠) | `#FFF3E0` / text `#E65100` |
| **code** | dark box, Consolas Bold 10, **token syntax color** | bg `#263238` |
| **bullets / numbered** | circle bullets / numbered list | default |
| **body** | plain paragraph | Lato 11 |
| **link** | clickable hyperlink paragraph (use for links — `body(url)` renders plain text, not a link) | default |
| **image** | centered embedded image `image(url, width=600)` — `url` = PUBLIC image URL (Drive anyone-with-link: `https://lh3.googleusercontent.com/d/<fileId>`); part of the block HTML so it SURVIVES rebuilds; omit to add nothing | default |

**Hierarchy:** banner (doc title) → section_box (big group, color per section) → step_badge (uniform
navy) → body / bullets / callouts / code.

## Fixed rules baked into build.py (do NOT re-decide per session)
- **Section boxes are UNIFORM color (indigo `#283593`) — they do NOT rotate** (decided 2026-06-28; the
  `color` arg on `section_box` is ignored). Step badges = always navy. Nothing rotates / is rainbow.
- **Spacing (breathing room) at a TABLE boundary = use a BLANK SPACER paragraph, NOT paragraph spacing.**
  ⚠️ Google Docs **IGNORES** `spaceAbove`/`spaceBelow` on any paragraph/list-item that directly touches a
  table — it renders flush no matter the value (verified: bullets with `spaceAbove 12pt` still jammed
  against the badge). So a box (banner / section box / step badge / code / callout) followed or preceded
  by text or a `<ul>`/`<ol>` must have an actual **empty spacer paragraph** between them
  (`<p>&nbsp;</p>` in the HTML). Rule: **insert one spacer between a table and any adjacent block on
  BOTH sides** — under the box title (before its bullets/body) AND after the last list item (before the
  next box). This is the ONLY reliable gap around boxes.
- (Non-table boundaries: a normal paragraph after/before another paragraph can still use `spaceAbove 12pt`
  / `spaceBelow 10pt`; spacing only fails at table edges.)
- **Line spacing = 1.15** on every top-level paragraph (body + bullets). The import default is too tight;
  set `lineSpacing: 115` (skip table-internal paragraphs so boxes/code don't stretch).
- **Banner sizing (set via batchUpdate — HTML `<font size>` is ignored):** title line = Arial Bold 20,
  summary line = 11, descriptor line = 9 italic. Without this the banner title imports small.
- **Algorithm explanation = MULTIPLE bullets, one idea per line** (not one dense paragraph). Always
  cover: how the result is built step by step, the input assumptions (e.g. different lengths), and the
  return contract (what is returned / that nothing is returned and how the caller gets the result).
- **Fonts:** body = Lato 11; headings = Arial; **code = Consolas BOLD 10** (inline + dark boxes).
- **Box cells = `contentAlignment: MIDDLE`** + 0.1in padding (text not stuck to the top).
- **Code syntax coloring — method (1) token rules** (no pygments): on `#263238`,
  `#`comment = gray `#9E9E9E` · `$` prompt = green `#A5D6A7` · command/flags = white `#E0E0E0` ·
  strings/paths = teal `#80CBC4`. Per-line, simple regex tokens (good enough for shell/commands).
- **★ `$` is a SHELL PROMPT — use it ONLY on real terminal/shell command lines.** Pseudocode, Python,
  and worked-examples have **NO `$`** (they are not commands). Do not prefix algorithm steps or
  pseudocode with `$`; the green `$`-coloring only applies to actual shell prompts.
- **No emoji in Canvas**, but emoji callouts (💡 💬 ⚠) are fine in Google Docs.

## How to build a doc (the procedure)
1. Write a small driver: a Python list of block specs, e.g.
   ```python
   from build import banner, section_box, step_badge, overview, tip, warning, code, bullets, numbered, body, make
   blocks = [
     banner("Title", "summary · here", "italic descriptor"),
     overview(["point one", "point two"]),
     section_box("[ SECTION A ] Big Header", "subtitle", color="green"),
     step_badge(1, "Step title"),
     body("paragraph text"),
     bullets(["b1", "b2", "b3"]),
     tip("helpful note"),
     code("# comment\n$ command one\n$ command two"),
   ]
   make(blocks, name="My Doc", folder_id="<FOLDER_ID>")   # creates empty gdoc → imports → refines → returns doc id
   ```
2. Run it. `make()` does: build fixed HTML → create empty gdoc in the folder → import → refine
   (spacing, fonts, box-align, code token coloring). One call, same look every time.
3. To EDIT an existing doc with an image (re-import would delete it), do NOT use make(); edit in place.

## Canvas embedding (if asked)
gdoc embed in Canvas = `https://docs.google.com/document/d/<ID>/preview` in an `<iframe>` + a plain
"open" link directly ABOVE it.
**`make()` FORCES, on every creation (unconditional): (1) anyone-with-link (reader) share AND
(2) Publish-to-web (embed enabled, `published`+`publishAuto`+`publishedOutsideDomain` on the latest
revision)** — so the `/preview` AND `/pub` / `/pubembed` embeds render and students can open it with no
manual step. (`rebuild()` keeps the existing sharing; `publishAuto` keeps it published across edits.)

## Reference
- Pairs with `gws-doc.md` (read/format + batchUpdate syntax).
- Master look: gdoc `1UzJhVARxgVB_49KcJg5BxyqIxeKPTiJnf1iRDBEVt6I`.
</content>
