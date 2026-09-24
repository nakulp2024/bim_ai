# IFC → Construction Schedule Generator

Upload an IFC model, profile what is actually in it, choose a **schedule level of detail**, and
get a CPM-calculated construction programme you can edit and export to CSV, Excel, MS Project,
Primavera P6 or JSON. Then track it: baseline the plan, report progress from site, see the
forecast finish move, and play the whole sequence back on the model in 4D.

Every task keeps the list of source `GlobalId`s it was built from, which is what ties the
schedule, the progress and the 3D model together.

```
IFC file
   ↓  parse          ifcopenshell → one flat record per element
   ↓  filter         drop fasteners, openings, tiny parts (config/filters.yaml)
   ↓  group          L1…L5 grouping, optional zone split
   ↓  price          quantity ÷ (rate × crew) → duration (config/rates.yaml)
   ↓  sequence       trade order, vertical logic, zone repetition (config/sequencing.yaml)
   ↓  calculate      forward/backward CPM pass → dates, float, critical path
   ↓  export         CSV · XLSX · MS Project XML · P6 XER · JSON
   ↓  baseline       freeze the plan as the yardstick
   ↓  track          progress from site → forecast CPM → variance and why
   ↓  4D             play planned, actual or variance back on the model
```

---

## Quick start

Two processes: the API on `:8000` and the UI on `:5173`.

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Interactive API docs at <http://localhost:8000/docs>.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to `http://localhost:8000`, so
there is nothing else to configure. Point it somewhere else with
`VITE_API_TARGET=http://host:port npm run dev`.

### Tests

```bash
cd backend && pytest          # 277 tests
cd frontend && npm run lint   # tsc --noEmit
```

The test suite builds its own small IFC model covering the awkward cases — assemblies, missing
quantities, fasteners, orphaned elements, IFC2X3 — so no external fixture file is needed. The
generator lives in `backend/tests/fixtures/sample_ifc.py` and can be run directly:

```bash
python backend/tests/fixtures/sample_ifc.py sample.ifc
```

---

## Level of detail

The level is chosen by the user at run time; nothing about it is hardcoded. Before committing,
`POST /api/projects/{id}/lod-preview` returns the exact task count each level would produce for
*this* model, which is what the picker in the UI displays.

| Level | Grouping key | Example task |
|-------|--------------|--------------|
| **L1** | Site → Building → Storey | `L02 – All works` |
| **L2** | Storey × work package | `L02 – Superstructure` |
| **L3** *(default)* | Storey × IfcClass / PredefinedType | `L02 – Columns` |
| **L4** | Storey × zone × IfcTypeObject or material | `L02 – 200mm Blockwork Solid Walls` |
| **L5** | One task per element | `L02 – Column C-12` |

**Optional secondary zone split.** Any level can be further split by `IfcZone` /
`IfcSpatialZone`, or by a property in any Pset (e.g. `Pset_WallCommon.Sector`). The profile
endpoint reports which zone sources the model actually offers, so the picker only shows real
options. Turning a zone split on also activates the zone-repetition sequencing rule.

**L5 never emits a trivial task.** An element with no measurable quantity, or one below
`min_net_volume_m3 × l5_trivial_volume_factor`, is folded back into its L4 group rather than
becoming a task of its own. The affected tasks are flagged `aggregated_trivial` and explain
themselves in the run report.

---

## Configuration

Four YAML files in `backend/config/` hold every rule. None of this logic lives in Python.

| File | What it controls |
|------|------------------|
| `filters.yaml` | Which elements are noise: excluded classes, assembly collapsing, size thresholds, name patterns |
| `work_packages.yaml` | How elements map to Substructure / Superstructure / Envelope / MEP / Interior / Finishes |
| `rates.yaml` | The productivity rate library that turns quantities into durations |
| `sequencing.yaml` | Trade order, within-storey links, vertical logic, zone repetition, the default calendar |

To override them, copy the directory, edit your copy, and point the app at it:

```bash
IFCSCHED_CONFIG_DIR=/path/to/my-config uvicorn app.main:app
```

Files missing from your directory fall back to the packaged defaults, so you can override just
`rates.yaml` and inherit the rest. `GET /api/config` returns the merged, active configuration.

### Noise filtering

Nuts and bolts never become tasks. `filters.yaml` removes, and the run report explains:

- **Excluded classes** — `IfcMechanicalFastener`, `IfcFastener`, `IfcDiscreteAccessory`,
  `IfcBuildingElementPart`, `IfcOpeningElement`, `IfcVirtualElement`, `IfcAnnotation`, `IfcGrid`,
  `IfcSpace`. Matching walks the full IFC class hierarchy, so excluding a supertype covers its
  subtypes. `schedulable_overrides` can force any class back in or out.
- **Assembly collapsing** — `IfcElementAssembly` children fold into the parent, which inherits the
  summed quantities of its children.
- **Size threshold** — elements below `min_net_volume_m3` *and* `min_bbox_diagonal_m` roll up into
  their parent group. An element with no measurement at all is never dropped by size (nothing
  proves it is trivial), and `never_filter_classes` protects small-but-real items like doors.
- **Name patterns** — regexes against Name / ObjectType / type name.

### Rate library and the fallback chain

```
duration_days = ceil(quantity / (output_per_crew_day × crew))   floored at min_duration_days
```

Rates are looked up in order, and the link that matched sets the task's confidence:

| Order | Match | Confidence |
|-------|-------|------------|
| 1 | class + predefined type + material pattern | `high` |
| 2 | class only | `medium` |
| 3 | `default` | `low` |
| 4 | `count_fallback` (rule's unit has no quantity) | `low` |

Confidence is capped at `medium` when the quantities were derived from geometry rather than read
from `Qto_*BaseQuantities`, and forced to `low` when there is no measurement at all.

Rates are editable in the UI and persisted **per project** — the packaged `rates.yaml` is never
modified. Saving repricing every task except those whose duration you edited by hand.

### Sequencing

Every relationship traces back to a rule, and the run report breaks links down by origin.

- **`within_storey`** — explicit links between work packages in the same storey/zone bucket, with
  type (FS/SS/FF/SF) and lag. Falls back to chaining `trade_order` with FS+0 if left empty.
- **`vertical`** — storey N's structure finishes before storey N+1's starts, ordered by elevation.
  Driving packages are treated as one train per storey, so a ground floor whose structure is
  Substructure still gates the floor above whose structure is Superstructure.
- **`zone_repetition`** — staggers the same package across zones instead of running them in
  parallel, when a zone split is active.
- **`within_bucket`** — orders the several tasks that share one bucket, using `class_order`.

### Calendar

Configurable work week (default Mon–Fri), start date and holiday list. CPM runs in integer
working-day offsets; the calendar converts them to dates at the end. Changing the calendar on an
existing schedule reschedules it without regenerating.

---

## Data extracted per element

`GlobalId`, IfcClass and the full class hierarchy, PredefinedType, Name, ObjectType, IfcTypeObject
name, material (single / layered / profile / constituent), spatial container via
`IfcRelContainedInSpatialStructure`, storey elevation, assembly parent, zone membership,
classification references (Uniclass / OmniClass / assembly codes), property sets, and quantities
from `Qto_*BaseQuantities` — all converted to SI using the file's own unit scale.

**Missing base quantities** fall back to `ifcopenshell.geom`: bounding box dimensions and mesh
volume, with the task flagged `quantity_source: derived`. Derivation is capped at
`IFCSCHED_MAX_DERIVED_GEOMETRY` elements (default 20 000) so a huge model does not stall, and
elements with no geometric representation are recorded as unmeasured rather than counted as
failures.

**Nothing crashes on a bad IFC.** Every extraction step is individually guarded — a broken
relationship or malformed representation degrades that one element and is recorded in the report.
A file that cannot be opened at all returns an empty result plus the reason.

---

## The run report

Written per run and available at `GET /api/projects/{id}/run-report` (and as a sheet in the XLSX
export). It answers: what was read, what was thrown away and why, what was built.

- **Parse** — schema, products seen, elements read, quantities by source, quantity coverage %,
  geometry failures, errors and warnings
- **Filter** — elements in / kept / removed, broken down by reason *and* by IFC class, with example
  GlobalIds and the total quantity that was rolled up rather than dropped
- **Grouping** — level, zone split, task count, elements represented, trivial groups aggregated
- **Durations** — confidence split, which link of the fallback chain each task used, coverage %
- **Sequencing** — link count by originating rule
- **CPM** — project duration, finish date, critical task count, plus any cycles broken or links
  dropped

---

## Exports

| Format | Notes |
|--------|-------|
| **CSV** | One row per task, predecessors as `ID FS+2`, GlobalIds semicolon-separated |
| **XLSX** | Formatted schedule sheet with critical tasks highlighted, plus a run-report sheet |
| **MS Project XML** | MSPDI with calendar, WBS outline, typed predecessor links and lags; GlobalIds ride in the task Notes field |
| **Primavera P6 XER** | `PROJECT`, `CALENDAR`, `PROJWBS`, `TASK`, `TASKPRED` tables, plus an `IFCSOURCE` table carrying the GlobalIds |
| **JSON** | Lossless: tasks, logic, quantities, confidence, float, and `source_global_ids` for 4D linking |

Once a schedule is tracked (it has a baseline or any progress), every format also carries
progress in its own native form — "baseline in, updates out":

| Format | Progress |
|--------|----------|
| **CSV / XLSX** | Status, % complete, quantity placed, actual and baseline dates, forecast finish, slip, flag, delay cause. XLSX adds a Progress sheet and highlights late rows |
| **MS Project XML** | `ActualStart`, `ActualFinish`, `PercentComplete`, `RemainingDuration`, and the baseline as Baseline 0 |
| **Primavera P6 XER** | Status (`TK_NotStart` / `TK_Active` / `TK_Complete`), physical % complete, actual dates, remaining duration, with the baseline as the target dates |
| **JSON** | A `progress` block per task, plus the project summary, for replaying what actually happened |

An untracked schedule exports exactly as it did before tracking existed.

---

## Progress tracking

The plan says what should happen; progress says what did. Three things drive it:

- **Baseline** — a frozen copy of the plan, so later edits to the plan do not move the yardstick.
  Several can exist per project; exactly one is current. Without one, variance is measured
  against the live plan and the UI says so.
- **Data date** — the date progress is reported as of. Following P6's convention, it is the
  first day of *remaining* work.
- **Progress reports** — percent complete, quantity placed, actual start and finish, per task.

### Reports merge; they never overwrite

Field reporting is partial. Someone reports "started on the 2nd"; a week later, "68 m³ placed".
The second report must not erase the first. Reports are append-only, and a task's current state
is the fold of its reports in date order: each later non-blank value overrides an earlier one, a
blank never erases one. The full history is kept at `/progress/history`.

When data is missing, the gap is filled by a stated rule — quantity derives percent or the
reverse, a completed task without an actual finish is assumed to have finished the working day
before the data date, and so on — and every assumption is recorded on the task rather than
applied silently. If a reported percent and a quantity-derived one disagree by more than 15
points, the reported percent is kept (it can account for work a quantity misses, like formwork
before a pour) and the disagreement is flagged.

### The forecast

A second CPM pass that honours what actually happened:

| State | How it is scheduled |
|-------|---------------------|
| Complete | Pinned at its actual dates. No float, and never on the critical path — finished work cannot drive the finish date |
| In progress | Pinned at its actual start; finishes after its remaining duration, counted from the data date |
| Not started | Cannot start before the data date, whatever its logic says |

Remaining duration is `ceil(duration × (1 − percent))`, but never less than one day while a task
is still in progress, however high its percent.

### Variance, and why

Every task gets its start and finish slip against the baseline in working days, planned versus
actual percent, and a flag: `complete`, `ahead`, `on_track`, `behind` or `not_started`.

"Behind" alone does not tell a planner what to do, so behind tasks also carry a **delay cause**:

| Cause | Meaning |
|-------|---------|
| `late_start` | It should have started by the data date and has not |
| `slow_progress` | It started, but is less complete than the plan says it should be by now |
| `predecessor_delay` | It is not due yet; it is only late because something before it slipped |

The project summary rolls this up: duration-weighted planned and actual percent complete, a
schedule performance index (actual ÷ planned; below 1 means behind), forecast versus reference
finish, quantity placed per unit, and the critical tasks that are behind — the ones actually
driving the finish date.

---

## 4D

The **4D** tab plays the schedule back on the model: work not yet started is ghosted, work in
progress is amber (red if it is critical), and built work takes its work package's colour.

| View | Driven by |
|------|-----------|
| **Planned** | The current plan's dates |
| **Actual** | What happened up to the data date, then the forecast |
| **Variance** | Actual and forecast timing, coloured by how far each task is off the baseline |

It opens on the plan until someone has reported progress: before that, "actual" is just the plan
pushed to today, which would hide the real start. Hover an element to see its task; click one
to select that task everywhere.

**Geometry** is built on demand the first time the tab opens, as a background job, and cached
per project. ifcopenshell tessellates every renderable product into two merged buffers —
positions and triangle indices — plus a manifest recording which slice belongs to which
GlobalId. The browser draws the whole model from those shared buffers and recolours an element
by writing into its slice, which is what keeps playback cheap.

A few things worth knowing:

- **Axes and origin are converted server-side.** IFC is Z-up and three.js is Y-up. And real
  models are often georeferenced far from the origin, where float32 cannot hold millimetres and
  vertices visibly jitter, so the model is re-centred on its footprint and the offset recorded.
- **Spaces, openings, annotation, grids, virtual elements and site terrain are not rendered.**
  They have geometry but they are not work.
- **Assembly parts resolve through their parent.** They are collapsed into the assembly before
  scheduling, so they appear in no task themselves; without this they would render as
  unscheduled context. Anything else unresolved — noise the filter removed — renders as neutral
  context.
- **Solid and ghosted work are drawn as two meshes over the same buffers.** A single mesh with
  per-vertex transparency cannot ghost future work correctly: with depth writes on, a
  translucent wall drawn first hides the built columns behind it.
- **There is a triangle budget** (3 million by default). Anything over it is skipped and the
  viewer says so rather than silently dropping it.
- **Normals are computed in the browser**, not shipped: a third less to download.

three.js is only loaded when the 4D tab is opened, so it costs nothing on the rest of the app.

---

## Optional LLM layer

**Off by default, and the core pipeline is fully deterministic without it.** Nothing in
`app/schedule/` imports `app/llm/` at module scope; it is loaded lazily and only when enabled, and
any failure inside it is caught and logged rather than propagated.

```bash
export IFCSCHED_LLM_ENABLED=true
export ANTHROPIC_API_KEY=sk-...
pip install anthropic
```

It can then (a) rename tasks more naturally, (b) classify unrecognised
`IfcBuildingElementProxy` / ObjectType strings into work packages, and (c) suggest missing logic
links. Suggested links are **returned, not applied** — the calculated programme only ever contains
links you or the rules put there. Anything the layer changes is recorded under the task's
`llm_notes` alongside the original value.

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `IFCSCHED_CONFIG_DIR` | `backend/config` | Override directory for the YAML rule files |
| `IFCSCHED_DATA_DIR` | `./data` | Uploads, element stores and the SQLite database |
| `IFCSCHED_DATABASE_URL` | `sqlite:///<data>/ifcsched.db` | SQLAlchemy URL |
| `IFCSCHED_MAX_UPLOAD_MB` | `1024` | Upload size limit |
| `IFCSCHED_MAX_DERIVED_GEOMETRY` | `20000` | Cap on geometry-derived quantities per run |
| `IFCSCHED_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `IFCSCHED_LLM_ENABLED` | `false` | Enables the optional LLM layer |
| `IFCSCHED_LLM_MODEL` | `claude-sonnet-5` | Model used by the LLM layer |
| `ANTHROPIC_API_KEY` | — | Required when the LLM layer is enabled |

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects` | Create a project |
| `POST` | `/api/projects/{id}/upload` | Upload an IFC; returns a `job_id` |
| `GET` | `/api/jobs/{job_id}` | Poll background-job progress |
| `GET` | `/api/projects/{id}/profile` | Model profile + parse report |
| `POST` | `/api/projects/{id}/lod-preview` | Predicted task count for every level |
| `POST` | `/api/projects/{id}/schedule` | Generate; returns a `job_id` |
| `GET` | `/api/projects/{id}/schedule` | Tasks, links, calendar and report |
| `PATCH` | `/api/projects/{id}/tasks/{task_id}` | Rename, change duration/crew, re-link |
| `DELETE` | `/api/projects/{id}/tasks/{task_id}` | Delete a task and its links |
| `POST`/`DELETE` | `/api/projects/{id}/links` | Add or remove a single link |
| `PUT` | `/api/projects/{id}/calendar` | Change start date, work week or holidays |
| `GET`/`PUT` | `/api/projects/{id}/rates` | Read or override the rate library |
| `GET` | `/api/projects/{id}/export/{fmt}` | `csv` · `xlsx` · `mspdi` · `xer` · `json` |
| `GET` | `/api/projects/{id}/run-report` | The per-run report on its own |
| `GET`/`POST` | `/api/projects/{id}/baselines` | List baselines, or freeze the current plan as a new one |
| `POST` | `/api/projects/{id}/baselines/{bid}/activate` | Make an earlier baseline current |
| `PUT` | `/api/projects/{id}/data-date` | Set the date progress is reported as of |
| `GET` | `/api/projects/{id}/progress` | Every task's state, forecast and variance, plus the summary |
| `POST` | `/api/projects/{id}/progress` | Record a batch of task updates; returns the recalculated view |
| `GET` | `/api/projects/{id}/progress/history` | The report log, optionally for one task |
| `DELETE` | `/api/projects/{id}/progress/{task_id}` | Clear every report for one task |
| `POST` | `/api/projects/{id}/geometry` | Build the 4D geometry in the background (cached; `?force=true` rebuilds) |
| `GET` | `/api/projects/{id}/geometry` | The geometry manifest |
| `GET` | `/api/projects/{id}/geometry/buffer` | The packed vertex and index buffer |
| `GET` | `/api/config` | The merged, active configuration |

Long parses run as background jobs on a thread pool, with progress written to the database on
every step so `/api/jobs/{id}` works across workers and survives a client reconnect. Any edit —
duration, link, calendar, rate — re-runs CPM and returns the whole recalculated schedule.

---

## Layout

```
backend/
  app/
    ifc/          parser (IFC → records) · model · profile · geometry (meshes for 4D)
    schedule/     filtering · lod · durations · sequencing · cpm · calendar · pipeline · progress
    exports/      tabular (CSV/XLSX) · msproject · p6 · jsonpkg
    llm/          optional, lazily loaded, off by default
    routes/       projects · schedule · rates · progress · geometry · exports · jobs · config
    db.py         SQLAlchemy models; element frames are stored as gzipped JSON on disk
    jobs.py       thread-pool job manager with a pollable progress endpoint
  config/         filters · work_packages · rates · sequencing  (all user-overridable)
  tests/          277 tests, plus the sample-IFC generator
frontend/
  src/
    steps/        UploadStep · ProfileStep · LodPicker
    components/   GanttChart · FourDPlayer · ProgressPanel · TaskTable · RatesEditor ·
                  RunReport · RelinkDialog · ExportBar
    components/ui shadcn/ui-style primitives (vendored, built on Radix)
    lib/          api client, shared types, helpers,
                  scene (three.js renderer) · fourd (element → task → colour at a date)
```

Existing databases pick up new columns automatically on startup — `create_all()` never alters
an existing table, so the app adds any missing nullable columns itself. Anything beyond an
additive column would need a real migration.

The UI components follow shadcn/ui conventions and are vendored into the repo rather than pulled
in by the CLI, so `npm install` is all that is needed to build.
