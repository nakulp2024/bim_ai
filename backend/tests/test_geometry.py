"""Mesh extraction and the geometry endpoints behind the 4D viewer."""

from __future__ import annotations

import numpy as np
import pytest

from app.ifc.geometry import extract_geometry, read_manifest, write_cache
from tests.conftest import wait_for_job


@pytest.fixture(scope="module")
def geometry(sample_ifc_path):
    return extract_geometry(sample_ifc_path, threads=1)


def unpack(result):
    manifest = result.manifest
    positions = np.frombuffer(
        result.buffer, dtype=np.float32, count=manifest["buffers"]["positions"]["length"]
    ).reshape(-1, 3)
    indices = np.frombuffer(
        result.buffer,
        dtype=np.uint32,
        offset=manifest["buffers"]["indices"]["offset"],
        count=manifest["buffers"]["indices"]["length"],
    )
    return positions, indices


def element(result, name):
    return next(e for e in result.manifest["elements"] if e["name"] == name)


# --- extraction ------------------------------------------------------------


def test_every_renderable_element_is_tessellated(geometry):
    manifest = geometry.manifest
    assert manifest["element_count"] == 84
    assert manifest["triangle_count"] > 0
    assert not geometry.warnings


def test_non_work_classes_are_never_rendered(geometry):
    rendered = {e["ifc_class"] for e in geometry.manifest["elements"]}
    # The fixture gives the IfcSpace a real box; it must still be excluded.
    assert "IfcSpace" not in rendered
    assert not rendered & {"IfcOpeningElement", "IfcAnnotation", "IfcVirtualElement"}


def test_buffers_are_internally_consistent(geometry):
    positions, indices = unpack(geometry)
    manifest = geometry.manifest
    assert len(positions) == manifest["vertex_count"]
    assert len(indices) == manifest["triangle_count"] * 3
    assert indices.max() < len(positions)
    assert np.isfinite(positions).all()


def test_element_slices_tile_the_buffers_without_overlap(geometry):
    elements = sorted(geometry.manifest["elements"], key=lambda e: e["vertex_start"])
    cursor = 0
    for item in elements:
        assert item["vertex_start"] == cursor
        cursor += item["vertex_count"]
    assert cursor == geometry.manifest["vertex_count"]

    _, indices = unpack(geometry)
    for item in elements:
        chunk = indices[item["index_start"] : item["index_start"] + item["index_count"]]
        # An element's triangles only ever reference its own vertices; this is
        # what makes per-element recolouring safe.
        assert chunk.min() >= item["vertex_start"]
        assert chunk.max() < item["vertex_start"] + item["vertex_count"]


def test_axes_are_converted_to_y_up_and_centred(geometry):
    # Column C7: 0.4 x 0.4 x 3.5 at world (7.5, 7.5), base z = 3.5.
    bbox = element(geometry, "L02 Column C7 (no Qto)")["bbox"]
    size = np.subtract(bbox["max"], bbox["min"])
    assert size == pytest.approx([0.4, 3.5, 0.4], abs=1e-3)

    offset = geometry.manifest["origin_offset"]
    centre = np.add(bbox["min"], bbox["max"]) / 2 + offset
    # three.js x = IFC x; three.js z = -IFC y.
    assert centre[0] == pytest.approx(7.5, abs=1e-3)
    assert centre[2] == pytest.approx(-7.5, abs=1e-3)


def test_model_sits_on_the_ground_plane(geometry):
    bounds = geometry.manifest["bounds"]
    assert bounds["min"][1] == pytest.approx(0.0, abs=1e-4)
    # Centred in plan so float32 keeps millimetres on georeferenced models.
    assert bounds["min"][0] == pytest.approx(-bounds["max"][0], abs=1e-3)
    assert bounds["min"][2] == pytest.approx(-bounds["max"][2], abs=1e-3)


def test_assembly_parts_carry_their_parent(geometry):
    parts = [e for e in geometry.manifest["elements"] if e["name"].startswith("SF-01")]
    assert len(parts) == 3
    assert len({part["parent_id"] for part in parts}) == 1
    assert all(part["parent_id"] for part in parts)


def test_upper_storeys_sit_above_lower_ones(geometry):
    low = element(geometry, "L01 Floor Slab")["bbox"]
    high = element(geometry, "L02 Floor Slab")["bbox"]
    assert high["min"][1] > low["max"][1]


def test_triangle_budget_is_enforced_and_reported(sample_ifc_path):
    result = extract_geometry(sample_ifc_path, max_triangles=100, threads=1)
    assert result.manifest["triangle_count"] <= 100
    assert result.manifest["element_count"] < 84
    assert any("budget" in warning for warning in result.warnings)


def test_a_model_with_no_geometry_yields_an_empty_manifest(tmp_path):
    from tests.fixtures.sample_ifc import SampleModelBuilder

    builder = SampleModelBuilder()
    builder.add_element("IfcWall", "Bare wall", storey="L01", quantities={"NetArea": 10.0})
    path = builder.write(tmp_path / "bare.ifc")
    result = extract_geometry(path, threads=1)
    assert result.manifest["element_count"] == 0
    assert result.buffer == b""


def test_cache_round_trip(geometry, tmp_path):
    write_cache(geometry, tmp_path)
    manifest = read_manifest(tmp_path)
    assert manifest["element_count"] == geometry.manifest["element_count"]
    assert manifest["build_id"]
    assert (tmp_path / "geometry.bin").read_bytes() == geometry.buffer


def test_half_written_cache_is_not_served(geometry, tmp_path):
    write_cache(geometry, tmp_path)
    (tmp_path / "geometry.bin").unlink()
    assert read_manifest(tmp_path) is None


# --- API -------------------------------------------------------------------------


def test_geometry_is_built_on_demand_and_served(api_client, project):
    assert api_client.get(f"/api/projects/{project}/geometry").status_code == 404

    response = api_client.post(f"/api/projects/{project}/geometry")
    assert response.status_code == 200
    job = wait_for_job(api_client, response.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["element_count"] == 84

    manifest = api_client.get(f"/api/projects/{project}/geometry").json()
    assert manifest["element_count"] == 84
    assert api_client.get(f"/api/projects/{project}").json()["geometry_status"] == "ready"

    buffer = api_client.get(f"/api/projects/{project}/geometry/buffer")
    assert buffer.status_code == 200
    assert buffer.headers["content-type"] == "application/octet-stream"
    expected = (
        manifest["buffers"]["positions"]["length"] * 4
        + manifest["buffers"]["indices"]["length"] * 4
    )
    assert len(buffer.content) == expected


def test_building_twice_reuses_the_cache(api_client, project):
    job = api_client.post(f"/api/projects/{project}/geometry").json()["job_id"]
    wait_for_job(api_client, job)
    first = api_client.get(f"/api/projects/{project}/geometry").json()["build_id"]

    again = api_client.post(f"/api/projects/{project}/geometry").json()
    assert again == {"job_id": None, "status": "ready"}

    forced = api_client.post(f"/api/projects/{project}/geometry", params={"force": True}).json()
    wait_for_job(api_client, forced["job_id"])
    assert api_client.get(f"/api/projects/{project}/geometry").json()["build_id"] != first


def test_reuploading_invalidates_geometry(api_client, project, sample_ifc_path):
    job = api_client.post(f"/api/projects/{project}/geometry").json()["job_id"]
    wait_for_job(api_client, job)

    with open(sample_ifc_path, "rb") as handle:
        upload = api_client.post(
            f"/api/projects/{project}/upload",
            files={"file": ("sample.ifc", handle, "application/octet-stream")},
        ).json()
    wait_for_job(api_client, upload["job_id"])

    assert api_client.get(f"/api/projects/{project}").json()["geometry_status"] is None
    assert api_client.get(f"/api/projects/{project}/geometry").status_code == 404


def test_geometry_needs_an_uploaded_model(api_client):
    project_id = api_client.post("/api/projects", json={"name": "Empty"}).json()["id"]
    assert api_client.post(f"/api/projects/{project_id}/geometry").status_code == 409
    assert api_client.get(f"/api/projects/{project_id}/geometry/buffer").status_code == 404
