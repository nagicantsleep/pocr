"""Regression guard for the browser console proof contract."""

from pathlib import Path


def test_console_shortcuts_keep_the_observed_workflow_contract():
    script = (Path(__file__).parents[1] / "app" / "web" / "review.js").read_text(
        encoding="utf-8"
    )

    for shortcut, action in {
        "case 'r':": "reject();",
        "case 'j':": "selectDocument(currentIndex + 1);",
        "case 'k':": "selectDocument(currentIndex - 1);",
        "case 'p':": "openPatchModal();",
    }.items():
        assert shortcut in script
        assert action in script

    assert "e.key === 'Enter' && (e.ctrlKey || e.metaKey)" in script
    assert "confirmAction();" in script
    assert "submitPatch();" in script
    assert "document.getElementById('patchReason').value" in script
    assert "prompt(" not in script
