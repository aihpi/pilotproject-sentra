"""How the explorer picks which generating method to run.

_generate used to take the method as a string and reach it with getattr, so
the choice was invisible to the type checker: a typo, or renaming the method
on AnswerGenerator, type-checked clean and failed at runtime with an
AttributeError. It failed late, too, after the embedding call and the vector
search, so a mistake cost an AI Hub call before surfacing.

It now takes the bound method. These tests cover what that changed in
behavioural terms: which method each entry point dispatches to, and that
nothing is generated when there is nothing to generate from.

Offline, which is itself a consequence of the change. Passing the callable in
means these no longer need a live AnswerGenerator.
"""

from sentra.domain import Generation, Hit
from sentra.services.explorer import _generate, answer_question, generate_overview


def hit(az: str = "WD 3 - 3000 - 029/23", score: float = 0.9) -> Hit:
    return Hit(
        score=score,
        text="Ein Absatz.",
        section_title="Abschnitt",
        section_path="",
        chunk_index=0,
        aktenzeichen=az,
        fachbereich_number=az.split(" - ")[0],
        fachbereich="Fachbereich",
        document_type="Ausarbeitung",
        title=f"Titel {az}",
        completion_date="2024-01-01",
        language="de",
        source_file=f"{az}.pdf",
    )


class FakeEmbedder:
    def embed_query(self, query: str) -> list[float]:
        return [0.0, 1.0]


class FakeStore:
    def __init__(self, results: list[Hit]):
        self._results = results
        self.search_kwargs: dict | None = None

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        return self._results


class RecordingGenerator:
    """Stands in for AnswerGenerator, recording which method was called.

    Both methods take the shape the AnswerMethod protocol describes, including
    the first parameter's differing name.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, str, str | None]] = []

    def generate_answer(self, question: str, context: str, system_prompt: str | None = None):
        self.calls.append(("generate_answer", question, context, system_prompt))
        return Generation(text="eine Antwort")

    def generate_overview(self, topic: str, context: str, system_prompt: str | None = None):
        self.calls.append(("generate_overview", topic, context, system_prompt))
        return Generation(text="ein Überblick")


def call(entry_point, store, generator, **kwargs):
    return entry_point(
        kwargs.pop("query", "Welche Regeln gelten für Drohnen?"),
        None,
        None,
        5,
        store,
        FakeEmbedder(),
        generator,
        **kwargs,
    )


class TestWhichMethodIsDispatchedTo:
    """The pairing the string used to express, now expressed by the argument."""

    def test_answer_question_uses_generate_answer(self):
        generator = RecordingGenerator()
        result = call(answer_question, FakeStore([hit()]), generator)

        assert [c[0] for c in generator.calls] == ["generate_answer"]
        assert result.text == "eine Antwort"

    def test_generate_overview_uses_generate_overview(self):
        generator = RecordingGenerator()
        result = call(generate_overview, FakeStore([hit()]), generator)

        assert [c[0] for c in generator.calls] == ["generate_overview"]
        assert result.text == "ein Überblick"


class TestWhatTheMethodReceives:
    def test_gets_the_query_and_a_context_built_from_the_hits(self):
        generator = RecordingGenerator()
        call(answer_question, FakeStore([hit()]), generator, query="Meine Frage?")

        _, question, context, _ = generator.calls[0]
        assert question == "Meine Frage?"
        assert "WD 3 - 3000 - 029/23" in context
        assert "Ein Absatz." in context

    def test_custom_prompt_is_forwarded(self):
        generator = RecordingGenerator()
        call(answer_question, FakeStore([hit()]), generator, system_prompt="Sei knapp.")

        assert generator.calls[0][3] == "Sei knapp."

    def test_no_custom_prompt_stays_none(self):
        """The generator applies its own default when it gets None, so this
        must not be pre-filled with the default on the way in."""
        generator = RecordingGenerator()
        call(answer_question, FakeStore([hit()]), generator)

        assert generator.calls[0][3] is None


class TestReportedPrompt:
    """What the response says was used, which the UI shows verbatim."""

    def test_default_when_none_given(self):
        generator = RecordingGenerator()
        result = call(answer_question, FakeStore([hit()]), generator)

        assert result.system_prompt
        assert "Fachfrage" in result.system_prompt

    def test_the_custom_one_when_given(self):
        generator = RecordingGenerator()
        result = call(answer_question, FakeStore([hit()]), generator, system_prompt="Sei knapp.")

        assert result.system_prompt == "Sei knapp."


class TestNoResults:
    def test_nothing_is_generated(self):
        """No hits means no context, so calling the model would spend an AI Hub
        request to summarise nothing."""
        generator = RecordingGenerator()
        result = call(answer_question, FakeStore([]), generator)

        assert generator.calls == []
        assert result.sources == []
        assert result.text == "Es wurden keine relevanten Dokumente gefunden."

    def test_still_reports_the_prompt_that_would_have_run(self):
        generator = RecordingGenerator()
        result = call(answer_question, FakeStore([]), generator, system_prompt="Sei knapp.")

        assert result.system_prompt == "Sei knapp."


class TestAnyConformingCallable:
    """_generate takes a callable, not a generator, so it need not be a method
    of AnswerGenerator at all. This is what makes the tests above offline."""

    def test_a_plain_function_works(self):
        seen: list[tuple[str, str, str | None]] = []

        def generate(
            question: str, context: str, *, system_prompt: str | None = None
        ) -> Generation:
            seen.append((question, context, system_prompt))
            return Generation(text="aus einer Funktion")

        result = _generate(
            "Frage?",
            None,
            None,
            5,
            FakeStore([hit()]),
            FakeEmbedder(),
            generate,
            "Standardprompt",
        )

        assert result.text == "aus einer Funktion"
        assert seen[0][0] == "Frage?"

    def test_the_search_is_given_the_filters(self):
        store = FakeStore([hit()])
        generator = RecordingGenerator()
        call(
            answer_question,
            store,
            generator,
            fachbereich="WD 3",
            document_type="Ausarbeitung",
        )

        assert store.search_kwargs["fachbereich"] == "WD 3"
        assert store.search_kwargs["document_type"] == "Ausarbeitung"
        assert store.search_kwargs["top_k"] == 5
