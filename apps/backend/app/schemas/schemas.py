from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RankTarget(BaseModel):
    """One user-nominated page and the keywords to rank-check on it.

    Nomination is what bounds quota spend: the free Google CSE tier allows 100
    queries/day and one query is one keyword on one page, so checking every
    crawled page would exhaust a day in a single audit of any real site.
    """
    url: str
    keywords: List[str] = Field(min_length=1, max_length=10)


class AuditRequestParams(BaseModel):
    url: str
    max_pages: Optional[int] = Field(default=8, ge=1, le=5000)
    max_depth: Optional[int] = Field(default=1, ge=0, le=15)
    ignore_robots: Optional[bool] = False
    enable_keyword_analysis: Optional[bool] = True
    enable_keyword_suggestions: Optional[bool] = False
    enable_rank_check: Optional[bool] = False
    enable_competitor_gap: Optional[bool] = False
    target_keywords: Optional[List[str]] = None
    rank_targets: Optional[List[RankTarget]] = None


class HealthScore(BaseModel):
    score: float
    grade: str
    critical_issues: int
    warning_issues: int
    info_issues: int
    categories: Optional[Dict[str, float]] = None


class Recommendation(BaseModel):
    code: str
    severity: str
    affected_pages: int
    example_urls: List[str]
    recommendation: str
    priority_score: float
    impact: Optional[str] = None
    estimated_effort: Optional[str] = None
    description: Optional[str] = None
    suggested_resolution: Optional[str] = None
