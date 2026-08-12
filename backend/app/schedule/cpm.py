"""Critical path method: forward pass, backward pass, float, critical flag.

Everything is computed in integer working-day offsets from the project start.
The calendar turns those offsets into dates at the end.

Convention (all offsets are 0-based inclusive starts, EF is exclusive finish):
    EF = ES + duration
    FS: successor.ES >= predecessor.EF + lag
    SS: successor.ES >= predecessor.ES + lag
    FF: successor.EF >= predecessor.EF + lag
    SF: successor.EF >= predecessor.ES + lag
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LINK_TYPES = ("FS", "SS", "FF", "SF")


@dataclass
class CpmTask:
    id: str
    duration: int
    predecessors: list[dict[str, Any]] = field(default_factory=list)

    early_start: int = 0
    early_finish: int = 0
    late_start: int = 0
    late_finish: int = 0
    total_float: int = 0
    free_float: int = 0
    is_critical: bool = False


@dataclass
class CpmResult:
    tasks: dict[str, CpmTask]
    order: list[str]
    project_duration: int
    critical_path: list[str]
    cycles_broken: list[dict[str, str]] = field(default_factory=list)
    dropped_links: list[dict[str, str]] = field(default_factory=list)


def _topological_order(
    ids: list[str], predecessors: dict[str, list[dict[str, Any]]]
) -> tuple[list[str], list[dict[str, str]]]:
    """Kahn's algorithm; any remaining edges are a cycle and get reported."""
    incoming: dict[str, set[str]] = {task_id: set() for task_id in ids}
    outgoing: dict[str, set[str]] = {task_id: set() for task_id in ids}
    for task_id in ids:
        for link in predecessors.get(task_id, []):
            source = link["id"]
            if source in incoming and source != task_id:
                incoming[task_id].add(source)
                outgoing[source].add(task_id)

    ready = sorted(task_id for task_id in ids if not incoming[task_id])
    placed: set[str] = set()
    order: list[str] = []
    broken: list[dict[str, str]] = []

    while len(order) < len(ids):
        if not ready:
            # Everything left is in a cycle. Free the single most-nearly-ready
            # task rather than shredding every edge in the cyclic subgraph.
            remaining = [task_id for task_id in ids if task_id not in placed]
            victim = min(remaining, key=lambda t: (len(incoming[t]), t))
            for source in sorted(incoming[victim]):
                broken.append({"from": source, "to": victim})
            incoming[victim] = set()
            ready.append(victim)

        current = ready.pop(0)
        order.append(current)
        placed.add(current)
        for successor in sorted(outgoing[current]):
            incoming[successor].discard(current)
            if not incoming[successor] and successor not in placed and successor not in ready:
                ready.append(successor)
        ready.sort()

    return order, broken


def calculate(
    tasks: list[CpmTask], project_start_offset: int = 0
) -> CpmResult:
    """Run the forward and backward passes over ``tasks``."""
    by_id: dict[str, CpmTask] = {task.id: task for task in tasks}
    ids = list(by_id.keys())

    # Sanitise links: drop references to unknown tasks and self-links.
    dropped: list[dict[str, str]] = []
    predecessors: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        cleaned: list[dict[str, Any]] = []
        for link in task.predecessors:
            source = link.get("id")
            if source not in by_id:
                dropped.append({"to": task.id, "from": str(source), "reason": "unknown_task"})
                continue
            if source == task.id:
                dropped.append({"to": task.id, "from": str(source), "reason": "self_link"})
                continue
            link_type = str(link.get("type") or "FS").upper()
            if link_type not in LINK_TYPES:
                link_type = "FS"
            cleaned.append({"id": source, "type": link_type, "lag": int(link.get("lag") or 0)})
        task.predecessors = cleaned
        predecessors[task.id] = cleaned

    order, cycles_broken = _topological_order(ids, predecessors)
    for cycle in cycles_broken:
        predecessors[cycle["to"]] = [
            link for link in predecessors[cycle["to"]] if link["id"] != cycle["from"]
        ]
        by_id[cycle["to"]].predecessors = predecessors[cycle["to"]]

    # --- forward pass -----------------------------------------------------
    for task_id in order:
        task = by_id[task_id]
        duration = max(0, int(task.duration))
        earliest = project_start_offset
        for link in predecessors[task_id]:
            source = by_id[link["id"]]
            lag = link["lag"]
            if link["type"] == "FS":
                candidate = source.early_finish + lag
            elif link["type"] == "SS":
                candidate = source.early_start + lag
            elif link["type"] == "FF":
                candidate = source.early_finish + lag - duration
            else:  # SF
                candidate = source.early_start + lag - duration
            earliest = max(earliest, candidate)
        task.early_start = max(project_start_offset, earliest)
        task.early_finish = task.early_start + duration

    project_duration = max((by_id[t].early_finish for t in order), default=project_start_offset)

    # --- backward pass ----------------------------------------------------
    successors: dict[str, list[tuple[str, dict[str, Any]]]] = {task_id: [] for task_id in ids}
    for task_id in ids:
        for link in predecessors[task_id]:
            successors[link["id"]].append((task_id, link))

    for task_id in reversed(order):
        task = by_id[task_id]
        duration = max(0, int(task.duration))
        latest = project_duration
        for successor_id, link in successors[task_id]:
            successor = by_id[successor_id]
            lag = link["lag"]
            if link["type"] == "FS":
                candidate = successor.late_start - lag
            elif link["type"] == "SS":
                candidate = successor.late_start - lag + duration
            elif link["type"] == "FF":
                candidate = successor.late_finish - lag
            else:  # SF
                candidate = successor.late_finish - lag + duration
            latest = min(latest, candidate)
        task.late_finish = latest
        task.late_start = task.late_finish - duration
        task.total_float = task.late_start - task.early_start
        task.is_critical = task.total_float <= 0

    # --- free float -------------------------------------------------------
    for task_id in ids:
        task = by_id[task_id]
        limits = []
        for successor_id, link in successors[task_id]:
            successor = by_id[successor_id]
            lag = link["lag"]
            if link["type"] == "FS":
                limits.append(successor.early_start - lag - task.early_finish)
            elif link["type"] == "SS":
                limits.append(successor.early_start - lag - task.early_start)
            elif link["type"] == "FF":
                limits.append(successor.early_finish - lag - task.early_finish)
            else:  # SF
                limits.append(successor.early_finish - lag - task.early_start)
        task.free_float = min(limits) if limits else task.total_float

    critical_path = [
        task_id
        for task_id in sorted(order, key=lambda t: (by_id[t].early_start, t))
        if by_id[task_id].is_critical
    ]

    return CpmResult(
        tasks=by_id,
        order=order,
        project_duration=project_duration - project_start_offset,
        critical_path=critical_path,
        cycles_broken=cycles_broken,
        dropped_links=dropped,
    )
