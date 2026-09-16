"""The judge model, and the one thing that has to be true of it at boot."""

from sentra.evaluation.config import get_eval_settings


class JudgeNotIndependent(RuntimeError):
    """The judge is configured as the model it is supposed to be checking.

    Raised at startup rather than on the first comparison. A round costs about
    180 generation calls; discovering afterwards that every consistency verdict
    was the model grading itself would mean discarding the lot.
    """


def assert_judge_is_independent(chat_model: str) -> None:
    """Refuse to start when the judge and SENTRA are the same model.

    A name comparison, which is as far as configuration can go. It does not
    catch a hub that serves two names from one model — that needs the served
    model id back on each response, which SENTRA does not report yet.
    """
    judge_model = get_eval_settings().judge_model
    if judge_model == chat_model:
        raise JudgeNotIndependent(
            f"JUDGE_MODEL and CHAT_MODEL are both {chat_model!r}. The judge has to be a "
            f"different model, or its verdicts only say that SENTRA agrees with itself."
        )
