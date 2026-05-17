# Docx + charts production module — design (2026-05-16)

Companion to [`2026-05-16_docx-drive-spike.md`](2026-05-16_docx-drive-spike.md).
The spike validated the architecture; this doc designs the actual
production module.

## Context

After the 2026-05-16 spike legs 1 and 2 passed (docx → Doc fidelity
clean; xlsx → Sheet native charts intact), Luke chose to skip a
one-off "dress rehearsal" preview (Path A from the chat) and go
straight to building the production module (Path B). Reason: a
real preview would have required a half-day generator that gets
thrown away. Building the production module produces the same
preview artefact as a side effect, plus the foundation for every
future cycle. Half the work doubles up.

Lisa-feedback driver: she wants charts on top findings. NotebookLM
constraint forces the architecture — `.md` stays text-only (per the
keep-LLM-output-outside-NotebookLM-inputs rule in
`memory/architecture_journalist_surfaces.md`), a parallel `.docx`
carries charts. The `.xlsx` also gains native charts at the same time.

## What's already in place

Useful mechanisms already shipped that this module plugs into:

- **`--no-record` flag** (`scrape.py:449`) → passes `record=False`
  to `export()` which skips the `brief_runs` INSERT. The "side
  export that doesn't advance the cycle" mechanism is already
  built. `python scrape.py --briefing-pack --no-record` works
  today for the .md path; the docx pipeline will inherit this for
  free.
- **Modular section renderers** under `briefing_pack/sections/`
  (18 modules). Each returns a `_Section` dataclass containing
  markdown. The orchestrator (`render()` in `briefing_pack/render.py`)
  assembles them.
- **`_Section` is a dataclass** (`_helpers.py:52`) — trivial to
  extend with a `docx_blocks` field carrying the parallel docx
  representation if we go that route.
- **`_compute_top_movers`** (`_helpers.py:315`) already does the
  filtering, scoring, and ranking for the top-N list. The chart
  recipes just need to fetch the underlying time series for each
  returned mover.
- **Spike outputs** (`scripts/drive_spike_local.py`,
  `exports/spike-2026-05-16/*.docx, *.xlsx`) carry the verified
  defaults: A4 portrait, 10mm margins, `Mm(190)` chart width,
  matplotlib chart style, openpyxl native chart pattern.

## Architecture: three choices to make

### Choice 1 — Where the docx rendering logic lives

**(A) Each section file gains a `to_docx()` method.** `_Section`
carries both markdown and docx representations. Sections own their
own rendering for both surfaces.

- ✅ Shares the section-specific data-fetching logic (no duplication
  of "which findings to show for top movers")
- ✅ Editorial structure stays in lock-step between `.md` and `.docx`
- ❌ Every existing section file grows; touches many files for v1
- ❌ Risks breaking the existing `.md` renderers (the NotebookLM-feed
  surface) for a feature only one journalist has asked for so far

**(B) Parallel `sections_docx/` directory mirroring `sections/`.**
Each markdown section gets a sibling docx section. Orchestrator
dispatches by output type.

- ✅ Zero touch to existing section files
- ✅ Sections can diverge if editorial value differs by surface
- ❌ Duplicates the section dispatch and ordering logic
- ❌ Drift risk: markdown and docx structures get out of sync over
  time

**(C) Single new docx module that subscribes to the same
data-fetching helpers as the sections do, but emits docx directly.**
The docx is a *subset* of the markdown content (v1: just top-5
movers with charts), not a full mirror.

- ✅ Smallest possible v1 — one new file (`briefing_pack/docx.py`)
- ✅ Zero touch to existing section files
- ✅ Decouples Lisa-facing surface from NotebookLM-feed surface
- ❌ If full coverage is wanted later, ends up duplicating editorial
  structure across two implementations
- ❌ Lisa might want the full Tier 1/2 content, not just top-5

**Recommendation: (C) for v1, with a clear upgrade path to (A) if
Lisa's feedback after v1 demands full coverage.** Rationale: v1 is
"prove the production architecture works end-to-end with real data."
That doesn't need full markdown-content parity. If Lisa says "great,
now I want everything", the answer is "let's refactor section.py to
carry both surfaces" — but that's a deliberate decision triggered by
known editorial demand, not a speculative architecture choice now.

### Choice 2 — Chart recipes per finding subkind

Top-5 movers are typically `hs_group_yoy*` findings (the composite
score in `_compute_top_movers` filters to that family). So v1 only
needs one chart recipe: **`hs_group_yoy*` → two-line monthly chart,
prior 12mo window vs current 12mo window, 24 months on the x-axis.**

Data fetch shape:
```sql
-- For an hs_group_yoy finding with current_end=YYYY-MM-01:
SELECT period, SUM(value_eur) AS monthly_eur
  FROM observations
  JOIN hs_group_members ON ...
 WHERE hs_group_id = ?
   AND scope = ?            -- e.g. 'EU27'
   AND flow = ?              -- 'import' or 'export'
   AND period >= current_end - INTERVAL '24 months'
   AND period <  current_end
 GROUP BY period
 ORDER BY period;
```
Split into prior_series (months -24..-12) and current_series
(months -12..0) for the chart.

Chart shape per spike: figsize (6.5, 3.2) in, dpi 150, grey for prior
+ red for current, generous title, x-tick rotation 45°.

**v2 chart recipes** (deferred until Lisa asks):
- `gacc_bilateral_aggregate_yoy*` → grouped bar (top-5 reporter
  breakdown, prior vs current 12mo)
- `mirror_gap*` → two-line (China-reported export vs EU-reported
  import, monthly)
- `hs_group_trajectory*` → multi-year line with the trajectory
  pattern (rising/dip-and-recovery/etc.) overlaid as an annotation
- `partner_share*` → stacked area or pie

Each is ~100 lines of renderer + a focused test. Add when needed.

### Choice 3 — Native charts in `04_Data.xlsx`

Audit result: `sheets_export.py` (957 lines) currently produces a
chart-less workbook. The spike showed openpyxl-native charts
round-trip cleanly to Sheets. So part of this module is adding
native charts to the data spreadsheet too.

**Scope for v1: one chart per top-5 mover, on the relevant tab.**
The spreadsheet already has dedicated tabs per finding subkind
(e.g. `gacc_bilateral_yoy` tab from 2026-05-15). We add a `Charts`
tab (or scatter charts onto existing tabs) for the top-5 movers'
underlying series.

Open question: where does the chart go? Options —
- **One dedicated `Charts` tab** with 5 charts stacked vertically.
  Cleanest. Mirrors the docx top-5 section. Easy to find for Lisa.
- **Chart embedded in the per-subkind tab where the data lives.**
  More "data-and-its-visualisation are together" but means top-5
  movers' charts are scattered across multiple tabs.

Recommendation: dedicated `Charts` tab. Same shape and ordering as
the docx top-5 section so Lisa can cross-reference visually.

## CLI integration

Pipeline additions:

```
python scrape.py --briefing-pack [--no-record] [--docx]
```

- `--docx` is the new flag. Off by default for v1 (additive,
  opt-in, doesn't break any existing flow).
- Combine with `--no-record` for the dress-rehearsal Luke asked
  about: `python scrape.py --briefing-pack --no-record --docx`.
- Once stable (say after 2-3 cycles of editorial review), promote
  `--docx` to default-on, then remove the flag.

When `--docx` is set, `export()` additionally writes:
- `03_Findings.docx` (the parallel docx, currently top-5 only)
- The `Charts` tab inside `04_Data.xlsx` (modifies an existing
  artefact rather than creating a new one)

`02_Leads.docx` is **deferred to v2** — leads is LLM-scaffolded
prose and a chart on it would be a chart-of-a-narrative-claim, which
collides with the "keep-LLM-output-outside-data" principle. Solve
later once we know whether Lisa wants charts there at all.

## Test strategy

Existing project bar: 273 tests, focused per-module. Match that.

Docx generation tests:
- **Smoke**: the file is produced, is valid (`Document(path)` opens
  without error), has the expected top-level structure (title,
  one H1 per top mover, table, picture).
- **Content assertions**: extract paragraph text, assert key
  strings present (group name, the YoY headline figure, the
  trace token).
- **Chart presence**: each top mover has at least one inline image.
  Don't assert on chart pixels — too brittle.
- **Determinism**: two runs against the same DB state produce
  byte-identical docx (with matplotlib seeded, openpyxl chart
  config identical). Important for the principle-5 (idempotent)
  bar. Catch via SHA256 comparison in a test.

Xlsx chart tests:
- **Smoke**: workbook opens, has a `Charts` tab, each chart object
  has a non-empty data reference.
- **Determinism**: same as above.

Total new test count probably +12 to +18 tests for v1.

## Phases

### v1 — top-5 movers + charts (this slice, ~1-1.5 days)

- New module `briefing_pack/docx.py` (~400 lines): orchestrator +
  one chart recipe (`hs_group_yoy*` rolling-12mo line).
- Extend `sheets_export.py` with a `Charts` tab populated with the
  same top-5 movers' underlying data + native LineCharts.
- `--docx` CLI flag wired into `scrape.py`.
- Tests as above.
- A real end-to-end run: `python scrape.py --briefing-pack
  --no-record --docx` produces a real-data dress rehearsal Luke
  can show to Lisa.

### v2 — more chart recipes (~half-day per family, demand-driven)

Add `gacc_bilateral_aggregate_yoy*`, `mirror_gap*`,
`hs_group_trajectory*` chart families one at a time, triggered by
Lisa asking for them or by a story needing one. Each is mostly a
new function in `briefing_pack/docx.py` + a new test file.

### v3 — Drive upload (~half-day, after OAuth lands)

`scripts/drive_spike.py` graduates into `briefing_pack/drive_export.py`.
Adds `--upload-to-drive` flag. Folder hierarchy mirrors local
`exports/` shape (top-level `Meridian exports/`, per-cycle subfolder
inside). Uses upload-with-conversion to land native Docs + Sheets in
Drive. Pageless toggle via Docs API if we decide it's worth it.

### v4 — full markdown-content parity in docx (deferred, demand-driven)

If after v1/v2 Lisa says "I want the full Tier 1/2 content in the
docx, not just top-5", that's the trigger to refactor toward
architecture (A) — every section module gains a `to_docx()` method,
the docx renderer becomes a true parallel of the markdown renderer.

This is a known fork in the road; the design doesn't pre-empt it.

## Concrete first slice (~half-day, picks up before access restoration)

Order of implementation that lets us validate the architecture
before going wide:

1. **Stub `briefing_pack/docx.py`** with a top-level
   `render_docx(out_path, top_movers, ...)` that produces a
   minimal valid docx with just the top-5 movers list (no charts
   yet). Wire `--docx` into `scrape.py` and the export pipeline.
2. **Add the rolling-12mo chart recipe.** New function
   `_chart_hs_group_yoy_rolling_12mo(cur, finding) -> bytes`
   (PNG). Tested in isolation against a fixture finding.
3. **Insert charts into the docx** per top mover, mirroring the
   spike's layout (heading per mover, two-paragraph prose, chart,
   small table of period-by-period values).
4. **Page setup defaults** lifted verbatim from
   `scripts/drive_spike_local.py:build_docx()` — A4, 10mm margins,
   `Mm(190)` chart width.
5. **Determinism check.** Run twice against the same DB state,
   assert byte-identical output. Fix any non-determinism
   (matplotlib font-cache, openpyxl creation timestamps, etc.).
6. **End-to-end smoke**: `python scrape.py --briefing-pack
   --no-record --docx` → real top-5 with real charts, in a real
   side-export bundle.

Steps 1–6 land in a single commit (or 2–3 small ones), titled
something like `briefing-pack: add docx output (top-5 movers + charts)`.

After this slice, the `Charts` tab in the xlsx is the next focused
piece of work, then v2 chart recipes as demand arrives.

## Risks / open questions

- **Determinism with matplotlib.** matplotlib has caches, font
  fallback, and a global font-rendering pipeline that can produce
  pixel-different PNGs run-to-run on the same Mac. Need to lock
  this down — likely via fixed font + `matplotlib.use("Agg")` (the
  spike does this already) + explicit `dpi`. May need to set
  `MPLBACKEND` env var. Worth testing this explicitly in step 5.
- **openpyxl write timestamps.** openpyxl writes a "created" /
  "modified" timestamp into the xlsx. Need to either explicitly
  set these (constant) or ignore them in the determinism check.
- **What about `02_Leads.docx`?** Currently deferred. Means Lisa's
  docx output is structurally smaller than her .md (which has both
  Leads and Findings). She might miss Leads. Worth flagging at
  v1 review.
- **Pageless mode.** Set after the fact via Docs API or by hand?
  Doesn't affect anything until OAuth is wired. Defer to v3.
- **Existing `04_Data.xlsx` tab structure.** Need to check that
  adding a `Charts` tab doesn't collide with any existing tab name
  in `sheets_export.py`. Quick grep, no real risk.
- **Sheets API: does the converted Sheet preserve chart anchor
  position?** Verified loosely in the spike (the chart appeared
  in the right tab) but not whether the cell-anchor exactly
  matches. Worth a re-check during step 6.
- **Spreadsheet chart determinism on re-run.** openpyxl chart
  internals include some auto-generated IDs. Need to either pin or
  ignore in determinism testing.

## When this gets picked up

Picking up before OAuth access is restored is fine — the entire v1
slice produces local files only. The Drive upload (v3) is properly
deferred until Monday's access restoration. Sequence Luke wants is
"v1 local first → Lisa eyeballs → v3 Drive next."

Update this doc's "Status" line below when work starts.

## Status

**v1 COMPLETE — 2026-05-16.** Five commits land the whole slice:

- [`f2b5c1c`](https://github.com/hoyla/meridian/commit/f2b5c1c) —
  stub module + `--docx` CLI flag
- [`d3f3bfc`](https://github.com/hoyla/meridian/commit/d3f3bfc) —
  24-month rolling-window charts in the docx
- [`eaf37cd`](https://github.com/hoyla/meridian/commit/eaf37cd) —
  docx tests (24 new)
- This commit (Charts tab) — native LineCharts in `04_Data.xlsx`
  + 7 new tests

End-to-end run (`python scrape.py --briefing-pack --no-record
--docx`) produces a real dress-rehearsal bundle against today's DB:
`03_Findings.docx` with 10 mover cards + matplotlib charts, plus
`04_Data.xlsx` with a `Charts` tab carrying the same 10 movers as
native openpyxl LineCharts (editable in Google Sheets). Both
surfaces round-trip cleanly through Drive → Google Docs / Sheets
(verified 2026-05-16 evening with real-data content, not just
spike-synthetic).

Test suite: 304 passing (up from 273 pre-slice), 5 skipped, 0
regressions. Coverage spans pure-function units (`_pick_eur_scale`,
`_months_back`, `_month_iter`, `_flow_label_for_subkind`,
`_build_chart_png`) and integration paths (smoke / structure /
empty-movers / chart-unavailable / `top_n` truncation / page-setup
preservation / xlsx Charts tab presence + data layout + native
chart count).

Determinism handled per the design's "structural-stability +
chart-bytes SHA256" approach — docx-internal and xlsx-internal
timestamps don't round-trip byte-identically and that's
acknowledged rather than chased.

## What's next

v2, v3, v4 from the original phase plan — picked up demand-driven:

- **v2 — more chart recipes.** `gacc_bilateral_aggregate_yoy*`,
  `mirror_gap*`, `hs_group_trajectory*`, `partner_share*`. Add when
  Lisa asks for a specific story type or a real cycle surfaces
  a gap.
- **v3 — Drive upload.** Picks up once GCP project access is
  restored. `briefing_pack/drive_export.py` wrapping `files.create`
  with upload-with-conversion. `--upload-to-drive` flag. Folder
  hierarchy `Meridian exports / YYYY-MM-DD-HHMM / *.docx, *.xlsx`.
- **v4 — full markdown-content parity in the docx.** Triggered
  2026-05-16 late evening — see § "v4 addendum" below.

Promotion of `--docx` from opt-in to default-on: defer until Lisa
has eyeballed 2-3 real cycles' worth of output and confirmed the
shape works.

## v4 addendum — full markdown-content parity (added 2026-05-16)

### Trigger

Mid-evening 2026-05-16, Luke pointed out that v1's `.docx` is a
chart-bearing top-N extract, not a `.md`-parallel-with-charts as
originally intended. The architectural rule was "`.docx` carries
the same content as `.md` plus charts at top-N". v1 shipped chart
cards only; the rest of the markdown's structure (Tier 1 diff,
Tier 2 state-of-play, mirror gaps, methodology footer, sources
appendix, etc.) doesn't appear in the docx. That's a scope miss
to fix before v2 chart recipes or any polish work.

### Approach decision

Three implementation paths were considered:

**(A) Each section file gains a `to_docx()` method.** Touches all
17 section files; each grows a parallel renderer. Most invasive.
Editorial structure stays in lock-step automatically.

**(B) Markdown → docx translator (pure Python via mistune).** Parse
the rendered `findings.md` via mistune, walk the AST, emit docx
blocks via python-docx. No external dependencies beyond the
already-installed python-docx. Chart injection happens at the AST
node corresponding to the top-movers section. ~250-400 lines for
the translator covering our markdown subset (headings, paragraphs,
bold + italic + code spans, ordered + unordered lists, tables,
hyperlinks, blockquotes). Existing markdown rendering stays
canonical; nothing in `briefing_pack/sections/` changes.

**(C) pandoc subprocess.** `pandoc findings.md -o findings.docx
--reference-doc=template.docx`. Best output quality (pandoc is the
gold-standard md→docx tool). External binary dependency. Chart
injection by post-processing the produced docx via python-docx.

**Decision: (B).** Pure-Python, no subprocess dependency, full
control over output shape, deterministic. Our markdown subset is
small enough that a focused mistune-based translator stays under
400 lines. If we later need rich features that the subset can't
cover, pandoc is still available as a drop-in alternative.

Approach (A) was rejected because touching every section file
risks the `.md` (NotebookLM feed) for a feature only the `.docx`
needs. The translator approach keeps the markdown renderers as the
single source of editorial truth.

### Chart injection

Top movers section's markdown emits a numbered list. The
translator detects the "Top N movers" `<h2>` and, when processing
each list item, inserts a chart picture after it. Chart data fetch
re-uses `_fetch_finding_detail` + `_fetch_monthly_eur_series` from
v1's `briefing_pack/docx.py`. List items are matched to findings
via the `finding/{id}` token already present in the markdown
(stable, deterministic, no parallel data structure needed).

### Out-of-scope details deferred to a future commit

- **HTML embedded in markdown.** If any section ever emits HTML
  (currently none), the translator passes it through as plain
  text. Not a real concern given the existing render pipeline.
- **Tables with cell-level formatting.** Cells render as plain
  paragraphs; bold/italic inside cells survives but more complex
  formatting (lists inside cells, nested tables) is unlikely in
  practice.
- **Hyperlinks inside list items.** The translator renders the
  link text; the URL is preserved as a docx hyperlink relationship.
  Visual fidelity verified after first integration run.

### Status

**v4 COMPLETE — 2026-05-16 evening.** Eight commits land the work:

- `713a337` — design addendum (this section)
- `11783d3` — scaffold `briefing_pack/md_to_docx.py`
- `910b5b2` — core block + inline handlers
- `f4baa7b` — GFM tables with alignment + inline runs
- `26fdb10` — integrate translator into `briefing_pack/docx.py`,
  full content + charts with first-occurrence-only guard
- `ff10df9` — rename `render_top_movers_docx` → `render_findings_docx`
  + update integration tests for v4 shape
- `f181419` — 22 focused unit tests for the translator
- `2498b1f` — silence matplotlib categorical-units INFO logs

End-to-end verified against today's DB: 438KB markdown → 672KB
docx, 4331 paragraphs (1 H1 + 14 H2 + 98 H3 + 179 H4 + 53 normal +
8 numbered + 3978 bullets), 10 inline charts (one per top-mover
finding, first-occurrence-only).

Full test suite: 327 passing (+22 translator unit tests +
adjustments to existing docx integration tests for the v4 shape),
5 skipped, 0 regressions.

mistune added as a new dependency (3.2.1). python-docx, matplotlib,
mistune are now soft dependencies — only imported when `--docx`
is set.

### Architecture in place after v4

- `briefing_pack/render.py` orchestrator unchanged conceptually:
  renders markdown via the existing section modules, writes
  `03_Findings.md`. When `docx=True`, additionally invokes the
  docx pipeline.
- `briefing_pack/docx.py` is the docx-pipeline orchestrator:
  re-renders the same markdown, pre-computes per-finding chart
  PNGs for top-N movers, applies page setup, hands both to the
  translator. Sole entry point: `render_findings_docx`.
- `briefing_pack/md_to_docx.py` is the markdown → docx translator:
  pure function from `(Document, markdown_text, chart_lookup) →
  Document mutated in place`. Reusable for any future md-backed
  docx surface (Leads.docx, Groups.docx, etc.) without changes.
- `sheets_export.py` unchanged from v1's Charts tab work — that
  surface is already feature-complete and well-tested.

## v2 addendum — chart variety (added 2026-05-16 late evening)

### Trigger

Luke flagged that the v4 .docx output had only one chart type
visually (the rolling-12mo line chart). The spike had shown two
shapes — a deliberate editorial decision to give Lisa
varied surfaces to react to was preferable to waiting for her to
specify in the abstract.

### What landed

Two new chart shapes, both as additions to the existing top-N
chart-lookup pipeline (no architectural changes; the translator's
`chart_for_finding` callable already returned `list[bytes]` so
multiple charts per finding were supported):

**Option 1 — per-reporter grouped bar for top movers.** Each
`hs_group_yoy*` top mover now gets TWO charts:
1. Existing rolling-12mo line (prior + current 12mo monthly series).
2. New grouped bar showing the top-5 reporters by absolute YoY
   delta — prior 12mo (grey) vs current 12mo (red). Answers Lisa's
   likely "which country is driving the move?" follow-up.

Data source: each finding's `detail.per_reporter_breakdown` field
(populated by Phase 6.11 in `anomalies._build_per_reporter_breakdown`).
No new SQL.

**Option 2 — bilateral summary bar for top GACC bilateral findings.**
New finding family covered: `gacc_bilateral_aggregate_yoy` +
`gacc_bilateral_aggregate_yoy_import`. Selection: top-N
latest-anchor bilaterals by |yoy_pct|, filtered to ≥5pp move
(matches Tier 1 diff's material-shift cutoff).

Chart shape: two-bar prior-vs-current 12mo grouped chart with €
value annotations, partner label + flow direction + YoY % +
direction arrow in the title. Simpler than the hs_group_yoy
line chart because bilaterals are headline-figure findings —
turning two abstract percentages into € magnitudes is the
editorial win.

### Result against real data

20 findings charted (10 hs_group_yoy top movers + 10 bilaterals),
30 total chart objects (10 × 2 + 10 × 1). File size grew from
672KB to 1.1MB — still well within Drive upload limits.

### Status

**Options 1 and 2 COMPLETE — 2026-05-16 late evening.** Two commits:

- `caa8efd` — Option 1 (per-reporter bar) + chart_for_finding
  list-based API + 11 new/updated tests.
- `b68ded9` — Option 2 (bilateral summary bar) + 10 new tests.

Full suite: 345 passing (+18 new since v4-complete), 5 skipped,
0 regressions.

### What's left for v2

The original v2 scope listed four chart families:
`gacc_bilateral_aggregate_yoy*` (done), `mirror_gap*` (deferred),
`hs_group_trajectory*` (deferred), `partner_share*` (deferred).

Lisa-eyeball-driven from here — wait for her to react to the
current variety before committing to more shapes.

After v1 closes, the path forward is unchanged: v2 (more chart
recipes, demand-driven), v3 (Drive upload, OAuth-gated), v4 (full
markdown-content parity, demand-driven).
