# BIM AI Platform

A web app that adds an AI-driven 4D animation layer on top of [Speckle](https://speckle.systems/). Users connect their existing Speckle projects (Revit / Rhino / ArchiCAD / IFC via Speckle's native connectors), upload a construction schedule, and Claude generates a timeline that drives the Speckle viewer.

## Status: M5 — End-to-end demo

The full pipeline works:

1. **M1** — sign in via Speckle OAuth, browse projects → models → versions, view a model in `@speckle/viewer`.
2. **M2** — upload a CSV / Excel schedule. A Celery worker fetches the Speckle catalog with `specklepy`, calls `claude-sonnet-4-6` via `messages.parse()` for column mapping, and shows you an editable proposal with a confidence badge.
3. **M3** — saving the mapping kicks off a deterministic SQL join (by `applicationId`, `category_and_level`, or `type_and_level`) against an `element_index` table built during M2; you see how many tasks and elements matched.
4. **M4** — "Generate animation" runs Claude again to cluster tasks into 3-6 named, color-coded phases. The browser plays the animation through `FilteringExtension`, with play/pause/scrub/speed/legend.
5. **M5** — job updates stream over SSE (Redis pub/sub from the worker), share-link button on the player, error states surfaced inline.

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
| `GET  /jobs/{id}/events` | Server-Sent Events stream of job state changes (token via `?token=`) |
| `GET  /schedules/{id}/resolution` | Counts of resolved task→element links |
| `POST /schedules/{id}/animation` | Queue a `generate_animation` job |
| `GET  /schedules/{id}/animation` | Latest animation script + task→Speckle index |

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

## What's next (post-MVP)

- `name_fuzzy` and `wbs_pattern` join strategies (currently no-ops in the
  resolver — surface as 0 matches).
- Per-row LLM fallback for unresolved rows (batched 50 at a time as the
  architecture doc suggests).
- Multiple activity types beyond `construct` (demolish, temporary works) with
  distinct visual treatments.
- Re-versioning: when a Speckle version changes, re-stitch animations using
  `application_id` so the timeline survives model edits.
- Snapshot / MP4 export of the timeline.
- Encrypt Speckle tokens at rest (`cryptography` Fernet); mint short-lived,
  scoped Speckle tokens for the viewer instead of handing the user's token to
  the SPA.
- Replace the `?token=` query param on the SSE endpoint with a cookie-bound
  flow so JWTs aren't logged in proxy access logs.
