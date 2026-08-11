---
name: git-asmt
description: "GLOBAL L1 ENTRY POINT (dispatcher) for creating a GitHub coding assignment end-to-end. Routes to two children: git-asmt-repo (build the solution/tests + prove 100/100 + ship the Starter + register in the org-hub) and git-asmt-page (build the Canvas assignment page via git_page). Language-agnostic; the language mechanics are L2 (git-asmt-repo/languages/*) and the course coordinates are the L3 course wrapper (config). Use when the user says 'make/build/create assignment <CODE>' — this decides repo-first then page."
tools: [build_starter_repo, build_coding_assignment_page]
---

# git-asmt — L1 dispatcher (entry point)

The single door for "make a git coding assignment." It holds **no mechanics** — it decides ORDER and
routes to the two children. Language = L2 (`git-asmt-repo/languages/*`); course coords = L3 wrapper.

```
git-asmt  (this — dispatch + order)
 ├─ git-asmt-repo   build solution/tests · audit (§0 fidelity) · prove 100/100 · Starter · hub register
 └─ git-asmt-page   Canvas assignment page + parts (test-items · per-item points · guide · instruction · prototype)
```

## Order (repo BEFORE page)
The page needs the repo done first — the **Request link** only resolves once the CODE is registered in
the org-hub config, and the page's **test-items table + rubric** come from the *actual* tests. So:

1. **`git-asmt-repo`** → source+tests audited, 100/100 proven, Starter cut, CODE registered in the hub.
2. **`git-asmt-page`** → fill the `asmt` dict from the same source/instruction → `git_page` → upload.

(If the repo is already done in a prior session, confirm it is registered, then go straight to page.)

## Shared inputs (passed to both children)
- `CODE` (e.g. `A71`), the **instruction source** (Canvas/gDoc/gSlides, via canonical readers), and the
  L3 course wrapper (course id, org, repo/dir naming, `language`, chapter→model map). Everything
  coordinate-shaped comes from `course_config.load(<course>)`; nothing is hardcoded here.

### Resolving the instruction source — read the WHOLE assignment page, then compose

When the assignment already exists in Canvas, the spec is **not one artifact** — it is everything the
page carries, and no single part is complete on its own. Read **all** of it, then compose one
instruction from the union:

1. `canvas_rest.fetch_assignment(...)` → the description **body text** (what the page itself states).
2. **Every EMBEDDED document** in that body — a slide deck (follow the iframe's `slide=id.<objectId>`
   to the exact page it points at), an instruction gDoc, a PDF. Read the embedded content, not just
   the fact that an embed exists.
3. **Every LINKED document** — a `[link]` to a gDoc/deck/file that is not embedded is still part of
   the instruction; students open it too.

Use the canonical readers (`canvas_rest`, `gws`, `attachments.read`); `canvas_core.links.extract_links`
inventories a body's links/embeds so nothing is missed. Never hand-scrape, and never stop at the first
source that looks sufficient.

**Composing them:** the parts are complementary, not competing — the body typically frames the task
while the deck/doc carries the detail. Where two genuinely CONFLICT (an old body line vs a revised
deck), the more specific and more recently updated artifact governs, and **the conflict is reported to
the instructor** — a page whose own parts disagree is a defect students will hit too.

A repo in another course with the same problem is **content ideas only**; it is not part of the
instruction and never outranks the page.

**Do not re-pick or rebuild an embed URL** — the page builder reuses the assignment's existing URL
verbatim (`assignment-page-builder`, "Slide embeds — use the GIVEN URL").

## What is L1 vs delegated
- **L1 (here + the two children):** what must happen regardless of language — order, audit method,
  §0 instruction-fidelity harness + GATE A0, ship pattern, 100/100 verification, page parts, gates.
- **L2 (delegated):** how to compile/run/assert in a language (`git-asmt-repo/languages/{cpp-stdout,
  cpp-catch2,python-pytest}.md`).
- **L3 (delegated):** which course — org, prefix, `language`, chapter→model map (course wrapper + config).

## Invoke a single role directly
Merged does not mean all-or-nothing: call **`git-asmt-repo`** alone to just build/test/verify a repo,
or **`git-asmt-page`** alone to just (re)build a Canvas page. `git-asmt` is only the ordered entry when
you want the whole thing.

## References
- Children: `git-asmt-repo/SKILL.md`, `git-asmt-page/SKILL.md`.
- L3 wrappers: each course's `…-git-repo` (e.g. <course> `<course>-git-repo`).
- Policy: `CourseGlobalWorkflow/GRADING.md`, `Access/GitHub.md`, `Access/GitHub.md`.
- Plan/history: `working_logs/jul-24-2026.md`.
