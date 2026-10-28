import json
from unittest import mock
from exorcist.tools import OneGitHubTool


def test_github_tool_is_idempotent_within_a_run():
    seen = []
    tool = OneGitHubTool(observer=lambda k, p: seen.append(p))
    with mock.patch("exorcist.one_exec.execute") as ex, mock.patch("exorcist.one_exec.run", side_effect=lambda c: c):
        ex.return_value = {"ok": True, "url": "https://github.com/o/r/issues/9", "note": ""}
        first = json.loads(tool._run("t", "b"))
        second = json.loads(tool._run("t", "b"))
    assert first["url"] == second["url"] == "https://github.com/o/r/issues/9"
    assert ex.call_count == 1 and "already" in second["note"]
    assert len(seen) == 1
