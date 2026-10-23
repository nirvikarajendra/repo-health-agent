"""Pydantic models returned by the metric tools."""

from datetime import datetime

from pydantic import BaseModel, Field

# Shared by every model that carries data_as_of (see the repo_data_as_of view, migration 003).
DATA_AS_OF = (
    "When this repo's data was last fully collected (latest successful sync); None if never"
)


class Metric(BaseModel):
    """One computed number, reserved for the Phase 4 answer format; metric tools don't use it."""

    name: str
    value: float | None
    window_days: int | None
    source_tool: str


class TrackedRepo(BaseModel):
    full_name: str
    data_as_of: datetime | None = Field(description=DATA_AS_OF)


class RepoOverview(BaseModel):
    full_name: str
    description: str | None
    stars: int
    forks: int
    open_issues: int = Field(description="GitHub's count: open issues plus open pull requests")
    language: str | None
    license: str | None
    archived: bool
    created_at: datetime
    pushed_at: datetime | None
    has_readme: bool | None
    has_contributing: bool | None
    has_code_of_conduct: bool | None
    snapshot_at: datetime = Field(description="When these repo stats were fetched from GitHub")
    data_as_of: datetime | None = Field(description=DATA_AS_OF)


class FirstResponseTime(BaseModel):
    full_name: str
    days: int = Field(description="Window length in days, ending at data_as_of")
    median_hours: float | None = Field(
        description="Median hours from issue creation to the first maintainer comment, "
        "over answered issues only"
    )
    issues_counted: int | None = Field(
        description="Non-PR issues created in the window by people who aren't maintainers or bots"
    )
    issues_without_response: int | None = Field(
        description="How many of the counted issues had no maintainer comment by data_as_of"
    )
    unanswered_issue_numbers: list[int] | None = Field(
        description="Numbers of the first 10 unanswered issues, oldest first"
    )
    unanswered_closed_completed: int | None = Field(
        description="Unanswered issues closed as completed (or with no reason) by data_as_of"
    )
    unanswered_closed_not_planned: int | None = Field(
        description="Unanswered issues closed as not planned by data_as_of (includes duplicates)"
    )
    unanswered_still_open: int | None = Field(
        description="Unanswered issues still open at data_as_of (closing later doesn't count)"
    )
    data_as_of: datetime | None = Field(description=DATA_AS_OF)
    note: str | None
