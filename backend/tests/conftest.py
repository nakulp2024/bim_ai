"""Shared fixtures. The sample IFC is built once per session and reused."""

from __future__ import annotations

import os
import sys
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
