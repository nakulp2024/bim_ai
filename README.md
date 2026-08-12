# IFC → Construction Schedule Generator

Upload an IFC model, profile what is actually in it, choose a **schedule level of detail**, and
get a CPM-calculated construction programme you can edit and export to CSV, Excel, MS Project,
Primavera P6 or JSON.

Every task keeps the list of source `GlobalId`s it was built from, so the output can drive 4D
linking later.

```
IFC file
   ↓  parse          ifcopenshell → one flat record per element
   ↓  filter         drop fasteners, openings, tiny parts (config/filters.yaml)
   ↓  group          L1…L5 grouping, optional zone split
   ↓  price          quantity ÷ (rate × crew) → duration (config/rates.yaml)
   ↓  sequence       trade order, vertical logic, zone repetition (config/sequencing.yaml)
   ↓  calculate      forward/backward CPM pass → dates, float, critical path
   ↓  export         CSV · XLSX · MS Project XML · P6 XER · JSON
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
cd backend && pytest          # 203 tests
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
| `GET` | `/api/config` | The merged, active configuration |

Long parses run as background jobs on a thread pool, with progress written to the database on
every step so `/api/jobs/{id}` works across workers and survives a client reconnect. Any edit —
duration, link, calendar, rate — re-runs CPM and returns the whole recalculated schedule.

---

## Layout

```
backend/
  app/
    ifc/          parser.py (IFC → records), model.py (record shape), profile.py
    schedule/     filtering · lod · durations · sequencing · cpm · calendar · pipeline
    exports/      tabular (CSV/XLSX) · msproject · p6 · jsonpkg
    llm/          optional, lazily loaded, off by default
    routes/       projects · schedule · rates · exports · jobs · config
    db.py         SQLAlchemy models; element frames are stored as gzipped JSON on disk
    jobs.py       thread-pool job manager with a pollable progress endpoint
  config/         filters · work_packages · rates · sequencing  (all user-overridable)
  tests/          203 tests, plus the sample-IFC generator
frontend/
  src/
    steps/        UploadStep · ProfileStep · LodPicker
    components/   GanttChart · TaskTable · RatesEditor · RunReport · RelinkDialog · ExportBar
    components/ui shadcn/ui-style primitives (vendored, built on Radix)
    lib/          api client, shared types, helpers
```

The UI components follow shadcn/ui conventions and are vendored into the repo rather than pulled
in by the CLI, so `npm install` is all that is needed to build.
