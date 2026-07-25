import hashlib
import subprocess
from pathlib import Path

from experiments import run_day4_acceptance as day4_acceptance


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def test_day4_input_hash_uses_git_blob_and_ignores_worktree_line_endings(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    tracked = repo / "tracked.txt"
    tracked.write_bytes(b"alpha\nbeta\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "add lf file")
    commit = _git(repo, "rev-parse", "HEAD")

    lf_hash = day4_acceptance._git_blob_sha256(
        "tracked.txt",
        commit=commit,
        root=repo,
    )
    tracked.write_bytes(b"alpha\r\nbeta\r\n")
    crlf_hash = day4_acceptance._git_blob_sha256(
        "tracked.txt",
        commit=commit,
        root=repo,
    )

    assert lf_hash == crlf_hash
    assert hashlib.sha256(tracked.read_bytes()).hexdigest() != crlf_hash


def test_day4_manifest_input_hashes_rebuild_from_recorded_commit(
    tmp_path: Path,
) -> None:
    git_info = day4_acceptance._git_info()
    manifest = day4_acceptance._build_manifest(
        run_id="day4-unit",
        output_dir=tmp_path,
        command_results=[],
        passed=True,
        representative={},
        git_info=git_info,
    )

    reconstruction = manifest["input_sha256_reconstruction"]
    assert manifest["input_hash_strategy"] == day4_acceptance.INPUT_HASH_STRATEGY
    assert reconstruction["hash_strategy"] == day4_acceptance.INPUT_HASH_STRATEGY
    assert reconstruction["commit"] == git_info["commit"]
    assert reconstruction["expected_file_count"] == 12
    assert reconstruction["reconstructed_file_count"] == 12
    assert reconstruction["all_passed"] is True
    assert reconstruction["mismatches"] == []
    assert all(
        digest is not None
        for group_hashes in manifest["input_sha256"].values()
        for digest in group_hashes.values()
    )
