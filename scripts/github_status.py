#!/usr/bin/python3
"""Read-only check of existing GitHub authentication and the intended repository."""

import argparse
import json
from pathlib import Path
import re

from _bootstrap import ROOT
from tactile_kit.github_api import GitHub, GitHubError, existing_token
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repository", default="yam-tactile-kit")
    parser.add_argument("--git", type=Path, default=Path("/usr/bin/git"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]+", args.owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.repository):
        parser.error("Use a GitHub owner and repository name, not a URL")
    with execution(ROOT / "build/records", "Read-only authentication and repository check for the requested GitHub publication") as record:
        token, source = existing_token(args.git, ROOT, args.owner, record)
        result = {"owner": args.owner, "repository": args.repository, "credential_source": source, "authenticated": False}
        if token is None:
            result["reason"] = "No existing GitHub HTTPS credential available. An authorized GitHub connection/login is needed."
        else:
            client = GitHub(token)
            try:
                user = client.request("GET", "/user")
                result["authenticated"] = True
                result["login"] = user["login"]
                result["matches_requested_personal_account"] = user["login"].lower() == args.owner.lower()
                try:
                    repository = client.request("GET", f"/repos/{args.owner}/{args.repository}")
                    result.update({"repository_exists": True, "repository_private": repository["private"], "repository_url": repository["html_url"]})
                except GitHubError as error:
                    if error.status != 404:
                        raise
                    result["repository_exists"] = False
            except GitHubError as error:
                result.update({"api_status": error.status, "reason": str(error)})
        record.update(result)
        (ROOT / "build/github-status.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
