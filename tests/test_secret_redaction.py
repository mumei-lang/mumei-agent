"""Tests for removing secret values before LLM prompts and reports."""
from __future__ import annotations

import json

import pytest

from agent.body_port import BodyPorter
from agent.secret_redaction import REDACTED, redact_secrets, redact_value, sensitive_env_values

SENTINEL = "fake-sentinel-value-0123456789"


@pytest.mark.parametrize("source", [
    'API_KEY = "fake-sentinel-value-0123456789"',
    "api_key: str = 'fake-sentinel-value-0123456789'",
    'const authToken = "fake-sentinel-value-0123456789";',
    'let db_password = `fake-sentinel-value-0123456789`;',
    'secret := "fake-sentinel-value-0123456789"',
    'string private constant ownerPrivateKey = "fake-sentinel-value-0123456789";',
    'let client_secret: &str = "fake-sentinel-value-0123456789";',
    '{"apiKey": "fake-sentinel-value-0123456789"}',
])
def test_redacts_string_literals_assigned_to_credential_names(source):
    out = redact_secrets(source)
    assert SENTINEL not in out and REDACTED in out


@pytest.mark.parametrize("token", [
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "ghp_" + "a" * 36,
    "github_pat_" + "A1" * 20,
    "sk-" + "x" * 32,
    "xoxb-" + "1234567890-abcdef",
    "AIza" + "b" * 35,
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVl",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEfake\n-----END RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----\nMIIfake\n-----END PRIVATE KEY-----",
])
def test_redacts_provider_token_formats_anywhere(token):
    out = redact_secrets(f"call({token!r})  # {token}")
    assert token not in out and out.count(REDACTED) == 2


def test_redacts_sensitive_environment_values_only():
    env = {"LLM_API_KEY": SENTINEL, "LLM_MODEL": "plain-model-name"}
    assert sensitive_env_values(env) == [SENTINEL]
    out = redact_secrets(f"x = {SENTINEL}; model plain-model-name", environ=env)
    assert SENTINEL not in out and "plain-model-name" in out


def test_short_values_count_but_only_as_whole_tokens():
    assert sensitive_env_values({"LLM_API_KEY": "abc", "GITHUB_TOKEN": ""}) == ["abc"]
    assert redact_secrets("a + abcd", environ={"LLM_API_KEY": "abc"}) == "a + abcd"


def test_extra_values_are_redacted():
    assert redact_secrets(f"value {SENTINEL}", extra_values=[SENTINEL], environ={}) == f"value {REDACTED}"


@pytest.mark.parametrize("source", [
    "def clamp(x, hi):\n    return hi if x > hi else x\n",
    'token_count = len(tokens)',
    'password_min_length = 12',
    'if auth is None: raise ValueError("missing")',
    'secret = os.environ["APP_SECRET"]',
    'name = "fake-sentinel-value-0123456789"',
    'api_key = ""',
    'skip = "sk-short"',
])
def test_leaves_ordinary_code_alone(source):
    assert redact_secrets(source, environ={}) == source


def test_redaction_is_idempotent():
    once = redact_secrets(f'API_KEY = "{SENTINEL}"', environ={})
    assert redact_secrets(once, environ={}) == once


def test_redact_value_walks_nested_structures():
    value = {"x": [f"k {SENTINEL}", 3, (SENTINEL,)], SENTINEL: True, "n": None}
    out = redact_value(value, extra_values=[SENTINEL], environ={})
    assert SENTINEL not in json.dumps(out) and out["x"][1] == 3 and out["n"] is None
    assert isinstance(out["x"][2], tuple)


class _Client:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []
        self.chat = type("C", (), {"completions": type("P", (), {"create": self._create})()})()

    def _create(self, *, model, messages):
        self.prompts.append(messages)
        msg = type("M", (), {"content": self.reply})()
        return type("R", (), {"choices": [type("Ch", (), {"message": msg})()]})()


class _Mumei:
    def __init__(self, verification):
        self.verification = verification

    def verify(self, path, report_dir=None, extra_args=None):
        return self.verification


CLAMP = {"name": "clamp", "params": [{"name": "x", "type": "i64"}, {"name": "hi", "type": "i64"}],
         "return_type": "i64", "requires": "hi >= 0", "ensures": "result <= hi"}
GO_CLAMP = (
    "func clamp(x int64, hi int64) int64 {\n"
    f'\tapiKey := "{SENTINEL}"\n\t_ = apiKey\n'
    "\tif x > hi {\n\t\treturn hi\n\t}\n\treturn x\n}\n"
)


def _port(reply, verification, monkeypatch, env_value=None):
    if env_value is not None:
        monkeypatch.setenv("LLM_API_KEY", env_value)
    client = _Client(reply)
    (entry,) = BodyPorter(client, "m", _Mumei(verification)).port(GO_CLAMP, "go", {"atoms": [CLAMP]})
    return client, entry


def test_body_port_prompt_never_carries_a_source_secret(monkeypatch):
    client, _ = _port('{"body": "x"}', {"success": True, "report": {"status": "success"}}, monkeypatch)
    prompt = json.dumps(client.prompts)
    assert SENTINEL not in prompt and REDACTED in prompt and "if x > hi" in prompt


def test_body_port_entry_never_carries_a_sensitive_env_value(monkeypatch):
    env_value = "fake-env-sentinel-9876543210"
    verification = {
        "success": False,
        "report": {
            "status": "failed",
            "diagnostics": [{"message": f"Postcondition violated near {env_value}"}],
            "counterexample": {"x": env_value, "hi": 0, env_value: 1},
        },
    }
    _, entry = _port(json.dumps({"body": f'if x > {env_value.count("-")} {{ x }} else {{ x }}'}),
                     verification, monkeypatch, env_value=env_value)
    assert env_value not in json.dumps(entry)


def test_body_port_entry_redacts_a_secret_echoed_in_the_body(monkeypatch):
    env_value = "fake-env-sentinel-9876543210"
    _, entry = _port(json.dumps({"body": f"x + 0 // {env_value}"}),
                     {"success": True, "report": {"status": "success"}}, monkeypatch, env_value=env_value)
    assert env_value not in json.dumps(entry)


@pytest.mark.parametrize("source", [
    'password = "hello\\"fake-sentinel-value-0123456789"',
    "token = 'it\\'s fake-sentinel-value-0123456789'",
    'secret = "it\'s fake-sentinel-value-0123456789"',
])
def test_redaction_covers_escaped_and_mixed_quotes(source):
    assert SENTINEL not in redact_secrets(source)


def test_short_sensitive_env_value_is_redacted_as_a_whole_token():
    environ = {"LLM_API_KEY": "fk42"}
    assert redact_secrets("key=fk42 end", environ=environ) == f"key={REDACTED} end"
    assert redact_secrets("fk425 xfk42", environ=environ) == "fk425 xfk42"


def test_redacted_counterexample_keys_keep_every_value():
    environ = {"LLM_API_KEY": "fake-env-sentinel-aaaa", "GITHUB_TOKEN": "fake-env-sentinel-bbbb"}
    out = redact_value({"fake-env-sentinel-aaaa": 1, "fake-env-sentinel-bbbb": 2}, environ=environ)
    assert sorted(out.values()) == [1, 2]
    assert "sentinel" not in json.dumps(out)


def test_body_port_prompt_redacts_other_atoms_contracts(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", SENTINEL)
    other = {**CLAMP, "name": "helper", "requires": f'x != "{SENTINEL}"'}
    client = _Client('{"body": "x"}')
    BodyPorter(client, "m", _Mumei({"success": True, "report": {"status": "success"}})).port(
        GO_CLAMP, "go", {"atoms": [CLAMP, other]}
    )
    assert SENTINEL not in json.dumps(client.prompts)


def test_body_port_never_writes_an_echoed_secret_to_the_module(monkeypatch):
    env_value = "fake-env-sentinel-9876543210"
    monkeypatch.setenv("LLM_API_KEY", env_value)
    written = []

    class _Reading(_Mumei):
        def verify(self, path, report_dir=None, extra_args=None):
            written.append(open(path, encoding="utf-8").read())
            return self.verification

    helper = {**CLAMP, "name": "helper", "requires": f'x != "{env_value}"'}
    BodyPorter(_Client(json.dumps({"body": f"helper(x, hi) + 0 // {env_value}"})), "m",
               _Reading({"success": True, "report": {"status": "success"}})).port(
        GO_CLAMP, "go", {"atoms": [CLAMP, helper]}
    )
    assert written and "helper" in written[0] and all(env_value not in w for w in written)
