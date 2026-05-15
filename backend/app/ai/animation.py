"""Claude-driven phase grouping for the M4 animation script.

The schedule's per-task timing is deterministic from the confirmed mapping. We
only ask Claude to (1) cluster tasks into 3-6 named phases and (2) pick a color
per phase. This bounds Claude's output size to phases × tasks-per-phase, not
elements.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from ..config import settings


class Phase(BaseModel):
    name: str
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    task_ids: list[str]


class PhaseGrouping(BaseModel):
    phases: list[Phase]
    rationale: str = ""


SYSTEM_PROMPT = """\
You are organising a construction-schedule task list into a small number of
well-named phases for a 4D BIM animation.

You will be given a list of tasks, each with: task_id, optional name, optional
WBS code, optional phase value from the schedule, start day, end day, and the
activity verb (construct / demolish / temporary).

Your job: cluster the tasks into 3-6 phases with short, building-trade-friendly
names (e.g. "Foundations", "Superstructure", "Envelope", "MEP", "Fit-out").
Assign each task to exactly one phase. Pick a distinct, visually distinguishable
hex color per phase.

Constraints:
- Every task_id you receive MUST appear in exactly one phase.
- Use 3-6 phases (fewer is better when tasks are homogeneous).
- Color hex must be `#RRGGBB`.
"""


def propose_phases(tasks: list[dict[str, Any]]) -> PhaseGrouping:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured. Set it in .env and restart workers."
        )

    # Cap the task count we send. For very large schedules we truncate; the
    # remainder are bucketed into a synthetic "Other" phase by the caller.
    sent = tasks[:400]

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.parse(
        model=settings.claude_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "## Tasks\n\n"
                    "```json\n"
                    f"{json.dumps(sent, indent=2, default=str)}\n"
                    "```\n\n"
                    "Return a phase grouping as structured output. Every task_id "
                    "above must appear in exactly one phase."
                ),
            }
        ],
        output_format=PhaseGrouping,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Claude returned no parsed output for phase grouping.")
    return parsed
