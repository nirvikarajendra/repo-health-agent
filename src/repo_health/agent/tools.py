"""The agent's tools: thin wrappers around the metric functions.

ADK sends each docstring (but not the Pydantic field descriptions) to the model, so each
wrapper's docstring ends with its model's fields, built by describe_fields(). Every wrapper
opens its own read-only connection and returns a JSON-ready dict with a "status".
"""

from collections.abc import Callable

import psycopg
from pydantic import BaseModel, ValidationError

from repo_health.db import connect
from repo_health.metrics.bug_close_rate import get_bug_close_rate as fetch_bug_close_rate
from repo_health.metrics.contributor_stats import (
    get_contributor_stats as fetch_contributor_stats,
)
from repo_health.metrics.first_response_time import (
    get_first_response_time as fetch_first_response_time,
)
from repo_health.metrics.list_repos import list_repos as fetch_repos
from repo_health.metrics.models import (
    BugCloseRate,
    ContributorStats,
    FirstResponseTime,
    PrReviewTime,
    ReleaseCadence,
    RepoOverview,
)
from repo_health.metrics.pr_review_time import get_pr_review_time as fetch_pr_review_time
from repo_health.metrics.release_cadence import get_release_cadence as fetch_release_cadence
from repo_health.metrics.repo_overview import get_repo_overview as fetch_overview


def read_only_connection() -> psycopg.Connection:
    """A connection on which Postgres refuses any write (until the read-only role exists)."""
    conn = connect()
    conn.read_only = True
    return conn


def describe_fields(model: type[BaseModel]) -> str:
    """The model's fields and their descriptions, as docstring lines for the agent."""
    lines = ["", "", "    Result fields:"]
    for name, field in model.model_fields.items():
        lines.append(
            f"        {name}: {field.description}" if field.description else f"        {name}"
        )
    return "\n".join(lines)


def issue_urls(full_name: str, numbers: list[int] | None, kind: str) -> list[str] | None:
    """GitHub links for issue (`kind="issues"`) or PR (`kind="pull"`) numbers."""
    if numbers is None:
        return None
    return [f"https://github.com/{full_name}/{kind}/{number}" for number in numbers]


# A median or rate resting on fewer items than this gets a warning.
FEW_ITEMS = 5
# Fewer bug-labelled issues than this: the repo rarely labels bugs, so the rate is shaky.
FEW_LABELLED_BUGS = 50
# The last 5 releases all within this many days: the median gap describes a burst.
BURST_DAYS = 7


def plural(count: int, word: str) -> str:
    """'1 reviewed PR', '3 reviewed PRs'."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def median_warnings(counted: int, without: int, item: str, done: str, missing: str) -> list[str]:
    """Warnings for a median over the counted items that got a response.

    `item` is what's counted ("issue"), `done` one that got a response ("answered issue"),
    `missing` the response itself ("a maintainer comment").
    """
    answered = counted - without
    if counted == 0:
        return [f"no {item}s from outside people in the window"]
    if answered == 0:
        return [f"no median: none of the {plural(counted, 'counted ' + item)} got {missing}"]
    if answered < FEW_ITEMS:
        return [f"median based on {plural(answered, done)} ({counted} counted)"]
    return []


def first_response_warnings(result: dict) -> list[str]:
    counted, without = result["issues_counted"], result["issues_without_response"]
    return median_warnings(counted, without, "issue", "answered issue", "a maintainer comment")


def pr_review_warnings(result: dict) -> list[str]:
    counted, without = result["prs_counted"], result["prs_without_review"]
    warnings = median_warnings(counted, without, "PR", "reviewed PR", "a formal review")
    if without:
        warnings.append(
            f"Of the {plural(without, 'PR')} without a maintainer review: "
            f"{result['unreviewed_merged']} were merged, "
            f"{result['unreviewed_closed_unmerged']} were closed without merging, "
            f"{result['unreviewed_still_open']} are still open."
        )
    return warnings


def bug_close_warnings(result: dict) -> list[str]:
    labelled, counted = result["labelled_bug_issues"], result["bugs_counted"]
    if labelled == 0:
        return []  # The note already says "not labelled".
    warnings = []
    if labelled < FEW_LABELLED_BUGS:
        verb = "is" if labelled == 1 else "are"
        warnings.append(
            f"only {plural(labelled, 'stored issue')} {verb} bug-labelled; rate may not be reliable"
        )
    if counted == 0:
        warnings.append("no bugs in the window, so no rate")
    elif counted < FEW_ITEMS:
        warnings.append(f"rate based on {plural(counted, 'bug')}")
    return warnings


def release_cadence_warnings(result: dict) -> list[str]:
    releases, gaps = result["releases_counted"], result["gaps_counted"]
    span = result["recent_span_days"]
    if releases == 0:
        return []  # The note already says "no GitHub releases".
    warnings = []
    if releases < FEW_ITEMS:
        warnings.append(
            f"only {plural(releases, 'release')}; median gap based on {plural(gaps, 'gap')}"
        )
    if gaps >= 2 and span < BURST_DAYS:
        warnings.append(f"median gap based on a burst: {gaps + 1} releases within {span:.1f} days")
    if result["days_since_latest_release"] is not None:
        warnings.append(
            "Days since the latest release are counted up to the data date (data_as_of), not today."
        )
    return warnings


def contributor_warnings(result: dict) -> list[str]:
    counted, unattributed = result["commits_counted"], result["unattributed_commits"]
    warnings = []
    if counted == 0:
        warnings.append("no commits by people in the window")
    elif counted < FEW_ITEMS:
        warnings.append(f"based on only {plural(counted, 'commit')}")
    if unattributed:
        warnings.append(f"{plural(unattributed, 'commit')} with no linked GitHub account left out")
    return warnings


def run_metric(
    fetch: Callable, repo: str, warn: Callable[[dict], list[str]] | None = None, **kwargs
) -> dict:
    """Run one metric; turn "not tracked" and a bad `days` into error dicts.

    On success, adds `warnings`: the metric's note, then what `warn` finds (small counts,
    bursts, few labels). With no complete snapshot there are no numbers to check.
    """
    with read_only_connection() as conn:
        try:
            result = fetch(conn, repo, **kwargs)
        except ValidationError:
            raise  # Our data doesn't fit the model: surface it, don't hide it from tests.
        except ValueError as error:  # A bad argument from the model, e.g. days out of range.
            return {"status": "error", "error_message": str(error)}
        if result is None:
            tracked = [tracked_repo.full_name for tracked_repo in fetch_repos(conn)]
            return {
                "status": "error",
                "error_message": "repo not tracked",
                "tracked_repos": tracked,
            }
    output = {"status": "success", **result.model_dump(mode="json")}
    warnings = [output["note"]] if output.get("note") else []
    if warn and output["data_as_of"] is not None:
        warnings += warn(output)
    output["warnings"] = warnings
    return output


def list_repos() -> dict:
    """List every GitHub repository the agent has data for.

    Returns:
        {"status": "success", "repos": [...]}, one entry per repo with "full_name"
        (OWNER/NAME) and "data_as_of": when that repo's data was last fully collected
        (ISO 8601, UTC), or null if it never was.
    """
    with read_only_connection() as conn:
        repos = fetch_repos(conn)
    return {"status": "success", "repos": [repo.model_dump(mode="json") for repo in repos]}


def get_repo_overview(repo: str) -> dict:
    """Get general stats for one tracked GitHub repository.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).

    Returns:
        {"status": "success", ...result fields, "warnings": [...]}. If the repo isn't tracked:
        {"status": "error", "error_message": "repo not tracked", "tracked_repos": [...]}.
    """
    return run_metric(fetch_overview, repo)


def get_first_response_time(repo: str, days: int = 90) -> dict:
    """How fast maintainers first comment on issues opened by outside people.

    Only issues are counted; GitHub Discussions are not.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).
        days: Window length in days, ending at data_as_of (1-365, default 90).

    Returns:
        {"status": "success", ...result fields, "warnings": [...],
        "unanswered_issue_urls": [...]}, where
        unanswered_issue_urls are GitHub links for unanswered_issue_numbers. Errors:
        {"status": "error", "error_message": ...}; "repo not tracked" adds "tracked_repos".
    """
    result = run_metric(fetch_first_response_time, repo, first_response_warnings, days=days)
    if result["status"] == "success":
        numbers = result["unanswered_issue_numbers"]
        result["unanswered_issue_urls"] = issue_urls(result["full_name"], numbers, "issues")
    return result


def get_bug_close_rate(repo: str, days: int = 365) -> dict:
    """Share of bug-labelled issues closed as completed within 30 days of being opened.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).
        days: Window length in days, ending at data_as_of (31-365, default 365).

    Returns:
        {"status": "success", ...result fields, "warnings": [...],
        "unfixed_bug_urls": [...]}, where
        unfixed_bug_urls are GitHub links for unfixed_bug_numbers. Errors:
        {"status": "error", "error_message": ...}; "repo not tracked" adds "tracked_repos".
    """
    result = run_metric(fetch_bug_close_rate, repo, bug_close_warnings, days=days)
    if result["status"] == "success":
        numbers = result["unfixed_bug_numbers"]
        result["unfixed_bug_urls"] = issue_urls(result["full_name"], numbers, "issues")
    return result


def get_pr_review_time(repo: str, days: int = 90) -> dict:
    """How long pull requests from outside people wait for a first formal maintainer review.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).
        days: Window length in days, ending at data_as_of (1-365, default 90).

    Returns:
        {"status": "success", ...result fields, "warnings": [...],
        "unreviewed_pr_urls": [...]}, where
        unreviewed_pr_urls are GitHub links for unreviewed_pr_numbers. Errors:
        {"status": "error", "error_message": ...}; "repo not tracked" adds "tracked_repos".
    """
    result = run_metric(fetch_pr_review_time, repo, pr_review_warnings, days=days)
    if result["status"] == "success":
        numbers = result["unreviewed_pr_numbers"]
        result["unreviewed_pr_urls"] = issue_urls(result["full_name"], numbers, "pull")
    return result


def get_release_cadence(repo: str) -> dict:
    """How recently and how often the repository publishes GitHub releases.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).

    Returns:
        {"status": "success", ...result fields, "warnings": [...]}. If the repo isn't tracked:
        {"status": "error", "error_message": "repo not tracked", "tracked_repos": [...]}.
    """
    return run_metric(fetch_release_cadence, repo, release_cadence_warnings)


def get_contributor_stats(repo: str, days: int = 365) -> dict:
    """How many people commit to the default branch, and how concentrated the work is.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).
        days: Window length in days, ending at data_as_of (1-365, default 365).

    Returns:
        {"status": "success", ...result fields, "warnings": [...]}. Errors:
        {"status": "error", "error_message": ...}; "repo not tracked" adds "tracked_repos".
    """
    return run_metric(fetch_contributor_stats, repo, contributor_warnings, days=days)


# Append each model's fields and descriptions (units, what's counted, limits) to the
# docstring the agent sees, so they're written once, in models.py.
for tool, model in [
    (get_repo_overview, RepoOverview),
    (get_first_response_time, FirstResponseTime),
    (get_bug_close_rate, BugCloseRate),
    (get_pr_review_time, PrReviewTime),
    (get_release_cadence, ReleaseCadence),
    (get_contributor_stats, ContributorStats),
]:
    tool.__doc__ += describe_fields(model)
