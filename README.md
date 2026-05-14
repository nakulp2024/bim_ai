# BIM AI Platform

A web app that adds an AI-driven 4D animation layer on top of [Speckle](https://speckle.systems/). Users connect their existing Speckle projects (Revit / Rhino / ArchiCAD / IFC via Speckle's native connectors), upload a construction schedule, and Claude generates a timeline that drives the Speckle viewer.

## Status: M1 — Speckle plumbing

End-to-end slice of the Speckle integration only — no schedule ingest or AI yet:

- Sign in with a self-hosted Speckle instance via OAuth.
- List your Speckle projects, models, and versions through the GraphQL API.
- Embed `@speckle/viewer` and load a chosen version.

## Architecture

```
frontend/   Vite + React + TS + react-router + @speckle/viewer
backend/    FastAPI + httpx + SQLAlchemy (asyncpg)
            └── stores: users (id, speckle_user_id, tokens)
docker-compose.yml
            ├── self-hosted Speckle (server + postgres + redis + minio)
            └── our app (backend + frontend + postgres)
```

Backend boundary discipline: we never copy Speckle model data into our DB. The
only Speckle-derived data we persist is the per-user OAuth token (encrypted at
rest is a TODO).

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

## Known M1 compromises

- The Speckle access token is handed to the SPA via `/me`. M2 should mint
  short-lived, narrowly-scoped tokens or proxy viewer requests through the
  backend.
- Speckle tokens are stored unencrypted in Postgres. Wrap with `cryptography`
  Fernet before this leaves dev.
- The Dockerfiles run the dev servers (`uvicorn --reload`, `vite dev`). Build
  production images separately when deploying.
- The compose file ships the minimum Speckle services. Preview thumbnails,
  webhooks, and the dedicated file-import service are omitted; add the
  corresponding `speckle/*` images if you want them.
- If Speckle's image fails to start, check `docker compose logs speckle-server`
  — its env-var contract evolves between versions. The canonical reference is
  https://github.com/specklesystems/speckle-server/blob/main/docker-compose.yml.

## What's next (M2)

Schedule upload (Excel/CSV → pandas → canonical schema), Claude column-mapping
with the `submit_mapping` tool, mapping confirmation UI. Stays well clear of
the viewer until M3.
