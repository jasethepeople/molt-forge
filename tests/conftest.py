import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample_repo")


def _ensure_fixture_is_a_git_repo(path: str) -> None:
    """tests/fixtures/sample_repo must itself be a git repo with a commit --
    intake.clone_repo() clones from it. git does not track a nested .git
    directory (it would need to be a submodule), so a plain checkout of
    this repo never ships one; a fresh clone needs this bootstrap step.
    Idempotent: a no-op if the fixture already has history.
    """
    if os.path.isdir(os.path.join(path, ".git")):
        return
    env = {**os.environ, "GIT_AUTHOR_NAME": "molt-forge-fixture",
           "GIT_AUTHOR_EMAIL": "fixture@molt-forge.local",
           "GIT_COMMITTER_NAME": "molt-forge-fixture",
           "GIT_COMMITTER_EMAIL": "fixture@molt-forge.local"}
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "fixture init"], cwd=path, check=True, env=env)


_ensure_fixture_is_a_git_repo(_FIXTURE)
