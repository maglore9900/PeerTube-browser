"""Probe: run the phase-4 checkpoint's scenarios against mutants of pages/search/index.ts bundled from stdin, leaving the source tree untouched."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("phase4", HERE / "test_40_search_card_actions_phase4.py")
p4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p4)

SOURCE = p4.ENTRY.read_text()
GUARD = '''  button.disabled = true;
  say("");'''
LIKE_SEND = '''      await sendReaction(apiBase, liked ? "undo_like" : "like", { uuid, host });
      row.reaction = liked ? null : "liked";'''
BLOCK_SEND = '''      const block = await blockVideoSource(apiBase, action, uuid, host);'''
MUTANTS = {
    "current": [],
    "guarded": [(GUARD, '''  if (action !== "like" && !getProfileKey()) {
    say(`${action === "dislike" ? "Disliking" : "Blocking"} needs a profile. Create one from the Profile button.`);
    return;
  }
''' + GUARD), ('import { ProfileKeyRejectedError } from "../../data/profile";', 'import { ProfileKeyRejectedError, getProfileKey } from "../../data/profile";')],
    "optimistic_dislike": [('''      await sendReaction(apiBase, disliked ? "undo_dislike" : "dislike", { uuid, host });
      row.reaction = disliked ? null : "disliked";''', '''      row.reaction = disliked ? null : "disliked";
      await sendReaction(apiBase, disliked ? "undo_dislike" : "dislike", { uuid, host });''')],
    "optimistic_like": [(LIKE_SEND, '''      row.reaction = liked ? null : "liked";
      await sendReaction(apiBase, liked ? "undo_like" : "like", { uuid, host });''')],
    "optimistic_like_redraw": [(LIKE_SEND + '''
      // A reset during the request detaches the card, and outerHTML on a detached node throws.
      if (card.isConnected) card.outerHTML = renderSearchCard(row);''', '''      row.reaction = liked ? null : "liked";
      if (card.isConnected) card.outerHTML = renderSearchCard(row);
      await sendReaction(apiBase, liked ? "undo_like" : "like", { uuid, host });''')],
    "block_flips_row": [(BLOCK_SEND, '''      row.reaction = "disliked";
''' + BLOCK_SEND)],
    "block_removes_first": [(BLOCK_SEND, '''      removeRows((candidate) => String(candidate.channel_id ?? "") === String(row.channel_id ?? ""));
''' + BLOCK_SEND)],
    "reject_clears_row": [('''    say(error instanceof Error ? error.message : "Action failed");''', '''    row.reaction = null;
    say(error instanceof Error ? error.message : "Action failed");''')],
    "no_reenable": [('''  } finally {
    button.disabled = false;
  }''', '''  } finally {
  }''')],
    "generic": [('say(error instanceof Error ? error.message : "Action failed");', 'say("Action failed");')],
}
REJECTED = [("like", 404, p4.NOT_FOUND_ERROR), ("dislike", 400, p4.LIMIT_ERROR), ("channel", 400, p4.BLOCK_LIMIT_ERROR), ("account", 400, p4.BLOCK_LIMIT_ERROR)]


def _line(error: BaseException) -> str:
    tb = error.__traceback__
    while tb.tb_next:
        tb = tb.tb_next
    return f"FAIL {type(error).__name__} line {tb.tb_lineno}"


@pytest.mark.parametrize("name", list(MUTANTS))
def test_probe(name, tmp_path):
    source = SOURCE
    for old, new in MUTANTS[name]:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    run = subprocess.run(
        [str(p4.ESBUILD), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", "--loader=ts", f"--outfile={tmp_path / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(p4.BASE)}", "--define:import.meta.env.DEV=false"],
        input=source, capture_output=True, text=True, cwd=p4.ENTRY.parent,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (tmp_path / "runner.mjs").write_text(p4.RUNNER)
    results = {}
    for action, prompt in [("dislike", "Disliking"), ("channel", "Blocking"), ("account", "Blocking")]:
        try:
            p4.test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing(tmp_path, action, f"{prompt} needs a profile. Create one from the Profile button.")
            results[f"C1-{action}"] = "pass"
        except (AssertionError, TypeError) as error:
            results[f"C1-{action}"] = _line(error)
    for action, status, error_text in REJECTED:
        for reaction, mark, like in [(None, p4.NEUTRAL, "like"), ("liked", p4.LIKED, "undo_like")]:
            try:
                p4.test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction(tmp_path, action, status, error_text, reaction, mark, like)
                results[f"C2-{action}-{reaction}"] = "pass"
            except (AssertionError, TypeError) as error:
                results[f"C2-{action}-{reaction}"] = _line(error)
    print(f"\nPROBE {name}: {json.dumps(results)}")
