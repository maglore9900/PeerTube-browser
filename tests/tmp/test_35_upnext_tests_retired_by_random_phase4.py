"""Checkpoint for plan 20-35 phase 4: the devsecops selector's claims for the restored up-next groups, and the retired archive copies moved to delete_me/.

- `claimed(project, load_config())` from the skill's validate_tests.py, over the skill's own config.json, has a group for each of test_blocks.py, test_dislikes.py, test_frontend_blocks.py and test_dislike_profile.py. The first three claim engine/server/api/handlers/similar.py and engine/server/data/similarity_candidates.py, test_dislike_profile.py claims engine/server/data/ann.py, engine/server/data/similarity_candidates.py and engine/server/api/handlers/similar.py, and each still claims every path it claimed before this phase.
- tests/archive/upnext_random_draw/ does not exist, and delete_me/ holds test_similar.py, test_dislike_profile.py, test_dislikes.py, test_blocks.py, test_frontend_blocks.py and test_frontend_videos.py, each byte-identical to the retired copy the archive held.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".un" / "skills" / "devsecops" / "scripts" / "validate_tests.py"
ARCHIVE = ROOT / "tests" / "archive" / "upnext_random_draw"
DELETE_ME = ROOT / "delete_me"

SIMILAR = "engine/server/api/handlers/similar.py"
CANDIDATES = "engine/server/data/similarity_candidates.py"
ANN = "engine/server/data/ann.py"
# R7's additions per group; test_dislike_profile.py already listed similar.py, and still must.
GAINED = {
    "test_blocks.py": {SIMILAR, CANDIDATES},
    "test_dislikes.py": {SIMILAR, CANDIDATES},
    "test_frontend_blocks.py": {SIMILAR, CANDIDATES},
    "test_dislike_profile.py": {ANN, CANDIDATES, SIMILAR},
}
# What each group claimed before this phase (observed through `claimed`), so a mapping that replaces a list instead of extending it fails.
BEFORE = {
    "test_blocks.py": {"tests/active/test_blocks.py", "client/backend/server.py", "client/backend/lib/blocks.py", "client/backend/lib/users_store.py", "client/backend/lib/engine_api_client.py"},
    "test_dislikes.py": {"tests/active/test_dislikes.py", "client/backend/lib/dislikes.py", "client/backend/server.py", "client/backend/lib/users_store.py", "client/backend/lib/engine_api_client.py", "client/backend/lib/profiles.py"},
    "test_frontend_blocks.py": {"tests/active/test_frontend_blocks.py", "client/frontend/src/data/blocks.ts", "client/frontend/src/data/videos.ts", "client/frontend/src/data/search.ts", "client/frontend/src/data/profile.ts", "client/backend/server.py"},
    "test_dislike_profile.py": {"tests/active/test_dislike_profile.py", "engine/server/api/recommendations/dislike_profile.py", "engine/server/api/handlers/internal_client_reads.py", "engine/server/api/handlers/similar.py", "engine/server/api/recommendations/mixer.py", "engine/server/api/recommendations/scoring.py", "engine/server/api/recommendations/related_personalization.py", "engine/server/api/server_config.py"},
}
# SHA-256 of each retired copy as tests/archive/upnext_random_draw/ held it before the move (observed); a same-named file that is not the archive copy fails.
RETIRED = {
    "test_similar.py": "4cdc1847514c82c05021bc0a58c7aba484589715275490a69ebb5fa48dd190a2",
    "test_dislike_profile.py": "ac5017a63d04f649766274d40e600955a6c27741e48337d5404a891a5572221e",
    "test_dislikes.py": "b5d8aabdcd669fe7b747cd516a999a2b333b58af9dafa8afd291d450f7afa8c8",
    "test_blocks.py": "671bd06931980e92cf3faf652da6f4ce61f628b9640edd640e7510756bfe46be",
    "test_frontend_blocks.py": "6ba58a1f2da38ef1b168a2514274f810db0ac4af01968cb4b196b3aeb5503574",
    "test_frontend_videos.py": "0487a0117da583f1bb996b094c23db48ab4426aa4ab00620c0f38c419be0953f",
}


def _claims(monkeypatch) -> dict[str, set[str]]:
    """`claimed(ROOT, load_config())` from a fresh load of validate_tests.py over the skill's config.json, as project-relative posix paths."""
    # CONFIG is fixed at import from DEVSECOPS_CONFIG, so clear it to read the config this phase edits.
    monkeypatch.delenv("DEVSECOPS_CONFIG", raising=False)
    spec = importlib.util.spec_from_file_location("validate_tests_phase4", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CONFIG == module.SKILL_CONFIG, module.CONFIG
    return {name: {p.relative_to(ROOT).as_posix() for p in paths} for name, paths in module.claimed(ROOT, module.load_config()).items()}


def test_the_restored_upnext_groups_claim_the_engine_similarity_sources_and_keep_their_earlier_claims(monkeypatch):
    claims = _claims(monkeypatch)
    for group, gained in GAINED.items():
        # `claimed` keys only test files present in tests/active and walks only paths that exist, so a misspelt group or source drops out here.
        assert group in claims, sorted(claims)  # C1
        assert gained <= claims[group], (group, sorted(gained - claims[group]))  # C1
        assert BEFORE[group] <= claims[group], (group, sorted(BEFORE[group] - claims[group]))  # C1


def test_the_retired_upnext_archive_is_gone_and_its_six_files_are_in_delete_me():
    assert not ARCHIVE.exists(), sorted(p.name for p in ARCHIVE.iterdir()) if ARCHIVE.is_dir() else ARCHIVE  # C2
    for name, digest in RETIRED.items():
        moved = DELETE_ME / name
        assert moved.is_file(), moved  # C2
        assert hashlib.sha256(moved.read_bytes()).hexdigest() == digest, moved  # C2
