"""Pydantic models returned by the metric tools."""

from datetime import datetime

from pydantic import BaseModel


class Metric(BaseModel):
    """One computed number, for the metric tools to come."""

    name: str
    value: float | None
    window_days: int | None
    source_tool: str


class TrackedRepo(BaseModel):
    full_name: str
    data_as_of: datetime | None  # finished_at of the latest successful sync run
