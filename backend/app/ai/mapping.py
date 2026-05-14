from __future__ import annotations

import json
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field

from ..config import settings


Role = Literal[
    "task_id",
    "name",
    "start",
    "end",
    "wbs",
    "phase",
    "join_key",
    "activity",
    "ignored",
]

JoinStrategy = Literal[
    "application_id",
    "category_and_level",
    "type_and_level",
    "name_fuzzy",
    "wbs_pattern",
]


class ColumnMapping(BaseModel):
    column: str = Field(description="Exact header text from the spreadsheet.")
    role: Role = Field(description="Canonical role this column fills.")
    speckle_property: str | None = Field(
        default=None,
        description=(
            "When role=join_key, the Speckle element property to match on "
            "(e.g. 'applicationId', 'category', 'level.name')."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Optional short note about the mapping decision.",
    )


class MappingProposal(BaseModel):
    mapping: list[ColumnMapping]
    join_strategy: JoinStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    unmapped_columns: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """\
You are mapping a construction-schedule spreadsheet to a BIM model exposed via Speckle.

You will be given:
1. The schedule's header row and a small sample of rows.
2. A compact summary of the Speckle model's element catalog: counts per category and
   level, sample elements with their properties, and the set of property keys seen.

Your job: decide which spreadsheet column fills each canonical role and how rows
should be joined to model elements. Be conservative — set confidence below 0.7 if
you are unsure, and list unmapped columns rather than forcing a fit.

Canonical roles:
- task_id      : unique task identifier
- name         : human-readable task name
- start, end   : task start / finish date
- wbs          : work-breakdown-structure code
- phase        : construction phase / activity grouping
- join_key     : the column whose value resolves to model elements
- activity     : what is happening (construct, demolish, etc.)
- ignored      : column with no relevant role

Join strategies (pick the strongest justified by the data):
- application_id     : a column contains Speckle applicationId values verbatim
                       (Revit ElementIds, IFC GlobalIds, etc.)
- category_and_level : rows resolve to all elements of a given category on a given level
- type_and_level     : like above but using family/type instead of category
- name_fuzzy         : rows resolve via fuzzy match on element name/family/type
- wbs_pattern        : rows resolve via regex on a Speckle parameter (e.g. Mark)

Prefer application_id whenever any column's values look like the sample applicationId
values in the catalog summary.
"""


def _user_message(headers: list[str], samples: list[dict[str, Any]], catalog: dict[str, Any]) -> str:
    sample_md_lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in samples:
        sample_md_lines.append(
            "| " + " | ".join(str(row.get(h, "")) for h in headers) + " |"
        )
    sample_md = "\n".join(sample_md_lines)

    return (
        "## Spreadsheet sample\n\n"
        f"{sample_md}\n\n"
        "## Speckle catalog summary\n\n"
        "```json\n"
        f"{json.dumps(catalog, indent=2, default=str)[:8000]}\n"
        "```\n\n"
        "Return a single mapping decision as structured output."
    )


def propose_mapping(
    headers: list[str],
    sample_rows: list[dict[str, Any]],
    catalog_summary: dict[str, Any],
) -> MappingProposal:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured. Set it in .env and restart workers."
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.parse(
        model=settings.claude_model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _user_message(headers, sample_rows, catalog_summary)}
        ],
        output_format=MappingProposal,
    )

    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Claude returned no parsed output for mapping proposal.")
    return parsed
