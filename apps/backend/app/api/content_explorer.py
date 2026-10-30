"""Content Explorer (Phase 7.2): the top results for a topic, analysed."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.keywords import _csv, _csv_response
from app.content_explorer import explore as explore_mod
from app.providers.serp import ProviderError, ProviderSkipped

router = APIRouter()

CSV_COLUMNS = ["position", "url", "domain", "title", "status", "error", "word_count", "h1", "h2_count", "schema_types",
               "images", "internal_links", "external_links", "readability", "issues", "referring_domains", "backlinks"]


class SearchIn(BaseModel):
    topic: str = Field(..., max_length=200)
    country: str = Field("US", max_length=8)
    language: str = Field("en", max_length=8)
    refresh: bool = False


@router.post("/content-explorer")
def search(body: SearchIn):
    try:
        return explore_mod.explore(body.topic, body.country, body.language, refresh=body.refresh)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ProviderSkipped as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/content-explorer/recent")
def recent():
    return {"items": explore_mod.recent()}


def _found(search_id: int):
    found = explore_mod.get_search(search_id)
    if found is None:
        raise HTTPException(status_code=404, detail="search not found")
    return found


@router.get("/content-explorer/{search_id}")
def get_search(search_id: int):
    return _found(search_id)


@router.get("/content-explorer/{search_id}/csv")
def search_csv(search_id: int):
    found = _found(search_id)
    rows = []
    for r in found["results"]:
        values = {**r, "h2_count": sum(1 for h in r.get("outline") or [] if h.get("level") == 2),
                  "schema_types": ";".join(r.get("schema_types") or [])}
        rows.append(["" if values.get(c) is None else values.get(c) for c in CSV_COLUMNS])
    slug = "-".join(found["topic"].split())[:60] or "content"
    return _csv_response(_csv(found["dry_run"], CSV_COLUMNS, rows), f"content-{slug}.csv")
