"""Manually submitted meets, reviewed as GitHub issues on this repo.

powerliftingrecords.com/submit-meet/ files each submission as an issue labeled
`meet-submission` whose body ends in a fenced ```json block of `Meet` fields
(see src/lib/meet-submission.ts in the site repo). A maintainer checks it,
edits the JSON if needed, and adds the `approved` label; this scraper then
publishes every approved, still-upcoming submission.

Only users with triage access can label issues, so the `approved` label is the
trust gate. Removing the label unpublishes the meet; closing the issue does not.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

from pydantic import ValidationError

from powerlifting_meets.models import Meet
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

REPO = "kdrisley/powerlifting-meet-api"
LABELS = "meet-submission,approved"
ISSUES_URL = f"https://api.github.com/repos/{REPO}/issues"
PER_PAGE = 100
MAX_PAGES = 10

_JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def meet_from_issue_body(body: str | None) -> Meet | None:
    """Parse the first ```json block of an issue body into a Meet, else None."""
    if not body:
        return None
    match = _JSON_BLOCK.search(body)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Meet.model_validate(data)
    except ValidationError:
        return None


class ManualScraper(BaseScraper):
    # meta.json key only; each meet carries its own federation code. It matches
    # no feed federation, so a failed run publishes no stale manual meets (the
    # next successful run restores them).
    federation = "MANUAL"

    def __init__(self, *args, today: date | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.today = today or date.today()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _issues(self) -> list[dict]:
        issues: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            resp = self.client.get(
                ISSUES_URL,
                params={"labels": LABELS, "state": "all", "per_page": PER_PAGE, "page": page},
                headers=self._headers(),
            )
            resp.raise_for_status()
            batch = resp.json()
            issues.extend(i for i in batch if "pull_request" not in i)
            if len(batch) < PER_PAGE:
                break
        return issues

    def scrape(self) -> list[Meet]:
        meets: list[Meet] = []
        for issue in self._issues():
            meet = meet_from_issue_body(issue.get("body"))
            if meet is None:
                logger.warning(
                    "Manual submission #%s has no valid JSON block; skipping",
                    issue.get("number"),
                )
                continue
            last_day = meet.date_end or meet.date_start
            if last_day < self.today:
                continue
            meets.append(meet)
        return meets
