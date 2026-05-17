# Docx + Drive upload spike (2026-05-16)

## Why this exists

Lisa-feedback arc: she wants charts on top findings. The constraint
hierarchy that locked the architecture choice:

- `03_Findings.md` stays text-only (NotebookLM feed, per
  `memory/architecture_journalist_surfaces.md` — keep LLM output
  OUTSIDE documents downstream LLM tools will read).
- Lisa reads via Google Docs. Currently Luke does paste-as-markdown
  manually; that workflow has been redundant since we acquired
  python-docx as an option.
- Charts therefore land in a parallel `.docx` alongside the `.md`,
  not inline in the `.md`.

Delivery: rather than producing local files and uploading manually,
we want to push directly into Drive using **OAuth user credentials
on Luke's Guardian Google account** — not service-account, which has
been the blocker for the `GoogleSheetsWriter` forward-work item. The
service-account path is right for hosted/headless deployments;
OAuth-user is right for a single user running locally, which is the
current shape and probably will be for some time.

Spike goal: verify in ~30 min that all three legs of the architecture
work end-to-end before scoping the production module.

## Success criteria

A test bundle round-trips through Drive cleanly:

1. **`.docx` → Google Doc**: a python-docx-authored document with
   H1/H2/H3, paragraphs, one table, and one matplotlib chart converts
   on upload to a native Google Doc that preserves the chart at
   acceptable visual fidelity (chart visible, not a "broken image"
   placeholder; styling preserved well enough that Lisa wouldn't ask
   "what's gone wrong with the formatting?").
2. **`.xlsx` → Google Sheet**: an openpyxl-authored spreadsheet with
   a native chart object converts to a Sheet where the chart is a
   real Sheets chart (editable; not a flat image).
3. **OAuth on Guardian Google account**: the consent flow completes
   without an "admin approval required" block. Refresh token persists;
   second run uses it silently. Scope = `drive.file` only.

If all three pass, the architecture is unblocked. If any fails,
we know which side to redesign before building the production
module.

## Setup (~15 min, one-off)

Reuse the existing Guardian "investigations tools" Google Cloud
project rather than creating a new one. Same semantic home; inherits
any Guardian IT approval / verification already in place; one project
per workstream is the model Google's UX assumes. Meridian gets its
own **OAuth client** within that project (you can have many clients
per project), so its credentials are isolated even though the
consent-screen branding is shared.

All five steps below happen in `console.cloud.google.com` under
**APIs & Services** in the left sidebar — not under the top-level
"create API key / deploy application" tiles on the project home page,
which are the wrong tools.

1. **Confirm you're in the investigations project**, not a different
   one. Project picker at top of console.
2. **Library** → search "Drive API" → confirm it's enabled. Likely
   already is. Docs and Sheets APIs are optional — Drive alone
   supports upload-with-conversion via the `mimeType` request
   parameter, which is how `.docx` becomes a Google Doc and `.xlsx`
   becomes a Google Sheet during upload.
3. **OAuth consent screen** → *read* this page. The consent screen is
   shared across all OAuth clients in the project, so it should
   already exist. Check the registered scopes list for
   `https://www.googleapis.com/auth/drive.file`. If present, do
   nothing here. If absent, adding it may trigger re-verification
   depending on Guardian org policy — pause and check before saving.
4. **Credentials** → Create credentials → OAuth client ID →
   application type **Desktop app** → name "Meridian Export".
   Download the `client_secret.json` it produces → store at
   `~/.config/meridian/client_secret.json`. **Not** in the repo.
5. Install Python deps. Most should already be present from earlier
   work; confirm:
   ```
   pip install google-auth google-auth-oauthlib \
               google-api-python-client \
               python-docx matplotlib openpyxl
   ```

## The spike (~30 min)

Write `scripts/drive_spike.py`:

1. **OAuth flow** using
   `google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file`
   with the `drive.file` scope. On first run, browser opens for
   consent; subsequent runs read the saved token. Token persistence:
   `~/.config/meridian/google-token.json`.

2. **Build a sample `.docx`** with python-docx:
   - Title ("Meridian docx fidelity spike")
   - Two H2s with representative findings-style prose underneath
     (lift a paragraph from a recent `03_Findings.md` for realism).
   - One table — say 5 rows × 4 cols — to test table conversion.
   - One matplotlib chart: simple line chart with 12 monthly points
     and two series. Save to PNG, insert with
     `document.add_picture()`.

3. **Build a sample `.xlsx`** with openpyxl:
   - A worksheet with 12 rows of mock data.
   - A native `LineChart` (openpyxl.chart) anchored to a cell range.

4. **Upload both to Drive** using `files.create` with
   upload-with-conversion. The relevant pattern:
   ```python
   media = MediaFileUpload(
       local_path,
       mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
   )
   service.files().create(
       body={
           'name': 'spike.docx',
           'mimeType': 'application/vnd.google-apps.document',
           'parents': [folder_id],
       },
       media_body=media,
   ).execute()
   ```
   Same shape for `.xlsx` → `application/vnd.google-apps.spreadsheet`.
   Folder name: `meridian-spike-2026-05-16` (create it once and reuse
   on re-run).

5. **Eyeball check** the resulting Doc and Sheet in browser:
   - Headings render as Doc heading styles (not bold-paragraphs).
   - Chart visible and clear at default zoom.
   - Table renders as table.
   - xlsx → Sheet: chart object is editable when clicked.

6. **Record the result at the bottom of this file.** What worked,
   what didn't, screenshots if a fidelity issue surfaced.

## What to do with the result

- **Clean pass**: graduate the approach into a real
  `drive_export.py` module. Add to the briefing-pack pipeline behind
  a flag (`--upload-to-drive`). Decide chart recipes per finding
  subkind. Update `architecture.md` to document the new
  `.docx`-parallel-to-`.md` shape and the Drive delivery path.
- **Fidelity issue in docx → Doc**: try pandoc-generated docx as an
  alternative author path. If still bad, fall back to direct Docs
  API construction (more work; bypass docx round-trip).
- **OAuth blocked by Guardian policy**: pivot to either (a) personal
  Google account writing to a folder shared into Lisa's Drive, or
  (b) escalate to Guardian IT for an approved-apps registration.

## Out of scope for the spike

- Real findings data — mock content is fine, we're testing pipes
  not content.
- Multiple chart shapes — one line chart is enough.
- Production-grade error handling, retries, rate-limit handling.
- Token rotation / scope changes / multi-user.
- Wiring into the actual briefing-pack pipeline — that's the
  follow-up after the spike passes.

## Time budget

30 min for the spike + 15 min for the Cloud Console setup. If it
grows past 90 min total, stop and rescope — something is wrong with
the approach, not with the execution.

## Result

**Legs 1 and 2: PASSED** (2026-05-16, partial spike run via manual
Drive upload — OAuth leg deferred to Monday pending GCP project
access restoration).

**Real-data validation also PASSED** (2026-05-16 late evening):
once the v1 production module landed (commits f2b5c1c, d3f3bfc),
re-tested with a real-data .docx — 10 mover cards, 10 matplotlib
charts at real-data density, uploaded to Drive, opened with Google
Docs. Fidelity holds for actual content at production scale, not
just the synthetic spike sample. The chart resolution + page-setup
defaults (A4, 10mm margins, Mm(190) chart width) need no further
tuning before the v3 OAuth-Drive integration lands.

What was verified:

- **`.docx` → Google Doc conversion preserves everything we need**:
  H1/H2/H3 headings, paragraphs with mixed bold + italic runs,
  numbered lists, bullet lists, 4-column tables with bold header
  rows, embedded matplotlib PNG charts (line + grouped bar), and
  emoji badges (🟡 🔴 🟢). No fidelity issues observed.
- **`.xlsx` → Google Sheets conversion preserves native chart
  objects**: the `LineChart` and `BarChart` round-trip as editable
  Sheets chart objects (not flat images), with titles, axis labels,
  and series legends intact.

What was learned about page setup:

- python-docx defaults to US Letter with ~1-inch margins, which
  carries through to the converted Google Doc. For a Guardian-facing
  document this looks wrong (huge margins, very little usable width).
- **Verified working defaults to bake into the production module**:
  A4 portrait (Mm(297) × Mm(210)), 10mm margins all sides, chart
  embed width `Mm(190)` to fill the new usable area. Set via
  `doc.sections[0].page_height/page_width/{top,bottom,left,right}_margin`.
- Google Docs' "Pageless" mode is a Docs-side toggle that isn't
  expressible in .docx. Can be set manually after conversion via
  File → Page setup → Pageless, or programmatically via the Docs
  API as a post-upload call once OAuth is in place.

Test artefacts: `scripts/drive_spike_local.py` (generator),
`exports/spike-2026-05-16/03_Findings_test.docx`,
`exports/spike-2026-05-16/04_Data_test.xlsx`. Both gitignored
(exports/ is gitignored).

## What remains

- **Leg 3 — OAuth on Guardian Google account**: blocked on GCP
  project access restoration (requested 2026-05-16; expected back
  early week of 2026-05-17). When access returns, follow the Setup
  section above to register Meridian as a new OAuth client within
  the existing investigations-tools project, then write
  `scripts/drive_spike.py` (the full version, ~30 min) that uploads
  the same two test files via the API rather than by hand.
- **Production module design**: after the OAuth leg passes,
  graduate the approach into a real `drive_export.py` module,
  wired into the briefing-pack pipeline behind a `--upload-to-drive`
  flag. Per-subkind chart recipes for the bilateral and hs_group_yoy
  families come next.
