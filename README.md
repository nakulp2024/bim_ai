# BIM AI Platform

A web-based BIM platform that ingests IFC and schedule data, uses an LLM to generate 4D construction animations, and plays them back in the browser.

## Status: M1 — Static Viewer

This milestone delivers an end-to-end slice of the parsing + rendering pipeline:

- Upload an IFC file via the browser
- Backend parses it with `ifcopenshell` and converts it to glTF via `IfcConvert`
- The browser loads the glTF in a three.js viewer with orbit controls
- An element sidebar lets you filter by type / name / storey and inspect property sets
- Clicking a mesh in the viewer or a row in the sidebar highlights the selected element (matched by IFC GUID)

No queue, no DB, no auth yet — files live on disk under `BIM_DATA_DIR` (default `/tmp/bim_ai_data`).

## Architecture

```
frontend/   Vite + React + TypeScript + three.js + zustand
backend/    FastAPI + ifcopenshell + IfcConvert
```

The frontend proxies `/api/*` to the backend so all browser requests are same-origin.

### Key data flow

1. `POST /projects` → `{project_id}`
2. `POST /projects/{id}/ifc` (multipart) — synchronous: parses elements, runs `IfcConvert --use-element-guids` to produce a `.glb`
3. `GET  /projects/{id}/model.glb` — binary glTF
4. `GET  /projects/{id}/elements` — JSON catalog of `IfcProduct` instances with property sets

The IFC GlobalId is the join key end-to-end: it survives parsing → glTF node names → three.js mesh names → selection state.

## Run with Docker (recommended)

```bash
docker compose up --build
# frontend: http://localhost:5173
# backend:  http://localhost:8000/health
```

## Run locally without Docker

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
# IfcConvert is bundled with the ifcopenshell wheel; symlink it onto PATH:
python -c "import ifcopenshell, glob, os; \
  print(glob.glob(os.path.dirname(ifcopenshell.__file__)+'/**/IfcConvert*', recursive=True))"
# put the binary on PATH, e.g.:
# sudo ln -s /path/to/IfcConvert /usr/local/bin/IfcConvert

uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

## Caveats

- `IfcConvert` is invoked synchronously, so large IFC files will tie up the request. M2 moves this onto a Celery worker.
- The backend serves files with permissive CORS — intended for local dev only.
- Property sets with non-JSON-serialisable values are silently coerced to strings.

## What's next (M2)

Async processing with Celery + Redis, progress events over SSE, Postgres persistence of element catalogs.
