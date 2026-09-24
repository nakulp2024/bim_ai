"""Shared fixtures. The sample IFC is built once per session and reused."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="session")
def sample_ifc_path(tmp_path_factory) -> Path:
    from tests.fixtures.sample_ifc import write_sample_ifc

    target = tmp_path_factory.mktemp("ifc") / "sample.ifc"
    return write_sample_ifc(target)


@pytest.fixture(scope="session")
def parsed(sample_ifc_path):
    from app.ifc.parser import parse_ifc

    return parse_ifc(sample_ifc_path)


@pytest.fixture(scope="session")
def elements(parsed):
    """The raw element frame, straight out of the parser."""
    from app.ifc.model import records_to_frame

    records, _report = parsed
    return records_to_frame(records)


@pytest.fixture(scope="session")
def parse_report(parsed):
    _records, report = parsed
    return report


@pytest.fixture
def classified(elements):
    """Element frame with the work_package column populated."""
    from app.schedule.work_packages import WorkPackageClassifier

    frame = elements.copy()
    frame["work_package"] = WorkPackageClassifier().classify_frame(frame)
    return frame


@pytest.fixture
def filtered(classified):
    """Element frame after noise filtering, plus the filter report."""
    from app.schedule.filtering import ElementFilter

    return ElementFilter().apply(classified)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """A TestClient bound to an isolated database and data directory."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("IFCSCHED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("IFCSCHED_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("IFCSCHED_LLM_ENABLED", "false")

    from app import config as config_module
    from app import db as db_module

    config_module.get_settings.cache_clear()
    db_module.reset_engine()

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client

    db_module.reset_engine()
    config_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_settings_cache():
    """Keep env-driven settings from leaking between tests."""
    yield
    from app import config as config_module

    config_module.get_settings.cache_clear()
    os.environ.pop("IFCSCHED_LLM_ENABLED", None)


# --- API flow fixtures, shared by every API test module ---------------------


def wait_for_job(client, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


@pytest.fixture
def project(api_client, sample_ifc_path):
    """A project with the sample IFC uploaded and parsed."""
    response = api_client.post("/api/projects", json={"name": "Sample Tower"})
    assert response.status_code == 200
    project_id = response.json()["id"]

    with open(sample_ifc_path, "rb") as handle:
        response = api_client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("sample.ifc", handle, "application/octet-stream")},
        )
    assert response.status_code == 200
    job = wait_for_job(api_client, response.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    return project_id


@pytest.fixture
def scheduled(api_client, project):
    response = api_client.post(
        f"/api/projects/{project}/schedule",
        json={"level": "L3", "start_date": "2026-09-01"},
    )
    assert response.status_code == 200
    job = wait_for_job(api_client, response.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    return project
