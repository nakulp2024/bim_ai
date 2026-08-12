"""Schedule exporters. Every format carries the source GlobalIds through."""

from .jsonpkg import to_json_package
from .msproject import to_msproject_xml
from .p6 import to_p6_xer
from .tabular import to_csv, to_xlsx

FORMATS = {
    "csv": ("text/csv", "csv", to_csv),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
        to_xlsx,
    ),
    "mspdi": ("application/xml", "xml", to_msproject_xml),
    "xer": ("text/plain", "xer", to_p6_xer),
    "json": ("application/json", "json", to_json_package),
}

__all__ = ["FORMATS", "to_csv", "to_xlsx", "to_msproject_xml", "to_p6_xer", "to_json_package"]
