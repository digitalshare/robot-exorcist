from exorcist.one_exec import _first_action_id, _extract_url, _looks_ok, _find_connection

MD = """## slack: post a message to a channel\n\nChosen with confidence 1.00.\n\n### Send a Message (chat.postMessage) · `POST /chat.postMessage` · actionId: `conn_mod_def::AAA::slack1`\n\nbody...\n\n## github: create an issue in a repository\n\n### Create an issue · actionId: `conn_mod_def::BBB::gh1`\n"""


def test_action_id_per_platform_from_markdown():
    assert _first_action_id(MD, "slack") == "conn_mod_def::AAA::slack1"
    assert _first_action_id(MD, "github") == "conn_mod_def::BBB::gh1"
    assert _first_action_id(MD) == "conn_mod_def::AAA::slack1"


def test_connection_lookup():
    integrations = {"connections": [{"platform": "slack", "key": "live::slack::default::1"}, {"platform": "github", "key": "live::github::default::2"}]}
    assert _find_connection(integrations, "github") == "live::github::default::2"
    assert _find_connection(integrations, "gmail") is None


def test_urls_and_ok():
    slack = {"responseData": {"ok": True, "channel": "C1", "ts": "1793223013.632049", "message": {"team": "T1"}}, "status": 200}
    assert _looks_ok(slack) and _extract_url(slack, "slack") == "https://app.slack.com/client/T1/C1/p1793223013632049"
    gh = {"responseData": {"html_url": "https://github.com/o/r/issues/7", "number": 7}, "status": 201}
    assert _looks_ok(gh) and _extract_url(gh, "github") == "https://github.com/o/r/issues/7"
    bad = {"responseData": {"ok": False, "error": "channel_not_found"}, "status": 200}
    assert not _looks_ok(bad)
