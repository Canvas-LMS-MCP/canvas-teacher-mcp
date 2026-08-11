# ViewGate

⛔ **Post nothing until every artifact Stage A surfaced has been READ.** The poster aborts
otherwise, in dry-run and in `--post` alike. `lib/view_gate.py`.

§0Z did not enforce itself: an assignment was graded with "drawing not re-VIEWED" as a deduction
on students whose drawings the engine had downloaded and the AI never opened. Reminders do not
stop that; a gate does.

## How it works

- `build_manifest` runs at the END of Stage A and writes `<code>_view_manifest.json` — every
  `answer_images` / `answer_docs` path across all students, attempts and questions, deduped so an
  image and its `.view.png` sibling count as one.
- `read_paths` parses the SESSION TRANSCRIPT once at POST time for every `Read` call's
  `file_path`. That is the measurement — no hook, no per-Read cost.
- `check` requires every manifest artifact in that set. Any miss prints the unread files and
  blocks the post.

## Rules this forces

- **Open it with the `Read` tool.** `cat`, `sed` and `head` leave no transcript record, so the post
  is blocked however carefully you read the output. Batching shell output feels faster and costs a
  full re-read.
- **Read the ENGINE path** — the exact `answer_images` / `answer_docs` entries. A private
  re-download's path will not match the manifest.
- **Fail closed, always.** No `view_manifest` field ⇒ blocked; re-run Stage A. Manifest present but
  no transcript ⇒ blocked; pass `--transcript`. Add no bypass flag and no "declare it null to skip"
  — the AI edits the record, so a null it can write is a gate it can switch off.
- Text-only questions surface no artifact and carry no obligation. An assignment with nothing to
  view has an empty manifest and passes trivially. A graph drawn as ASCII is still accepted.

## The proof binds to the GATHER, not the conversation

`build_manifest` stamps `run_id = <code>#<stage_a_runs>@<built_at>`; `verify_and_stamp` copies it
into `<code>_view_verified.json`; `check_verified` accepts the proof while the ids match and the
artifact list is covered, and `report_generator` carries a still-valid proof forward without
touching the transcript.

Reading is a fact about MATERIAL. A re-gather changes the material and voids the proof; a
re-render does not. Without this, fixing one sentence demanded re-opening every artifact.

## Finding the manifest

```
1  json/{code}_rounds.json register entry whose `record` is THIS record
2  json/{code}_view_manifest{_round}.json
3  json/{code}_view_manifest.json  ·  ../{code}_view_manifest.json
4  the previous record's stored `view_manifest`
```

Existence-check every candidate; a path that does not resolve is not a manifest and falls through.
Nothing resolves ⇒ the render FAILS and writes nothing — a render that knows the post cannot
proceed has no business succeeding.

Store the path as DATA (`"view_manifest"` in the record) and read that field. Never rebuild it from
the file name. Paths are folded to `~/…` (`Local/Paths.md`); `_norm()` is the single choke point
every comparison passes through.

## What it does not catch

Comprehension. You read it and still misjudged is a Stage-B error, a different layer. Path presence
is the minimal non-gameable proof that you looked.
