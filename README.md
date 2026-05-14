# BIM AI Platform

A web app that adds an AI-driven 4D animation layer on top of [Speckle](https://speckle.systems/). Users connect their existing Speckle projects (Revit / Rhino / ArchiCAD / IFC via Speckle's native connectors), upload a construction schedule, and Claude generates a timeline that drives the Speckle viewer.

## Status: M2 — Schedule upload + AI column mapping

Adds the first AI layer on top of M1:

- **Schedule upload** (CSV / Excel) bound to a Speckle version, parsed with pandas.
- **Speckle catalog summary** built server-side via `specklepy` (counts per category and storey, sample elements with `applicationId` / `family` / `type`).
- **Claude column mapping**: a Celery worker calls `claude-sonnet-4-6` with `messages.parse()` and a Pydantic schema to propose how columns map to canonical roles + a join strategy.
- **Mapping confirmation UI**: editable role table with confidence badge; saves a confirmed mapping back to Postgres.

M1 features still work: Speckle OAuth, project / model / version browsing, embedded `@speckle/viewer`.

## Architecture

```
frontend/   Vite + React + TS + react-router + @speckle/viewer
backend/    FastAPI + httpx + SQLAlchemy (asyncpg)
            ├── Celery worker (sync SQLAlchemy + psycopg2 + specklepy + anthropic)
            └── stores: users, schedule_uploads, mapping_proposals, jobs
docker-compose.yml
            ├── self-hosted Speckle (server + postgres + redis + minio)
            └── our app (api + worker + postgres + redis + frontend)
```

Backend boundary discipline: we never copy Speckle model data into our DB. The
only Speckle-derived data we persist is the per-user OAuth token, the Speckle
catalog *summary* used for one mapping pass (counts and a few sample elements),
and pointers back to Speckle by project / model / version / applicationId.

## Run

### 1. Boot the stack

```bash
docker compose up --build
```

Wait for Speckle's first boot — the server image migrates its DB and creates
the MinIO bucket. Healthy when:

- `http://localhost:3000` shows the Speckle login page
- `http://localhost:8000/health` returns `{"status":"ok"}`

### 2. Register an OAuth app in Speckle

This is the one manual step — Speckle requires a logged-in user to create
OAuth apps:

1. Open `http://localhost:3000` and sign up (any email; the local server
   doesn't actually deliver mail unless you wire one up).
2. Go to **Profile → Developer Settings → Applications → New application**.
3. Fill in:
   - **Name**: `BIM AI (dev)`
   - **Redirect URL**: `http://localhost:8000/auth/speckle/callback`
   - **Scopes**: at minimum `streams:read`, `users:read`, `profile:read`,
     `streams:write` (the last only if you later want to write filters back).
4. Copy the **App ID** and **App Secret** Speckle gives you.
5. Create `.env` at the repo root from `.env.example` and paste them in:
   ```
   SPECKLE_APP_ID=...
   SPECKLE_APP_SECRET=...
   ```
6. Restart the backend: `docker compose restart app-backend`.

### 3. Push a model into Speckle

The OAuth flow works on an empty Speckle account, but the viewer needs
something to render. Quickest paths:

- Use a Speckle **connector** (Revit, Rhino, etc.) from a desktop app pointing
  at `http://localhost:3000`, or
- Drag an `.ifc` file onto a Speckle project — the bundled
  `speckle-fileimport-service` is **not** included in this minimal compose;
  enable it by adding `speckle/speckle-fileimport-service` if you want
  drag-and-drop IFC uploads, or
- Use the public sample data: clone an existing public project from
  speckle.xyz with the Speckle CLI.

### 4. Use the app

Open `http://localhost:5173` and **Sign in with Speckle**. You should land on
your project list, drill into a model and version, and see the viewer load it.

## Endpoints

| Path | Notes |
|---|---|
| `GET  /auth/speckle/start` | Begin OAuth (redirects to Speckle) |
| `GET  /auth/speckle/callback` | OAuth return, mints app JWT, redirects to SPA |
| `GET  /me` | Current user, including their Speckle token for the viewer |
| `GET  /speckle/projects` | GraphQL passthrough — `activeUser.projects` |
| `GET  /speckle/projects/{id}/models` | `project.models` |
| `GET  /speckle/projects/{id}/models/{mid}/versions` | `model.versions` |
| `POST /schedules` (multipart) | Upload schedule, queue mapping job |
| `GET  /schedules` | List the user's uploaded schedules (optionally filter by `speckle_version_id`) |
| `GET  /schedules/{id}/mapping` | Latest mapping proposal + catalog summary |
| `POST /schedules/{id}/mapping/confirm` | Persist the (possibly edited) confirmed mapping |
| `GET  /jobs/{id}` | Job status for client polling |

## M2 setup

In addition to the Speckle OAuth app from M1, M2 needs an Anthropic API key.
Add it to `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
# CLAUDE_MODEL=claude-sonnet-4-6   # optional override
```

Restart the stack so the worker picks up the new key:

```bash
docker compose up -d --build app-backend app-worker
```

## Using the schedule flow

1. Sign in, drill into a project → model → version, click **Schedule →** in the
   viewer top bar.
2. Upload an Excel or CSV schedule.
3. The page polls the job until it's ready (typically 5–20s once Claude
   responds). You'll see a proposed mapping with a confidence badge.
4. Edit roles / join strategy / Speckle property as needed, then **Save mapping**.

The mapping is persisted against the (user, speckle_version_id) tuple. M3 will
consume it to resolve schedule rows to Speckle object IDs.

## Known M2 compromises

- The Speckle access token is handed to the SPA via `/me`. A future milestone
  should mint short-lived, narrowly-scoped tokens.
- Speckle tokens and uploaded schedules are stored unencrypted. Wrap with
  `cryptography` Fernet before this leaves dev.
- Catalog traversal materialises the whole referenced object in worker memory.
  For models above ~50k elements, switch to a streamed traversal or pre-cache.
- No row-to-element resolution yet — that's M3.
- The Dockerfiles run dev servers (`uvicorn --reload` not enabled, but `vite
  dev`). Build production images separately when deploying.
- The compose file ships the minimum Speckle services. Preview thumbnails,
  webhooks, and the dedicated file-import service are omitted; add the
  corresponding `speckle/*` images if you want them.

## What's next (M3)

Deterministic row-to-element resolution by the chosen join strategy, surfaced
as a "X / Y rows matched" report with samples of unmatched rows. Then M4 starts
the animation generation pass.
