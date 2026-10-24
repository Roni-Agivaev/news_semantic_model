"""
Start the Kan News GitHub Actions workflow (.github/workflows/kan-daily.yml) on demand.

Needs GITHUB_TOKEN: a fine-grained personal access token limited to this
repository with "Actions: Read and write". Without it, Kan only runs on its
nightly schedule.
"""
import json
import os
import urllib.error
import urllib.request

REPO = "Roni-Agivaev/news_semantic_model"
WORKFLOW = "kan-daily.yml"


def start_kan_workflow():
    """Returns (started, message)."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return False, "not configured (GITHUB_TOKEN not set); Kan runs with the nightly schedule"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        data=json.dumps({"ref": "main"}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "news-semantic-model-dashboard",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True, "started on GitHub; results in about 1-2 minutes"
    except urllib.error.HTTPError as e:
        return False, f"GitHub refused the request (HTTP {e.code}); check GITHUB_TOKEN"
    except Exception as e:
        return False, f"could not reach GitHub ({type(e).__name__})"
