#!/usr/bin/env python3
"""
Update the stats block in README.md to show:
  repos     • X
  contribs     • X
  issues    • X
  stars     • X

Removes any existing 'commits' line. Uses GH_TOKEN (preferred) or GITHUB_TOKEN.
Set USERNAME to explicitly target a username; otherwise the workflow will set it.
"""
import os
import re
import sys
import time
import requests

API = "https://api.github.com/graphql"

REPO_NODE_FIELDS = """
  name
  isPrivate
  stargazerCount
  forkCount
  primaryLanguage { name color }
"""

REPOS_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    login
    name
    repositories(first: 100, after: $after, ownerAffiliations: OWNER) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        %s
      }
    }
    contributionsCollection {
      contributionCalendar { totalContributions }
      totalIssueContributions
    }
  }
}
""" % REPO_NODE_FIELDS

MARKER_START = "<!-- STATS START -->"
MARKER_END = "<!-- STATS END -->"

def get_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: set GH_TOKEN or GITHUB_TOKEN in environment", file=sys.stderr)
        sys.exit(1)
    return token

def graphql_query(token, query, variables=None):
    headers = {"Authorization": f"bearer {token}"}
    resp = requests.post(API, json={"query": query, "variables": variables or {}}, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise SystemExit(f"GraphQL query failed: {resp.status_code} {resp.text}")
    payload = resp.json()
    if payload.get("errors"):
        raise SystemExit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]

def collect_repos(token, login):
    repos = []
    after = None
    total_count = 0
    while True:
        data = graphql_query(token, REPOS_QUERY, {"login": login, "after": after})
        user = data.get("user")
        if not user:
            raise SystemExit("User not found or token lacks permission")
        batch = user["repositories"]["nodes"]
        repos.extend(batch)
        page = user["repositories"]["pageInfo"]
        total_count = user["repositories"]["totalCount"]
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]
    return user, repos, total_count

def compute_stats(user, repos, total_count):
    total_repos = total_count if total_count is not None else len(repos)
    total_stars = sum((r.get("stargazerCount") or 0) for r in repos)
    contributions_total = 0
    contributions_coll = user.get("contributionsCollection", {})
    if contributions_coll:
        cal = contributions_coll.get("contributionCalendar")
        if cal:
            contributions_total = cal.get("totalContributions", 0)
    issues_year = contributions_coll.get("totalIssueContributions", 0)
    return {
        "repos": total_repos,
        "contribs": contributions_total,
        "issues": issues_year,
        "stars": total_stars,
    }

def build_stats_block(stats):
    lines = [
        MARKER_START,
        f"repos     • {stats['repos']}",
        f"contribs     • {stats['contribs']}",
        f"issues    • {stats['issues']}",
        f"stars     • {stats['stars']}",
        MARKER_END,
    ]
    return "\n".join(lines) + "\n"

def update_readme_with_markers(text, stats):
    block = build_stats_block(stats)
    marker_regex = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)
    if marker_regex.search(text):
        new_text = marker_regex.sub(block.strip() + "\n", text, count=1)
        return new_text, True
    return text, False

def fallback_update(text, stats):
    # Remove any 'commits' line
    commits_line_pat = re.compile(r"^\s*commits\s*[\u2022•]\s*\d+\s*$\n?", re.IGNORECASE | re.MULTILINE)
    text = commits_line_pat.sub("", text)

    # Try to insert contribs (or contributions) after repos line if missing
    repo_pat = re.compile(r"(^.*?repos\s*[\u2022•]\s*\d+.*?$)", re.IGNORECASE | re.MULTILINE)
    contribs_existing_pat = re.compile(r"(contribs|contributions)\s*[\u2022•]\s*\d+", re.IGNORECASE)
    if repo_pat.search(text) and not contribs_existing_pat.search(text):
        def insert_after_repo(match):
            repo_line = match.group(1)
            return repo_line + "\ncontribs     • %d" % stats["contribs"]
        text = repo_pat.sub(insert_after_repo, text, count=1)

    # Replace/update the lines (first occurrence). Accept both old and new labels for matching,
    # but write the "contribs" label.
    replacements = [
        (r"repos\s*[\u2022•]\s*\d+", f"repos     • {stats['repos']}"),
        (r"(contribs|contributions)\s*[\u2022•]\s*\d+", f"contribs     • {stats['contribs']}"),
        (r"issues\s*[\u2022•]\s*\d+", f"issues    • {stats['issues']}"),
        (r"stars\s*[\u2022•]\s*\d+", f"stars     • {stats['stars']}"),
    ]
    new_text = text
    for pat, rep in replacements:
        new_text, n = re.subn(pat, rep, new_text, count=1, flags=re.IGNORECASE)
    changed = new_text != text
    return new_text, changed

def update_readme_file(path, stats):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # 1) Prefer marker replacement
    new_text, changed = update_readme_with_markers(text, stats)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return True

    # 2) Fallback to regex-based replacement (legacy)
    new_text, changed = fallback_update(text, stats)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return True

    # 3) Nothing matched: tell the user exactly what to paste
    print("Could not find target area in README.md to update.", file=sys.stderr)
    print("Add the following block somewhere appropriate in your README (then re-run):\n")
    print(build_stats_block(stats))
    return False

def main():
    token = get_token()
    explicit_user = os.environ.get("USERNAME")
    actor = os.environ.get("GITHUB_ACTOR")
    login = explicit_user or actor
    if not login:
        print("Error: set USERNAME or run inside Actions where GITHUB_ACTOR is present", file=sys.stderr)
        sys.exit(1)

    user, repos, total_count = collect_repos(token, login)
    stats = compute_stats(user, repos, total_count)

    readme_path = os.path.join(os.getcwd(), "README.md")
    if not os.path.exists(readme_path):
        raise SystemExit("README.md not found in repository root")

    changed = update_readme_file(readme_path, stats)
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    if changed:
        print(f"README.md updated with stats: {stats} (at {now})")
        sys.exit(0)
    else:
        print("No update performed. See instructions above.", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
