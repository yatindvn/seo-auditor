"""Rendering results, and the comparison stored per page."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol


@dataclass
class RenderResult:
    url: str
    html: str = ""
    final_url: Optional[str] = None
    status: Optional[int] = None
    render_ms: Optional[float] = None
    error: Optional[str] = None
    axe: Optional[Dict[str, Any]] = None       # raw axe-core results, when asked for
    axe_error: Optional[str] = None


@dataclass
class RenderComparison:
    url: str
    status: str = "rendered"                  # rendered | failed
    error: Optional[str] = None
    render_ms: Optional[float] = None
    raw_word_count: Optional[int] = None
    rendered_word_count: Optional[int] = None
    changes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    js_only_links: List[str] = field(default_factory=list)
    js_only_links_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Renderer(Protocol):
    name: str

    def render(self, urls: List[str],
               on_progress: Optional[Callable[[int, int, str], None]] = None,
               run_axe: bool = False) -> List[RenderResult]: ...
