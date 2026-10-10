"""GitHub API access using standard existing authentication, without logging secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise GitHubError(code, "Authenticated API redirect refused; inspect the repository address")


def existing_token(git: Path, cwd: Path, owner: str, record: dict) -> tuple[str | None, str]:
    """Use standard token variables or Git's normal github.com credential helper."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name], name
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    command = [str(git), "-C", str(cwd), "credential", "fill"]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
    record["credential_lookup"] = {"command": command, "pid": process.pid, "host": "github.com"}
    try:
        stdout, _ = process.communicate(f"protocol=https\nhost=github.com\nusername={owner}\n\n", timeout=15)
    except subprocess.TimeoutExpired:
        record["intentional_stop_requests"].append(f"Timeout: stop owned credential lookup {process.pid}")
        process.kill()
        process.communicate()
        return None, "none"
    record["credential_lookup"]["exit_code"] = process.returncode
    # Credential-helper output and stderr may contain secrets; neither is logged.
    fields = dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)
    if process.returncode == 0 and fields.get("password"):
        return fields["password"], "Git credential helper for github.com"
    return None, "none"


class GitHub:
    def __init__(self, token: str):
        self._token = token
        self._opener = build_opener(NoRedirect())

    def request(self, method: str, endpoint: str, payload=None):
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise ValueError("GitHub API path must start with one slash")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            "https://api.github.com" + endpoint,
            data=data,
            method=method,
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "yam-tactile-kit/0.1.0",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            # Preserve only status and GitHub's short message; never request headers.
            try:
                message = json.loads(error.read()).get("message", "GitHub API request failed")
            except (ValueError, UnicodeError):
                message = "GitHub API request failed"
            raise GitHubError(error.code, str(message).replace(self._token, "[redacted]")) from None
        except URLError:
            raise GitHubError(0, "GitHub API network request failed") from None
