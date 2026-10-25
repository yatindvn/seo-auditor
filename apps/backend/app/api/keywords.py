"""Keywords Explorer and Content Gap over HTTP, as JSON and CSV."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import Competitor, Project
from app.keywords import explorer, gap
from app.providers.serp import ProviderError, ProviderSkipped

router = APIRouter()
DRY_RUN_LINE = "# DRY RUN — made-up data"


class ExploreIn(BaseModel):
    seed: str = Field(max_length=80)
    country: str = Field("US", min_length=2, max_length=2)
    language: str = Field("en", min_length=2, max_length=8)
    cluster: bool = False


class GapIn(BaseModel):
    competitors: Optional[List[str]] = None
    country: str = Field("US", min_length=2, max_length=2)
    language: str = Field("en", min_length=2, max_length=8)
    limit: int = Field(500, ge=10, le=1000)


def _explore(seed, country, language, cluster):
    try:
        return explorer.explore(seed, country=country, language=language, cluster=cluster)
    except ProviderSkipped as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _csv(dry_run: bool, header: List[str], rows: List[List]) -> str:
    out = io.StringIO()
    if dry_run:
        out.write(DRY_RUN_LINE + "\n")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _csv_response(text: str, filename: str) -> Response:
    return Response(content=text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/keywords/explore")
def explore_keywords(body: ExploreIn):
    return asdict(_explore(body.seed, body.country, body.language, body.cluster))


@router.get("/keywords/explore.csv")
def explore_keywords_csv(seed: str = Query(..., max_length=80), country: str = "US", language: str = "en"):
    result = _explore(seed, country, language, False)
    columns = ["keyword", "source", "search_volume", "cpc", "competition", "difficulty",
               "traffic_potential_estimate"]
    rows = [[k[c] if k[c] is not None else "" for c in columns] for k in result.keywords]
    return _csv_response(_csv(result.dry_run, columns, rows), "keywords.csv")


def _gap(project_id: int, competitors: Optional[List[str]], country: str, language: str, limit: int):
    with _factory()() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="no such project")
        domain = project.domain
        if not competitors:
            competitors = list(session.scalars(select(Competitor.domain)
                                               .where(Competitor.project_id == project_id)
                                               .order_by(Competitor.domain)))
    if not competitors:
        raise HTTPException(status_code=400, detail="add competitors to the project, or pass some")
    try:
        return gap.content_gap(domain, competitors, country=country, language=language, limit=limit)
    except ProviderSkipped as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/projects/{project_id}/content-gap")
def content_gap(project_id: int, body: GapIn):
    return asdict(_gap(project_id, body.competitors, body.country, body.language, body.limit))


@router.get("/projects/{project_id}/content-gap.csv")
def content_gap_csv(project_id: int, competitor: Optional[List[str]] = Query(None),
                    country: str = "US", language: str = "en", limit: int = Query(500, ge=10, le=1000)):
    result = _gap(project_id, competitor, country, language, limit)
    header = ["keyword", "search_volume", "difficulty", "opportunity", "best_competitor_position"]
    for rival in result.competitors:
        header += [f"{rival} position", f"{rival} url"]
    rows = []
    for row in result.rows:
        line = [row["keyword"], row["search_volume"] or "", "" if row["difficulty"] is None else row["difficulty"],
                row["opportunity"], row["best_competitor_position"]]
        for rival in result.competitors:
            hit = row["competitors"].get(rival)
            line += [hit["position"], hit["url"]] if hit else ["", ""]
        rows.append(line)
    return _csv_response(_csv(result.dry_run, header, rows), f"content-gap-{result.my_domain}.csv")
