from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import GitHubConfig, LabelConfig
from .store import IssueSnapshot


class GitHubError(RuntimeError):
    """Raised when GitHub API calls fail."""


@dataclass(frozen=True)
class GitHubIssue:
    repo: str
    number: int
    title: str
    body: str
    url: str
    state: str
    labels: list[str]
    author: str
    updated_at: str

    def snapshot(self, labels: LabelConfig, default_task_type: str) -> IssueSnapshot:
        task_type = default_task_type
        if labels.type_code in self.labels:
            task_type = "code"
        if labels.type_research in self.labels:
            task_type = "research"
        return IssueSnapshot(
            repo=self.repo,
            number=self.number,
            title=self.title,
            url=self.url,
            state=self.state,
            labels=self.labels,
            task_type=task_type,
            body=self.body,
            author=self.author,
            updated_at=self.updated_at,
        )


class GitHubClient:
    def __init__(self, config: GitHubConfig):
        self.config = config
        self.token = os.environ.get(config.token_env)

    def list_issues(self, repo: str, labels: list[str] | None = None) -> list[GitHubIssue]:
        params = {"state": "open", "per_page": "100"}
        if labels:
            params["labels"] = ",".join(labels)
        data = self._request_json("GET", f"/repos/{repo}/issues?{urllib.parse.urlencode(params)}")
        issues: list[GitHubIssue] = []
        for item in data:
            if "pull_request" in item:
                continue
            issues.append(
                GitHubIssue(
                    repo=repo,
                    number=int(item["number"]),
                    title=item.get("title") or "",
                    body=item.get("body") or "",
                    url=item.get("html_url") or "",
                    state=item.get("state") or "open",
                    labels=[label.get("name", "") for label in item.get("labels", [])],
                    author=(item.get("user") or {}).get("login", ""),
                    updated_at=item.get("updated_at") or "",
                )
            )
        return issues

    def add_labels(self, repo: str, issue_number: int, labels: list[str]) -> None:
        self._require_token()
        self._request_json("POST", f"/repos/{repo}/issues/{issue_number}/labels", {"labels": labels})

    def remove_label(self, repo: str, issue_number: int, label: str) -> None:
        self._require_token()
        encoded = urllib.parse.quote(label, safe="")
        self._request_json(
            "DELETE", f"/repos/{repo}/issues/{issue_number}/labels/{encoded}", expect_empty=True
        )

    def create_comment(self, repo: str, issue_number: int, body: str) -> str:
        self._require_token()
        data = self._request_json("POST", f"/repos/{repo}/issues/{issue_number}/comments", {"body": body})
        return str(data.get("html_url") or "")

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expect_empty: bool = False,
    ) -> Any:
        url = self.config.api_base_url.rstrip("/") + path
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"GitHub API {method} {path} failed: {exc.reason}") from exc
        if expect_empty or not data:
            return None
        return json.loads(data.decode("utf-8"))

    def _require_token(self) -> None:
        if not self.token:
            raise GitHubError(
                f"GitHub write requires ${self.config.token_env}. "
                "Use a GitHub App installation token or a development token."
            )
