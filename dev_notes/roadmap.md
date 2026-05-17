# Roadmap — outstanding work

What's still open. For history of what shipped, see
[`history.md`](history.md). For the design rationale that drove
the original Phase 1–6 plan, look at the git log around
`8f18e68`–`5d0e23e` (2026-05-09 to 2026-05-10).

## Observability / logging follow-ups (2026-05-15 evening arc)

Four new audit-log surfaces shipped tonight along with
[`dev_notes/logging-policy.md`](logging-policy.md):
`routine_check_log` (per-source Routine telemetry + lifecycle
bookends), `llm_rejection_log`, `periodic_run_log`,
`findings_emit_log`. CLIs: `--source-status`, `--llm-rejections`,
`--periodic-history`, `--emit-history`. What's still open:

### Ad-hoc CLI coverage for `findings_emit_log`

Today's integration is in `periodic.run_periodic`'s analyser
dispatch — so `--periodic-run` cycles write rows, but ad-hoc
`python scrape.py --analyse hs-group-yoy` from the CLI does not.
Closing this means instrumenting each `detect_X()` directly (~9
functions in `anomalies.py` + `llm_framing.detect_llm_framings`).
The cleanest pattern is a context manager that wraps the body of
each function: open it after `analysis_run_id` is created, capture
the returned counts at exit, write the row in `__exit__`. ~half a
day; deferred until ad-hoc runs become a frequent debugging case.

### Supersede-reason classification

`findings_emit_log` records aggregate counts (`new` / `confirmed`
/ `superseded`) per analyser invocation, but doesn't distinguish
*why* a row was superseded — data change vs method-version bump
vs caveat-list change. Today's only way to tell is to inspect the
old and new rows' `detail.method` manually.

Implementation sketch: add `supersede_reason TEXT` and
`prior_value_fields JSONB` to `findings`, populate them in
`findings_io.emit_finding` on the supersede branch by comparing
the new `value_fields` against the prior row's. Reasons:
`method_bump` (only `method` differs), `value_change` (numeric
fields differ), `caveat_change` (caveat list differs), `mixed`.

Editorial payoff: the brief's Tier 1 method-bump-churn
auto-suppression in [briefing_pack/sections/diff.py](../briefing_pack/sections/diff.py)
could use a structured signal instead of inferring from
value-identity. The first-export audit on 2026-05-12 surfaced this
as the kind of inference that ought to be explicit.

### Other silent-decision surfaces flagged but deferred

Lower priority — pick up when one of them breaks visibly:

- **Currency-unit guard rejections.** `db._assert_currency_unit_consistent`
  raises on bad pairs. Adding a log table would capture which
  release pages tripped it.
- **Parser anomalies.** Title-format mismatches, unexpected column
  counts, etc. Most raise today; some `log.warning`. Per-anomaly
  table if frequency rises.

## Near-term (likely next session)

### Docx + Drive upload — v1 and v4 shipped 2026-05-16

Lisa-feedback arc on docx + charts is substantially complete:

- **v1** — `--docx` CLI flag + chart-bearing top-N renderer +
  xlsx `Charts` tab. Commits `f2b5c1c` → `0b0d88b`.
- **v4** — full markdown-content parity (the docx now contains
  the same sections as `03_Findings.md` plus charts at top-N
  movers via a mistune-based md→docx translator). Commits
  `713a337` → `f181419`. Design addendum captured in
  [`2026-05-16_docx-production-module-design.md`](2026-05-16_docx-production-module-design.md).

What's still open from this arc:

- **v2 chart recipes** (partial — see design doc § "v2 addendum").
  Per-reporter bar (Option 1) and bilateral summary bar (Option 2)
  shipped 2026-05-16 to give Lisa varied surfaces to react to.
  Three families still deferred: `mirror_gap*`,
  `hs_group_trajectory*`, `partner_share*`. Demand-driven from
  here — wait for Lisa's reaction before committing to more.
- **v3 Drive upload.** Waiting on Guardian GCP project access
  restoration (requested 2026-05-16; expected early week of
  2026-05-17). Spike spec at
  [`2026-05-16_docx-drive-spike.md`](2026-05-16_docx-drive-spike.md)
  — legs 1 and 2 verified manually; leg 3 (OAuth) deferred to
  access restoration. When unblocked: ~half-day to graduate
  `scripts/drive_spike_local.py` into `briefing_pack/drive_export.py`,
  add `--upload-to-drive` flag, folder hierarchy
  `Meridian exports / YYYY-MM-DD-HHMM / *.docx, *.xlsx`.
- **Promote `--docx` from opt-in to default-on.** Defer until
  Lisa has eyeballed 2-3 real cycles' worth of output.

### Watch the first 2-3 real cycles + decide delivery vector

Periodic-run **pipeline + Routine** shipped 2026-05-11 (Phase 6.9 /
6.10 — see `history.md` and
[`periodic-runs-design-2026-05-11.md`](periodic-runs-design-2026-05-11.md)).
Routine fires daily at 09:01 local time. What remains is observation
and Layer-3 design:

- **Click "Run now" once from the Scheduled sidebar** to pre-approve
  the tools the Routine uses (`psql`, `python scrape.py ...`).
  Otherwise the first real scheduled run will pause on permission
  prompts.
- **Watch the first 2–3 real cycles land** (whenever the next
  Eurostat release publishes — typically 6-8 weeks after period
  close). Tier 1 currently shows same-day method-bump churn
  (everything created today); after the first real Eurostat-release
  cycle, it'll show the actual data diff. Validate that the diff
  reads usefully editorially.
- **Decide on delivery vector** (Layer 3) once we've seen what a
  real cycle looks like in Lisa's hands. Don't pre-pick
  email / Slack / Drive — pick after the first usable export
  has been delivered manually a few times.
- **Migrate Luke's environment** from laptop to desktop. Steps in
  the design doc § "Migration: laptop → desktop". Routines are
  account-bound; the pipeline is portable via `git clone` +
  `pg_dump | pg_restore`.

## Coverage extension (surfaced by the 2026-05-11 Soapbox validation pass)

Items the Soapbox validation surfaced as real gaps but not on
the periodic-runs critical path. Each is small-to-medium and
self-contained. See
[`soapbox-validation-2026-05-11.md`](soapbox-validation-2026-05-11.md)
for the per-claim test that motivates each.

### Eurostat-side HS-level mirror for "China's exports to EU"

Soapbox routinely quotes GACC-side HS-level figures ("China's
EV+hybrid exports to EU +87% in Q1 2026 at $20.6B"). GACC
sections 5/6 in our DB have only ~30 hand-curated commodity
names (no HS codes), so the GACC-side HS-level test is blocked
on parser work for sections 5 and 6 specifically. The cleaner
path is to rely on Eurostat for HS-level and accept the CIF/FOB
caveat — but the editorial register ("China reported $20.6B...")
isn't substitutable.

### 2017 pre-v2 COMEXT format duplicate `000TOTAL` rows

Surfaced by the §5.4 snapshot refresh on 2026-05-11. The pre-v2
bulk-file format produces duplicate `000TOTAL` rows per
(reporter, period, partner, flow, stat_procedure) — 2017 sp=1
has 648 rows vs 2018 sp=1 has 351. Analyser output is unaffected
(HS LIKE filters skip aggregate rows) but any 2017 raw-row
aggregate rollup is 2x inflated. Forward work to dedupe or
re-ingest 2017 with the v2 parser. Independent of the 000TOTAL
filter rule resolution from 2026-05-10.

## Methodology depth (pick up if a story warrants it)

### Editorial calibration of `low_base_threshold_eur` via shock-validation backtest

Phase 6.3 sensitivity sweep showed €50M is the single largest
editorial-framing driver — 49% of `hs_group_yoy*` findings would
flip low_base classification across €5M–€500M. The default has
never been calibrated against editorial reality. Approach:

1. Take each shock from `shock-validation-2026-05-09.md` (2018
   Section 232 steel, Q1 2020 COVID lockdown, Feb 2022 Russia
   invasion, Oct 2023 EV probe).
2. For each, identify which HS groups carried the story and what
   their absolute 12mo €-figures were at the surfacing anchor.
3. Replay the sensitivity sweep — would those groups have been
   suppressed under €100M? Surfaced cleanly under €25M?
4. Pick the threshold that minimises both false-positive
   (low_base flag on a real story) and false-negative (no flag
   on a story that genuinely rests on a niche base).

Same exercise plausibly applies to the Soapbox-validation
2026-05-11 doc's per-claim concur table. Decide whether to keep
€50M (the engineered floor), shift it, or move to a per-group
threshold seeded from the group's typical EU-27 12mo magnitude.
Discussed 2026-05-12 with the first-export audit.

### CN8 concordance table (Phase 4 carry-over)

Full mapping of old→new codes across Eurostat's annual revisions.
Currently we apply a blanket `cn8_revision` caveat to any YoY
window spanning a year boundary; a real concordance would let us
strip the caveat where the relevant codes didn't change. The
historical Eurostat backfill (2017–2026) spans 9 CN8 revisions so
the blanket caveat is on most findings. Pick up when a story rests
on a precise YoY for a specific HS-CN8 code.

### Per-(country, commodity) CIF/FOB granularity

Phase 4 carry-over partially addressed in
`cif-fob-baselines-2026-05-10.md`. Per-(EU member state, China)
margins are now in `cif_fob_baselines`. The OECD ITIC SDMX endpoint
also supports HS-4 splits (1224 commodities × 28 EU countries × CN
≈ 34k rows) for per-(country, commodity) precision. Schema-extend
`cif_fob_baselines` and pull when a story needs it.

### Structural-break detection (Chow / CUSUM)

Statistically right but unstable on the 11 periods we had at
Phase 1. With the historical Eurostat backfill we now have 110
periods; this is ready to move from parked to scheduled if a
journalist's question warrants it.

### Sector breadth review (round 2)

The 6.5 promote/drop pass shipped 2026-05-10. A year from now a
similar pass should re-evaluate what's editorially live. Three
groups stayed draft (Honey, Polysilicon, Tropical timber) and
might warrant a second look.

### Derive January from Feb release's `(ytd − monthly)`

The 2026-05-15 Jan+Feb combined-release work closes the prior-year
Jan/Feb gap for 2020-2025 (years where GACC bundled them as a
single cumulative release). 2026 broke the combined pattern by
publishing a separate February release with both Monthly and YTD
columns — meaning January is implicitly available as
`Feb-release YTD − Feb-release Monthly = 1529.1 − 696.6 = 832.5
(100M CNY)` for Germany exports in our case. That's a deterministic
arithmetic identity, not interpolation: the cumulative IS the sum
of Jan + Feb, and Monthly IS Feb alone, so Jan = ytd − monthly by
definition.

Implementation sketch:
- At analyser time (not ingest), in `_gacc_aggregate_per_period_totals`
  (or a sibling helper), for each year where a Feb-only release
  has both monthly and YTD observations AND no separate January
  monthly exists: synthesise a January datapoint with value
  `ytd − monthly`, anchored at Jan 1 of the year. Source the
  derivation from both the YTD obs and the monthly obs (carry
  both obs_ids forward so the finding's provenance file shows the
  arithmetic chain).
- Same honest-accounting principle as the combined-release work:
  no interpolation, no estimation. Just an algebraic identity.
- Likely needs a new caveat code (`jan_derived_from_feb` or
  similar) so journalists can see when a window's January is
  derived rather than directly reported.

Editorial payoff: closes the remaining `partial_window` cases on
the four Lisa-facing bilateral findings; YoYs would shift by
roughly +5pp toward what's probably the true 12mo figure.

Roughly half a day's work. Triggered: any cycle where a journalist
asks why the current-year January is still flagged missing.

### Promote 2020 GACC Jan-Feb release (section=3 → section=4)

The 2020 combined Jan-Feb release was tagged `(3)` rather than
`(4)` by GACC (their own numbering inconsistency that year). Our
parser stored the section_number faithfully so the YoY analysers
skip it. Two options if a story rests on 2020 specifically:
manual override at ingest, or extend `_infer_section_from_description`
to take precedence when the prefix and the description disagree.
~30 minutes of work; deferred until needed.

### Provenance renderers for remaining subkinds

The 2026-05-14/15 arc added detailed provenance templates for
`gacc_bilateral_aggregate_yoy{,_import}`, `hs_group_yoy*` (six
scope/flow variants), and `hs_group_trajectory*` (six scope/flow
variants). What stays as a stub for now:

- `mirror_gap*` — per-country CIF/FOB gap. Pick up if a story rests
  on a specific mirror-gap finding being challenged.
- `partner_share*` — China's share of EU extra-EU imports. Same
  trigger.
- `gacc_aggregate_yoy*` — non-EU bloc YoY (ASEAN, RCEP, etc.).
- `llm_topline*` — narrative lead scaffold. The verification chain
  is upstream (each verified number traces back to a deterministic
  finding); the LLM-prose audit is less pressing than the
  underlying-finding audit.

Each is ~100 lines of renderer + a focused test, modelled on the
shape of the corresponding subkind in `provenance.py`. The CLI flag
`--finding-provenance N` already returns a stub for any of these
that flags "generator pending"; extend `provenance._RENDERERS` when
a journalist asks for one specifically.

## Data sources (deferred until needed)

### 2018 GACC mirror-trade

See [`forward-work-gacc-2018-parser.md`](forward-work-gacc-2018-parser.md).
Title parser handles all 2018 quirks but the section-4 release
pages embed PNG screenshots, not HTML tables. Body parse fails
and the data is in pixels. Options: OCR (~half-day with editorial
risk), hunt for source xlsx, accept gap, lean on Eurostat+HMRC
which already cover 2018.

### Aggregate-label handling for non-EU blocs (ASEAN, RCEP)

Original project requirement. GACC reports trade with these blocs
as labelled aggregates; we don't currently split them into
member-country flows. Pick up if a non-EU-bloc story emerges.

### Chinese-language source URL backfill on `releases`

Most GACC releases have a Chinese-language equivalent at
`www.customs.gov.cn` (vs the English `english.customs.gov.cn`).
The brief constructs the link via `_construct_chinese_source_url`
but we don't store it. Backfill if useful for downstream consumers.

## Future-platform items

### Web UI / hosted deployment

Required for any non-luke-laptop use. AWS-side (Fargate, RDS,
Cognito) per the fuel-finder precedent. Triggers: when a desk
journalist actually wants to use the tool independently.

### Custom Q&A bot (Phase 7+)

See [`forward-work-qa-bot.md`](forward-work-qa-bot.md). Two-tier
scope (ask the findings, ask the underlying data). Tier 1 is ~3-5
days of build. Triggers: web UI exists AND a journalist has a
recurrent question pattern the brief can't answer.

### GoogleSheetsWriter implementation

Pending service-account credentials (was due "next week" as of
2026-05-09). Once available, the sheets-export module wires up
trivially.

## Closed forward-work, kept for reference

These are real options that may be picked up later but aren't on
any near-term path:

- [`forward-work-gacc-2018-parser.md`](forward-work-gacc-2018-parser.md)
  — 2018 image-only blocker (above).
- [`forward-work-qa-bot.md`](forward-work-qa-bot.md) — Phase 7+
  Q&A bot (above).
- [`shock-validation-2026-05-09.md`](shock-validation-2026-05-09.md)
  + companion `.sql` — pre-registered shock validation
  methodology. Living methodology doc, not just a one-off; re-run
  after any major analyser change. §5.4 refreshed 2026-05-11
  using the canonical `product_nc='000TOTAL'` row.
- [`soapbox-validation-2026-05-11.md`](soapbox-validation-2026-05-11.md)
  — peer-comparison validation against Soapbox Trade
  (substack). 50 testable claims pre-registered, ~60% clean concur,
  ~80% directional. The 2026-05-12 A1 re-test (Stage B/C) drove
  the four-step feature pass (Tier 1 hs_groups, briefing-pack
  modularisation, bilateral aggregate analyser, partner_share +
  extra-EU aggregates) recorded in
  [`history.md`](history.md#2026-05-12--soapbox-a1-re-test--four-step-feature-pass).
  Living methodology doc — re-run after any major analyser change.
- [`cif-fob-baselines-2026-05-10.md`](cif-fob-baselines-2026-05-10.md)
  — sourced reference for the OECD ITIC backfill. Reproducibility
  notes for refreshing in a future year.
