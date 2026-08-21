#!/usr/bin/env python3
"""
Update the small stats block in README.md:
  repos     • X
  commits   • X
  issues    • X
  stars     • X

Uses GitHub GraphQL. Provide token via GH_TOKEN (preferred) or GITHUB_TOKEN.
Set USERNAME to explicitly target a username; otherwise the workflow will set it.
"""
import os
import re
import sys
import time
import requests

API = "https://api.github.com/graphql"

# GraphQL query: repositories + contributionsCollection
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
      totalCommitContributions
      totalRepositoryContributions
      totalPullRequestContributions
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
    contributions = user.get("contributionsCollection", {})
    commits_year = contributions.get("totalCommitContributions", 0)
    issues_year = contributions.get("totalIssueContributions", 0)
    return {
        "repos": total_repos,
        "commits": commits_year,
        "issues": issues_year,
        "stars": total_stars,
    }

def update_readme_file(path, stats):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # Regex matches the first block with the four lines, allowing spacing variation.
    pattern = re.compile(
        r"^(?P<prefix>.*?)(?P<section>"
        r"repos\s*[\u2022•]\s*\d+\s*\n"
        r"commits\s*[\u2022•]\s*\d+\s*\n"
        r"issues\s*[\u2022•]\s*\d+\s*\n"
        r"stars\s*[\u2022•]\s*\d+\s*\n)"
        , re.IGNORECASE | re.DOTALL | re.MULTILINE)

    # If pattern fails, attempt a more permissive single-line replacements
    m = pattern.search(text)
    if m:
        section = m.group("section")
        # Build replacement with same line endings
        repl_lines = [
            f"repos     • {stats['repos']}\n",
            f"commits   • {stats['commits']}\n",
            f"issues    • {stats['issues']}\n",
            f"stars     • {stats['stars']}\n",
        ]
        new_section = "".join(repl_lines)
        new_text = text[:m.start("section")] + new_section + text[m.end("section"):]
    else:
        # Fallback: replace each line individually (first occurrence)
        new_text = text
        replacements = [
            (r"repos\s*[\u2022•]\s*\d+", f"repos     • {stats['repos']}"),
            (r"commits\s*[\u2022•]\s*\d+", f"commits   • {stats['commits']}"),
            (r"issues\s*[\u2022•]\s*\d+", f"issues    • {stats['issues']}"),
            (r"stars\s*[\u2022•]\s*\d+", f"stars     • {stats['stars']}"),
        ]
        for pat, rep in replacements:
            new_text, n = re.subn(pat, rep, new_text, count=1, flags=re.IGNORECASE)
        if new_text == text:
            raise SystemExit("Could not find stats block in README.md to update")

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
