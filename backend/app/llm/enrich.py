"""The three optional LLM assists, each independently skippable.

(a) natural task naming
(b) classifying unrecognised proxies / ObjectType strings into work packages
(c) suggesting missing logic links

Every function mutates only additive fields and records what it changed under
``llm_notes``, so a reviewer can always tell deterministic output from suggested
output.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .client import complete_json, is_enabled

log = logging.getLogger(__name__)

NAMING_PROMPT = """You are naming construction programme activities.
Rewrite each task name so a site manager would recognise it. Keep the storey
prefix, keep it under 60 characters, do not invent scope.

Return JSON: [{{"id": "<task id>", "name": "<new name>"}}]

Tasks:
{payload}
"""

CLASSIFY_PROMPT = """Classify each unrecognised building element into exactly one
work package from: Substructure, Superstructure, Envelope, MEP, Interior, Finishes.

Return JSON: [{{"id": "<task id>", "work_package": "<package>", "reason": "<short>"}}]

Elements:
{payload}
"""

LOGIC_PROMPT = """Suggest missing predecessor relationships in this construction
programme. Only suggest links that are physically necessary. Use FS, SS, FF or SF
and a lag in working days.

Return JSON: [{{"predecessor_id": "...", "successor_id": "...", "type": "FS", "lag": 0,
"reason": "<short>"}}]

Tasks:
{payload}
"""

VALID_PACKAGES = {"Substructure", "Superstructure", "Envelope", "MEP", "Interior", "Finishes"}
VALID_LINK_TYPES = {"FS", "SS", "FF", "SF"}


def suggest_names(tasks: list[dict[str, Any]], limit: int = 200) -> dict[str, str]:
    payload = [
        {
            "id": task["id"],
            "current": task.get("label"),
            "class": task.get("ifc_class"),
            "type": task.get("type_name"),
            "material": task.get("material"),
            "storey": task.get("storey_name"),
            "count": task.get("element_count"),
        }
        for task in tasks[:limit]
    ]
    result = complete_json(NAMING_PROMPT.format(payload=payload))
    names: dict[str, str] = {}
    valid_ids = {task["id"] for task in tasks}
    for item in result if isinstance(result, list) else []:
        task_id = str(item.get("id", ""))
        name = str(item.get("name", "")).strip()
        if task_id in valid_ids and name:
            names[task_id] = name[:120]
    return names


def classify_unrecognised(
    tasks: list[dict[str, Any]], limit: int = 100
) -> dict[str, dict[str, str]]:
    """Only touches tasks the deterministic classifier could not place well."""
    candidates = [
        task
        for task in tasks
        if task.get("ifc_class") == "IfcBuildingElementProxy"
        or (task.get("ifc_class") and task.get("predefined_type") in (None, "NOTDEFINED"))
    ][:limit]
    if not candidates:
        return {}
    payload = [
        {
            "id": task["id"],
            "class": task.get("ifc_class"),
            "object_type": task.get("type_name") or task.get("label"),
            "material": task.get("material"),
            "storey": task.get("storey_name"),
        }
        for task in candidates
    ]
    result = complete_json(CLASSIFY_PROMPT.format(payload=payload))
    valid_ids = {task["id"] for task in candidates}
    classified: dict[str, dict[str, str]] = {}
    for item in result if isinstance(result, list) else []:
        task_id = str(item.get("id", ""))
        package = str(item.get("work_package", ""))
        if task_id in valid_ids and package in VALID_PACKAGES:
            classified[task_id] = {
                "work_package": package,
                "reason": str(item.get("reason", ""))[:200],
            }
    return classified


def suggest_links(tasks: list[dict[str, Any]], limit: int = 150) -> list[dict[str, Any]]:
    payload = [
        {
            "id": task["id"],
            "name": task.get("label"),
            "package": task.get("work_package"),
            "storey": task.get("storey_name"),
            "duration": task.get("duration_days"),
            "predecessors": [link.get("id") for link in task.get("predecessors") or []],
        }
        for task in tasks[:limit]
    ]
    result = complete_json(LOGIC_PROMPT.format(payload=payload))
    valid_ids = {task["id"] for task in tasks}
    suggestions: list[dict[str, Any]] = []
    for item in result if isinstance(result, list) else []:
        predecessor = str(item.get("predecessor_id", ""))
        successor = str(item.get("successor_id", ""))
        link_type = str(item.get("type", "FS")).upper()
        if predecessor not in valid_ids or successor not in valid_ids:
            continue
        if predecessor == successor or link_type not in VALID_LINK_TYPES:
            continue
        suggestions.append(
            {
                "predecessor_id": predecessor,
                "successor_id": successor,
                "type": link_type,
                "lag": int(item.get("lag") or 0),
                "origin": "llm_suggestion",
                "reason": str(item.get("reason", ""))[:200],
                "accepted": False,
            }
        )
    return suggestions


def enrich_schedule(tasks: list[dict[str, Any]], frame: pd.DataFrame) -> dict[str, Any]:
    """Apply naming + classification in place; return link suggestions.

    Suggested links are deliberately NOT applied: they are returned for the user
    to accept, so the calculated programme stays deterministic.
    """
    outcome: dict[str, Any] = {"renamed": 0, "reclassified": 0, "suggested_links": []}
    if not is_enabled() or not tasks:
        return outcome

    by_id = {task["id"]: task for task in tasks}

    try:
        for task_id, name in suggest_names(tasks).items():
            task = by_id[task_id]
            task.setdefault("llm_notes", {})["original_label"] = task.get("label")
            task["label"] = name
            outcome["renamed"] += 1
    except Exception as exc:
        log.warning("LLM naming skipped: %s", exc)

    try:
        for task_id, classification in classify_unrecognised(tasks).items():
            task = by_id[task_id]
            notes = task.setdefault("llm_notes", {})
            notes["original_work_package"] = task.get("work_package")
            notes["classification_reason"] = classification["reason"]
            task["work_package"] = classification["work_package"]
            outcome["reclassified"] += 1
    except Exception as exc:
        log.warning("LLM classification skipped: %s", exc)

    try:
        outcome["suggested_links"] = suggest_links(tasks)
    except Exception as exc:
        log.warning("LLM logic suggestions skipped: %s", exc)

    return outcome
