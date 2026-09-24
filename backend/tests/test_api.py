"""API: the full upload -> profile -> LOD -> schedule -> edit -> export flow."""

from __future__ import annotations

import pytest

from tests.conftest import wait_for_job

# --- basics ---------------------------------------------------------------


def test_health(api_client):
    payload = api_client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["llm_enabled"] is False


def test_project_crud(api_client):
    created = api_client.post("/api/projects", json={"name": "Tower B"}).json()
    assert created["name"] == "Tower B"
    assert created["status"] == "created"

    listed = api_client.get("/api/projects").json()["projects"]
    assert created["id"] in [p["id"] for p in listed]

    assert api_client.get(f"/api/projects/{created['id']}").json()["name"] == "Tower B"
    assert api_client.delete(f"/api/projects/{created['id']}").status_code == 200
    assert api_client.get(f"/api/projects/{created['id']}").status_code == 404


def test_unknown_project_returns_404(api_client):
    assert api_client.get("/api/projects/9999").status_code == 404
    assert api_client.get("/api/projects/9999/schedule").status_code == 404


# --- upload and parse -----------------------------------------------------


def test_upload_parses_and_profiles(api_client, project):
    payload = api_client.get(f"/api/projects/{project}/profile").json()
    assert payload["project"]["status"] == "parsed"
    assert payload["project"]["ifc_schema"] == "IFC4"
    assert payload["project"]["element_count"] > 100

    profile = payload["profile"]
    assert profile["element_count"] == payload["project"]["element_count"]
    classes = {entry["key"] for entry in profile["by_class"]}
    assert {"IfcColumn", "IfcWall", "IfcSlab"} <= classes
    assert [s["name"] for s in profile["storeys"]][:3] == ["L00", "L01", "L02"]
    assert profile["storeys"][0]["elevation"] == 0.0
    assert {entry["key"] for entry in profile["by_discipline"]} <= {
        "Substructure", "Superstructure", "Envelope", "MEP", "Interior", "Finishes",
    }
    assert profile["quantity_coverage"]["coverage_pct"] > 50
    assert "Pset_WallCommon.Sector" in profile["available_zone_properties"]

    report = payload["parse_report"]
    assert report["elements_read"] == profile["element_count"]
    assert not report["errors"]


def test_rejects_unsupported_and_empty_uploads(api_client):
    project_id = api_client.post("/api/projects", json={"name": "X"}).json()["id"]

    response = api_client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("model.txt", b"nope", "text/plain")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]

    response = api_client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("model.ifc", b"", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_malformed_ifc_fails_the_project_without_crashing(api_client):
    project_id = api_client.post("/api/projects", json={"name": "Broken"}).json()["id"]
    response = api_client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("bad.ifc", b"not an ifc file at all", "application/octet-stream")},
    )
    assert response.status_code == 200
    job = wait_for_job(api_client, response.json()["job_id"])
    assert job["status"] == "done"
    assert job["result"]["elements_read"] == 0

    project = api_client.get(f"/api/projects/{project_id}").json()
    assert project["status"] == "failed"
    assert project["error"]


def test_job_progress_is_reported(api_client, sample_ifc_path):
    project_id = api_client.post("/api/projects", json={"name": "Progress"}).json()["id"]
    with open(sample_ifc_path, "rb") as handle:
        job_id = api_client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("sample.ifc", handle, "application/octet-stream")},
        ).json()["job_id"]

    job = wait_for_job(api_client, job_id)
    assert job["progress"] == 1.0
    assert job["kind"] == "parse"
    assert job["message"]


def test_unknown_job_returns_404(api_client):
    assert api_client.get("/api/jobs/does-not-exist").status_code == 404


# --- LOD preview ----------------------------------------------------------


def test_lod_preview_predicts_counts_for_every_level(api_client, project):
    payload = api_client.post(f"/api/projects/{project}/lod-preview", json={}).json()
    levels = payload["levels"]
    assert [item["level"] for item in levels] == ["L1", "L2", "L3", "L4", "L5"]
    counts = [item["task_count"] for item in levels]
    assert counts == sorted(counts)
    assert counts[0] >= 1
    assert next(item for item in levels if item["is_default"])["level"] == "L3"
    assert all(item["name"] and item["description"] for item in levels)
    assert payload["filter"]["elements_removed"] > 0


def test_lod_preview_reflects_the_zone_split(api_client, project):
    plain = api_client.post(f"/api/projects/{project}/lod-preview", json={}).json()
    zoned = api_client.post(
        f"/api/projects/{project}/lod-preview",
        json={"zone_split": "Pset_WallCommon.Sector"},
    ).json()
    plain_l3 = next(i for i in plain["levels"] if i["level"] == "L3")["task_count"]
    zoned_l3 = next(i for i in zoned["levels"] if i["level"] == "L3")["task_count"]
    assert zoned_l3 > plain_l3


def test_levels_endpoint_documents_the_five_levels(api_client):
    levels = api_client.get("/api/config/levels").json()["levels"]
    assert len(levels) == 5
    assert all(item["name"] and item["description"] for item in levels)


def test_config_endpoint_exposes_the_rule_files(api_client):
    payload = api_client.get("/api/config").json()
    assert set(payload["files"]) == {"filters", "work_packages", "rates", "sequencing"}
    assert payload["files"]["rates"]["rules"]
    assert payload["llm_enabled"] is False


# --- schedule generation --------------------------------------------------


def test_schedule_generation_and_retrieval(api_client, scheduled):
    payload = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    assert payload["level"] == "L3"
    assert payload["tasks"]
    assert payload["links"]
    assert payload["project_duration_days"] > 0
    assert payload["calendar"]["start_date"] == "2026-09-01"

    report = api_client.get(f"/api/projects/{scheduled}/run-report").json()
    assert report["cpm"]["project_duration_days"] == payload["project_duration_days"]
    assert report["filter"]["elements_removed"] > 0
    assert report["durations"]["confidence"]


def test_scheduling_before_parsing_is_rejected(api_client):
    project_id = api_client.post("/api/projects", json={"name": "Empty"}).json()["id"]
    response = api_client.post(f"/api/projects/{project_id}/schedule", json={"level": "L3"})
    assert response.status_code == 409


def test_invalid_level_is_rejected(api_client, project):
    response = api_client.post(f"/api/projects/{project}/schedule", json={"level": "L9"})
    assert response.status_code == 422


def test_regenerating_at_another_level_replaces_the_schedule(api_client, scheduled):
    before = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    job_id = api_client.post(
        f"/api/projects/{scheduled}/schedule", json={"level": "L2", "start_date": "2026-09-01"}
    ).json()["job_id"]
    assert wait_for_job(api_client, job_id)["status"] == "done"

    after = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    assert after["level"] == "L2"
    assert len(after["tasks"]) < len(before["tasks"])


# --- editing --------------------------------------------------------------


def test_rename_and_change_duration(api_client, scheduled):
    schedule = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    task = schedule["tasks"][0]

    response = api_client.patch(
        f"/api/projects/{scheduled}/tasks/{task['id']}",
        json={"label": "Renamed activity", "duration_days": task["duration_days"] + 10},
    )
    assert response.status_code == 200
    updated = next(t for t in response.json()["tasks"] if t["id"] == task["id"])
    assert updated["label"] == "Renamed activity"
    assert updated["duration_days"] == task["duration_days"] + 10
    assert updated["user_edited"] is True
    assert updated["rate_source"] == "user_override"
    # Dates must be recalculated, not left stale.
    assert updated["finish_date"] > task["finish_date"]


def test_deleting_a_task_removes_its_links(api_client, scheduled):
    schedule = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    target = next(
        task for task in schedule["tasks"]
        if any(link["predecessor_id"] == task["id"] for link in schedule["links"])
    )

    response = api_client.delete(f"/api/projects/{scheduled}/tasks/{target['id']}")
    assert response.status_code == 200
    payload = response.json()
    ids = {task["id"] for task in payload["tasks"]}
    assert target["id"] not in ids
    for link in payload["links"]:
        assert link["predecessor_id"] in ids
        assert link["successor_id"] in ids


def test_deleting_an_unknown_task_is_404(api_client, scheduled):
    assert api_client.delete(f"/api/projects/{scheduled}/tasks/nope").status_code == 404


def test_relinking_tasks(api_client, scheduled):
    schedule = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    first, second = schedule["tasks"][0]["id"], schedule["tasks"][-1]["id"]

    response = api_client.post(
        f"/api/projects/{scheduled}/links",
        json={"predecessor_id": first, "successor_id": second, "type": "SS", "lag": 4},
    )
    assert response.status_code == 200
    payload = response.json()
    link = next(
        item for item in payload["links"]
        if item["predecessor_id"] == first and item["successor_id"] == second
    )
    assert link["type"] == "SS" and link["lag"] == 4

    successor = next(t for t in payload["tasks"] if t["id"] == second)
    predecessor = next(t for t in payload["tasks"] if t["id"] == first)
    assert successor["early_start_offset"] >= predecessor["early_start_offset"] + 4

    response = api_client.delete(
        f"/api/projects/{scheduled}/links",
        params={"predecessor_id": first, "successor_id": second},
    )
    assert not [
        item for item in response.json()["links"]
        if item["predecessor_id"] == first and item["successor_id"] == second
    ]


def test_self_link_is_rejected(api_client, scheduled):
    task_id = api_client.get(f"/api/projects/{scheduled}/schedule").json()["tasks"][0]["id"]
    response = api_client.post(
        f"/api/projects/{scheduled}/links",
        json={"predecessor_id": task_id, "successor_id": task_id},
    )
    assert response.status_code == 400


def test_replacing_a_tasks_predecessor_list(api_client, scheduled):
    schedule = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    target = schedule["tasks"][-1]
    source = schedule["tasks"][0]

    response = api_client.patch(
        f"/api/projects/{scheduled}/tasks/{target['id']}",
        json={"predecessors": [{"id": source["id"], "type": "FS", "lag": 2}]},
    )
    updated = next(t for t in response.json()["tasks"] if t["id"] == target["id"])
    assert updated["predecessors"] == [{"id": source["id"], "type": "FS", "lag": 2}]


def test_calendar_change_reschedules(api_client, scheduled):
    before = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    response = api_client.put(
        f"/api/projects/{scheduled}/calendar",
        json={"start_date": "2026-10-05", "work_days": [0, 1, 2, 3, 4, 5, 6]},
    )
    after = response.json()
    assert after["calendar"]["start_date"] == "2026-10-05"
    assert after["tasks"][0]["start_date"] >= "2026-10-05"
    # A seven-day week compresses the calendar span of the same work.
    assert after["tasks"][0]["finish_date"] != before["tasks"][0]["finish_date"]


# --- rates ----------------------------------------------------------------


def test_rates_are_readable(api_client, project):
    payload = api_client.get(f"/api/projects/{project}/rates").json()
    assert payload["effective"]["rules"]
    assert payload["overrides"] == {}
    assert payload["defaults"]["default"]["unit"]


def test_rate_override_persists_and_reprices(api_client, scheduled):
    before = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    wall = next(t for t in before["tasks"] if t["rate_id"] == "wall-blockwork")

    response = api_client.put(
        f"/api/projects/{scheduled}/rates",
        json={"rules": [{"id": "wall-blockwork", "output_per_crew_day": 1.0}]},
    )
    assert response.status_code == 200
    assert response.json()["repriced_tasks"] > 0

    after = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    repriced = next(t for t in after["tasks"] if t["id"] == wall["id"])
    assert repriced["duration_days"] > wall["duration_days"]

    stored = api_client.get(f"/api/projects/{scheduled}/rates").json()
    assert stored["overrides"]["rules"][0]["id"] == "wall-blockwork"


def test_repricing_does_not_overwrite_a_manual_duration(api_client, scheduled):
    schedule = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    wall = next(t for t in schedule["tasks"] if t["rate_id"] == "wall-blockwork")
    api_client.patch(
        f"/api/projects/{scheduled}/tasks/{wall['id']}", json={"duration_days": 99}
    )
    api_client.put(
        f"/api/projects/{scheduled}/rates",
        json={"rules": [{"id": "wall-blockwork", "output_per_crew_day": 1.0}]},
    )
    after = api_client.get(f"/api/projects/{scheduled}/schedule").json()
    assert next(t for t in after["tasks"] if t["id"] == wall["id"])["duration_days"] == 99


def test_invalid_rate_values_are_rejected(api_client, project):
    response = api_client.put(
        f"/api/projects/{project}/rates",
        json={"rules": [{"id": "wall-blockwork", "output_per_crew_day": -5}]},
    )
    assert response.status_code == 422


# --- exports --------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "content_type"),
    [
        ("csv", "text/csv"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("mspdi", "application/xml"),
        ("xer", "text/plain"),
        ("json", "application/json"),
    ],
)
def test_export_endpoints(api_client, scheduled, fmt, content_type):
    response = api_client.get(f"/api/projects/{scheduled}/export/{fmt}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert "attachment" in response.headers["content-disposition"]
    assert "Sample_Tower" in response.headers["content-disposition"]
    assert len(response.content) > 200


def test_unknown_export_format_is_rejected(api_client, scheduled):
    response = api_client.get(f"/api/projects/{scheduled}/export/pdf")
    assert response.status_code == 400


def test_export_without_a_schedule_is_404(api_client, project):
    assert api_client.get(f"/api/projects/{project}/export/csv").status_code == 404


def test_export_format_listing(api_client, project):
    formats = api_client.get(f"/api/projects/{project}/export").json()["formats"]
    assert {item["id"] for item in formats} == {"csv", "xlsx", "mspdi", "xer", "json"}
