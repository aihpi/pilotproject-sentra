"""The judge model, and the one thing that has to be true of it at boot."""

from dataclasses import dataclass

from sentra_eval.config import get_eval_settings


@dataclass(frozen=True)
class JudgeConfig:
    """A judge that is actually configured.

    Exists so that everything downstream gets plain strings instead of
    `str | None`. The settings carry the optionality; this is what you get once
    it has been checked, and it is checked once, at boot.
    """

    base_url: str
    api_key: str
    model: str


class MissingJudgeConfiguration(RuntimeError):
    """The harness is switched on with no judge behind it."""


def judge_config() -> JudgeConfig:
    """The judge, or a failure naming exactly what is missing.

    Reading three required settings would give a pydantic error listing three
    missing fields, which is accurate and says nothing about why they are
    wanted. This says it.
    """
    settings = get_eval_settings()
    missing = [
        name
        for name, value in (
            ("JUDGE_BASE_URL", settings.judge_base_url),
            ("JUDGE_API_KEY", settings.judge_api_key),
            ("JUDGE_MODEL", settings.judge_model),
        )
        if not value
    ]
    if missing:
        raise MissingJudgeConfiguration(
            f"EVAL_ENABLED is set but {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not. The harness needs a judge model "
            f"that is not CHAT_MODEL; see backend/.env.example."
        )
    # Narrowed by the check above, which mypy cannot see through.
    assert settings.judge_base_url and settings.judge_api_key and settings.judge_model
    return JudgeConfig(
        base_url=settings.judge_base_url,
        api_key=settings.judge_api_key,
        model=settings.judge_model,
    )
