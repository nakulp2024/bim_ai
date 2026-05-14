from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse

from specklepy.api.client import SpeckleClient
from specklepy.api import operations
from specklepy.transports.server import ServerTransport

from ..config import settings


_MAX_TRAVERSE = 50_000  # safety limit


def _make_client(token: str) -> SpeckleClient:
    parsed = urlparse(settings.speckle_internal_url)
    host = parsed.netloc or parsed.path
    use_ssl = parsed.scheme == "https"
    client = SpeckleClient(host=host, use_ssl=use_ssl)
    client.authenticate_with_token(token)
    return client


def _walk(node: Any, out: list[Any], seen: set[int]) -> None:
    if len(out) >= _MAX_TRAVERSE:
        return
    if node is None:
        return
    if id(node) in seen:
        return
    seen.add(id(node))

    if isinstance(node, list):
        for item in node:
            _walk(item, out, seen)
        return
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, out, seen)
        return

    # Speckle Base objects expose attributes via get_member_names()
    if hasattr(node, "get_member_names"):
        if getattr(node, "speckle_type", None) and getattr(node, "applicationId", None):
            out.append(node)
        for name in node.get_member_names():
            try:
                child = getattr(node, name, None)
            except Exception:
                continue
            if child is node:
                continue
            _walk(child, out, seen)


def _level_name(el: Any) -> str | None:
    lvl = getattr(el, "level", None)
    if lvl is None:
        return None
    name = getattr(lvl, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(lvl, str):
        return lvl
    return None


def _category(el: Any) -> str | None:
    cat = getattr(el, "category", None)
    if isinstance(cat, str):
        return cat
    st = getattr(el, "speckle_type", "") or ""
    if st.startswith("Objects.BuiltElements."):
        return st.rsplit(".", 1)[-1]
    return None


def build_catalog_summary(
    token: str,
    speckle_project_id: str,
    referenced_object: str,
    sample_n: int = 20,
) -> dict[str, Any]:
    """Receive the referenced object tree and return a compact summary for Claude."""
    client = _make_client(token)
    transport = ServerTransport(client=client, stream_id=speckle_project_id)
    root = operations.receive(obj_id=referenced_object, remote_transport=transport)

    elements: list[Any] = []
    _walk(root, elements, set())

    by_category: Counter[str] = Counter()
    by_level: Counter[str] = Counter()
    by_speckle_type: Counter[str] = Counter()
    property_keys: set[str] = set()
    samples: list[dict[str, Any]] = []

    sample_categories_seen: set[str] = set()
    for el in elements:
        cat = _category(el) or "(uncategorised)"
        lvl = _level_name(el) or "(no-level)"
        st = getattr(el, "speckle_type", None) or "(unknown)"
        by_category[cat] += 1
        by_level[lvl] += 1
        by_speckle_type[st] += 1

        # Collect property keys we'd expose for the join.
        for k in ("family", "type", "Mark", "Comments"):
            if hasattr(el, k):
                property_keys.add(k)
        if hasattr(el, "parameters"):
            params = getattr(el, "parameters", None)
            if hasattr(params, "get_member_names"):
                for name in list(params.get_member_names())[:30]:
                    property_keys.add(f"parameters.{name}")

        # Sample: take one per category, then any extras up to sample_n.
        if cat not in sample_categories_seen and len(samples) < sample_n:
            sample_categories_seen.add(cat)
            samples.append(
                {
                    "id": getattr(el, "id", None),
                    "applicationId": getattr(el, "applicationId", None),
                    "speckle_type": st,
                    "category": cat,
                    "level": lvl,
                    "family": getattr(el, "family", None),
                    "type": getattr(el, "type", None),
                }
            )

    # Fill the sample bucket with a few more if we have room.
    if len(samples) < sample_n:
        for el in elements[: sample_n * 4]:
            if len(samples) >= sample_n:
                break
            already = {s["id"] for s in samples}
            if getattr(el, "id", None) in already:
                continue
            samples.append(
                {
                    "id": getattr(el, "id", None),
                    "applicationId": getattr(el, "applicationId", None),
                    "speckle_type": getattr(el, "speckle_type", None),
                    "category": _category(el),
                    "level": _level_name(el),
                    "family": getattr(el, "family", None),
                    "type": getattr(el, "type", None),
                }
            )

    return {
        "total_elements": len(elements),
        "by_category": dict(by_category.most_common(50)),
        "by_level": dict(by_level.most_common(50)),
        "by_speckle_type": dict(by_speckle_type.most_common(30)),
        "property_keys_seen": sorted(property_keys),
        "sample_elements": samples,
    }
