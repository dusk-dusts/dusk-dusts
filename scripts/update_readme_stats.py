#!/usr/bin/env python3
"""
Update the stats block in README.md to show:
  repos     • X
  contributions     • X
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
      contributionCalendar {
        totalContributions
      }
      totalIssueContributions
    }
  }
}
""" % REPO_NODE_FIELDS

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
        "contributions": contributions_total,
        "issues": issues_year,
        "stars": total_stars,
    }

def update_readme_file(path, stats):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # Find repo line to anchor insertion
    repo_pat = re.compile(r"(^.*?repos\s*[\u2022•]\s*\d+.*?$)", re.IGNORECASE | re.MULTILINE)
    if not repo_pat.search(text):
        raise SystemExit("Could not find 'repos' line to anchor updates in README.md")

    # Remove existing 'commits' line(s)
    commits_line_pat = re.compile(r"^\s*commits\s*[\u2022•]\s*\d+\s*$\n?", re.IGNORECASE | re.MULTILINE)
    text = commits_line_pat.sub("", text)

    # Insert contributions line if missing (after the first repos line)
    contributions_pat = re.compile(r"contributions\s*[\u2022•]\s*\d+", re.IGNORECASE)
    if not contributions_pat.search(text):
        # Insert after the first repos line (preserve same indentation/spaces)
        def insert_after_repo(match):
            repo_line = match.group(1)
            return repo_line + "\ncontributions     • %d" % stats["contributions"]
        text = repo_pat.sub(insert_after_repo, text, count=1)

    # Replace/update the four lines (repos, contributions, issues, stars) - first occurrence
    replacements = [
        (r"repos\s*[\u2022•]\s*\d+", f"repos     • {stats['repos']}"),
        (r"contributions\s*[\u2022•]\s*\d+", f"contributions     • {stats['contributions']}"),
        (r"issues\s*[\u2022•]\s*\d+", f"issues    • {stats['issues']}"),
        (r"stars\s*[\u2022•]\s*\d+", f"stars     • {stats['stars']}"),
    ]

    new_text = text
    for pat, rep in replacements:
        new_text, n = re.subn(pat, rep, new_text, count=1, flags=re.IGNORECASE)
    if new_text == text:
        raise SystemExit("Could not find/update stats lines in README.md")
    if new_text != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return True
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
        print(f"No changes needed (stats: {stats})")
        sys.exit(0)

if __name__ == "__main__":
    main()
