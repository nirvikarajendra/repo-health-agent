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


class BugCloseRate(BaseModel):
    full_name: str
    days: int = Field(description="Window length in days, ending at data_as_of")
    rate: float | None = Field(
        description="Share (0-1) of counted bugs closed as completed within 30 days of creation"
    )
    bugs_counted: int | None = Field(
        description="Bug-labelled issues (not from bots) created in the window at least 30 days "
        "before data_as_of, leaving out those closed as not planned or duplicate"
    )
    bugs_fixed: int | None = Field(
        description="How many counted bugs were closed as completed within 30 days"
    )
    unfixed_bug_numbers: list[int] | None = Field(
        description="Numbers of the first 10 counted bugs not fixed within 30 days, oldest first"
    )
    labelled_bug_issues: int | None = Field(
        description="Non-PR issues with a bug label among stored issues (all open issues plus "
        "those updated in the last 365 days). Very low values mean the repo rarely labels bugs, "
        "so the rate is not reliable."
    )
    data_as_of: datetime | None = Field(description=DATA_AS_OF)
    note: str | None


class PrReviewTime(BaseModel):
    full_name: str
    days: int = Field(description="Window length in days, ending at data_as_of")
    median_hours: float | None = Field(
        description="Median hours from PR creation to the first maintainer review, based on "
        "reviewed PRs only; check prs_counted, as a median of very few PRs means little. "
        "PRs that started as drafts are timed from creation, which can make this longer than "
        "the real wait."
    )
    prs_counted: int | None = Field(
        description="Non-draft PRs created in the window by people who aren't maintainers or bots"
    )
    prs_without_review: int | None = Field(
        description="How many of the counted PRs had no formal maintainer review (comments "
        "and merges alone don't count) by data_as_of"
    )
    unreviewed_pr_numbers: list[int] | None = Field(
        description="Numbers of the first 10 unreviewed PRs, oldest first"
    )
    unreviewed_merged: int | None = Field(
        description="Unreviewed PRs (no formal review) merged by data_as_of"
    )
    unreviewed_closed_unmerged: int | None = Field(
        description="Unreviewed PRs closed without merging by data_as_of"
    )
    unreviewed_still_open: int | None = Field(
        description="Unreviewed PRs still open at data_as_of "
        "(merging or closing later doesn't count)"
    )
    data_as_of: datetime | None = Field(description=DATA_AS_OF)
    note: str | None


class ReleaseCadence(BaseModel):
    full_name: str
    latest_release_tag: str | None = Field(description="Tag of the latest counted release")
    latest_release_at: datetime | None = Field(description="When the latest release was published")
    days_since_latest_release: float | None = Field(
        description="Days from the latest release to data_as_of"
    )
    releases_last_365_days: int | None = Field(
        description="Releases published in the 365 days up to data_as_of"
    )
    median_gap_days: float | None = Field(
        description="Median days between consecutive releases among the last 5 (up to 4 gaps). "
        "A burst of quick patch releases makes this short; check days_since_latest_release "
        "and releases_last_365_days."
    )
    gaps_counted: int | None = Field(description="How many gaps the median uses (0-4)")
    recent_release_tags: list[str] | None = Field(
        description="Tags of the last 5 releases used for the gaps, oldest first"
    )
    releases_counted: int | None = Field(
        description="Published releases (not drafts or prereleases) up to data_as_of, any date"
    )
    data_as_of: datetime | None = Field(description=DATA_AS_OF)
    note: str | None


class ContributorStats(BaseModel):
    full_name: str
    days: int = Field(description="Window length in days, ending at data_as_of")
    active_contributors: int | None = Field(
        description="Distinct people (not bots) with a commit on the default branch in the window"
    )
    authors_for_half_of_commits: int | None = Field(
        description="Smallest number of people who together made at least 50% of commits_counted; "
        "1 means one person carries the project"
    )
    commits_counted: int | None = Field(
        description="Default-branch commits in the window by people (not bots) with a linked "
        "GitHub account: the base for the two numbers above"
    )
    bot_commits: int | None = Field(
        description="Commits by bots in the window, left out of the numbers above"
    )
    unattributed_commits: int | None = Field(
        description="Commits in the window with no linked GitHub account, left out of the "
        "numbers above"
    )
    data_as_of: datetime | None = Field(description=DATA_AS_OF)
    note: str | None
