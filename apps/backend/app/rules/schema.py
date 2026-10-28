"""Validation of a custom rule. Declarative only: no regex, no code, no
headers -- nothing a rule can do may hang or harm the server."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional, Union

import soupsieve
from pydantic import BaseModel, Field, ValidationError, model_validator

TEXT_FIELDS = ("title", "meta_description", "h1", "canonical", "meta_robots")
NUMBER_FIELDS = ("word_count", "internal_links_count", "external_links_count")
RESPONSE_FIELDS = ("status", "response_time_ms")
TEXT_OPS = ("equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with",
            "is_empty", "is_not_empty", "length_gte", "length_lte")
NUMBER_OPS = ("eq", "gte", "lte")
VALUELESS_OPS = ("is_empty", "is_not_empty", "exists", "not_exists")
MAX_TEXT = 200


class RuleError(ValueError):
    """A rule that can't be saved, with a message fit for the user."""


def _whole_number(value: Any, what: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number")
    if number != int(number):
        raise ValueError(f"{what} must be a whole number")
    if number < 0:
        raise ValueError(f"{what} must be ≥ 0")
    return int(number)


def _number(value: Any, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if number < 0:
        raise ValueError(f"{what} must be ≥ 0")
    return int(number) if number == int(number) else number


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("needs a value")
    if len(value) > MAX_TEXT:
        raise ValueError(f"value must be at most {MAX_TEXT} characters")
    return value


class FieldCheck(BaseModel):
    type: Literal["field"]
    field: Literal[TEXT_FIELDS + NUMBER_FIELDS + RESPONSE_FIELDS]  # type: ignore[valid-type]
    op: str
    value: Optional[Union[int, float, str]] = None

    @model_validator(mode="after")
    def _check(self):
        text_field = self.field in TEXT_FIELDS
        allowed = TEXT_OPS if text_field else NUMBER_OPS
        if self.op not in allowed:
            raise ValueError(f"'{self.op}' is not valid for {self.field} (use one of: {', '.join(allowed)})")
        if self.op in VALUELESS_OPS:
            self.value = None
        elif self.value is None or self.value == "":
            raise ValueError(f"'{self.op}' needs a value")
        elif self.op in ("length_gte", "length_lte"):
            self.value = _whole_number(self.value, "value")
        elif not text_field:
            self.value = _number(self.value, "value")
        else:
            self.value = _text(self.value)
        return self


class TextCheck(BaseModel):
    type: Literal["text"]
    scope: Literal["visible", "html"] = "visible"
    op: Literal["contains", "not_contains"]
    value: str
    case_sensitive: bool = False

    @model_validator(mode="after")
    def _check(self):
        self.value = _text(self.value)
        return self


class SelectorCheck(BaseModel):
    type: Literal["selector"]
    selector: str = Field(min_length=1, max_length=MAX_TEXT)
    op: Literal["exists", "not_exists", "count_eq", "count_gte", "count_lte"]
    value: Optional[Union[int, str]] = None

    @model_validator(mode="after")
    def _check(self):
        try:
            soupsieve.compile(self.selector)
        except Exception as exc:
            first_line = (str(exc).splitlines() or [""])[0]
            raise ValueError(f"Invalid CSS selector: {first_line}")
        if self.op in VALUELESS_OPS:
            self.value = None
        elif self.value is None or self.value == "":
            raise ValueError(f"'{self.op}' needs a value")
        else:
            self.value = _whole_number(self.value, "value")
        return self


Check = Annotated[Union[FieldCheck, TextCheck, SelectorCheck], Field(discriminator="type")]


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    severity: Literal["critical", "warning", "info"] = "warning"
    message: str = Field(default="", max_length=MAX_TEXT)
    url_pattern: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    check: Check


def _readable(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error.get("loc", ()) if not isinstance(p, int))
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


def validate_rule(data: Dict[str, Any]) -> Dict[str, Any]:
    """A clean rule dict (name, enabled, severity, message, url_pattern, check),
    or RuleError with a readable reason."""
    try:
        rule = RuleIn.model_validate(data)
    except ValidationError as exc:
        raise RuleError(_readable(exc))
    out = rule.model_dump()
    out["url_pattern"] = (out["url_pattern"] or "").strip() or None
    return out
