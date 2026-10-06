"""What the harness sends to SENTRA, and what it must not require.

The harness is a machine client of SENTRA over HTTP, and SENTRA has started
refusing things: #162 closed `/api/ingest` and `/api/feedback`, #168 graded
them by role, #191 closed the `system_prompt` field.

`sentra_admin_token` was read in `feedback` and nowhere else, so the runner
reached SENTRA anonymously while the setting read as though the whole harness
were an authenticated client. It does not need the token today — the round
posts to `/explorer/answer`, which is open, and sets no `system_prompt`. It
carries it so the next thing SENTRA enforces does not stop rounds in a way the
harness reports as SENTRA being unreachable.

**The assertion that matters is the absent one.** SENTRA leaves its guarded
endpoints open when it has no token of its own, which is the compose default and
every developer machine. A harness that required one would be enforcing a rule
SENTRA is not applying, and it would fail in the setup most people run.
"""

from sentra_eval.config import EvalSettings, sentra_headers


def _settings(**over) -> EvalSettings:
    base = {
        "judge_base_url": "http://judge.invalid/v1",
        "judge_api_key": "nicht-echt",
        "judge_model": "qwen3-8-27b",
        "chat_model_under_test": "llama-3-3-70b",
    }
    base.update(over)
    return EvalSettings(_env_file=None, **base)


class TestWithoutAToken:
    def test_nothing_is_sent(self):
        assert sentra_headers(_settings()) == {}

    def test_an_empty_string_counts_as_none(self):
        """Which is what an unset compose variable becomes — `SENTRA_ADMIN_TOKEN=`
        in an env file is the empty string, not absent. Sending
        `Authorization: Bearer ` would be refused by a SENTRA that *does* have a
        token, and refused less helpfully than sending nothing."""
        assert sentra_headers(_settings(sentra_admin_token="")) == {}


class TestWithAToken:
    def test_it_goes_in_the_authorization_header(self):
        headers = sentra_headers(_settings(sentra_admin_token="geheim"))

        assert headers == {"Authorization": "Bearer geheim"}

    def test_bearer_rather_than_x_admin_token(self):
        """Both work — `auth.has_token` reads either. Bearer is what anything
        speaking HTTP reaches for; the header is there for browser fetches."""
        headers = sentra_headers(_settings(sentra_admin_token="geheim"))

        assert "X-Admin-Token" not in headers


class TestBothClientsUseIt:
    """The point of the helper. One of two call sites is the shape a setting
    takes when it is about to be quietly wrong, so this pins that there is no
    second copy of the decision."""

    def test_the_runner_builds_its_client_with_them(self):
        import inspect

        from sentra_eval import runner

        assert "sentra_headers(settings)" in inspect.getsource(runner.execute)

    def test_and_so_does_the_feedback_reader(self):
        import inspect

        from sentra_eval import feedback

        assert "sentra_headers(settings)" in inspect.getsource(feedback.fetch)
