"""One page's accessibility scan."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

IMPACTS = ("critical", "serious", "moderate", "minor")


@dataclass
class A11yResult:
    url: str
    status: str = "scanned"                   # scanned | failed
    error: Optional[str] = None
    score: Optional[int] = None
    counts: Dict[str, int] = field(default_factory=lambda: {i: 0 for i in IMPACTS})
    violations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
