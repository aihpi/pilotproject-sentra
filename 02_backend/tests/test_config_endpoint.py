"""GET /api/config: the prompts and filter options the UI used to hardcode.

The frontend kept its own copy of both prompts under a comment asking whoever
edited them to keep the two in step, and its own copy of the filter options.
The options had already drifted by the time the endpoint was written.

What is guarded where is worth being exact about. The prompt duplication is
gone because the frontend copy is deleted, not because of a test: the checks
below compare the endpoint against the generator's constants, so they catch
the endpoint serving something stale or reshaped, but editing a prompt moves
both sides at once and no test here would notice. That is fine, since after
this change there is only one side.

The document-type check is the one that catches a live bug class: a value
extraction can assign but the filter does not offer, which hides those
documents without any error.

No Qdrant, no AI Hub. The endpoint is static, and the client below is built
with no dependency overrides on purpose: if it ever grows a dependency, these
tests fail rather than turning into integration tests by accident.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentra.api.routes import router
from sentra.ingestion.metadata import (
    DOCUMENT_TYPE_VALUES,
    DOCUMENT_TYPES,
    FACHBEREICH_NAMES,
    FALLBACK_DOCUMENT_TYPE,
    extract_metadata,
)
from sentra.rag.generator import DEFAULT_PROMPTS, FACHFRAGE_PROMPT, OVERVIEW_PROMPT

app = FastAPI()
app.include_router(router)


def get_config() -> dict:
    with TestClient(app) as client:
        response = client.get("/api/config")
    assert response.status_code == 200, response.text
    return response.json()


class TestPrompts:
    def test_served_verbatim(self):
        """Byte-identical to what the generator uses, not merely similar.

        The UI offers "Standard wiederherstellen" and presents the text as the
        prompt in use, so anything less than exact makes that a lie. Pins the
        endpoint to the constants; it cannot see an edit to the constants
        themselves, which now move both sides together anyway.
        """
        prompts = get_config()["prompts"]
        assert prompts["fachfrage"] == FACHFRAGE_PROMPT
        assert prompts["ueberblick"] == OVERVIEW_PROMPT

    def test_covers_every_generating_sub_mode(self):
        """The question sub-modes are fachfrage and ueberblick, both present.

        The document sub-modes generate no text and need no prompt.
        """
        assert set(get_config()["prompts"]) == {"fachfrage", "ueberblick"}

    def test_no_prompt_is_empty(self):
        """An empty string would leave the model with no instructions at all."""
        for name, text in get_config()["prompts"].items():
            assert text.strip(), f"prompt {name} is blank"


class TestDocumentTypes:
    def test_offers_every_type_extraction_can_assign(self):
        """The drift this endpoint was written to end.

        DOCUMENT_TYPES is what the extractor looks for; the value it writes
        when it finds none of them is the fallback. A filter built from the
        first list alone hides every document carrying the second, which in
        the real corpus is 221 of 1936 documents.
        """
        served = set(get_config()["document_types"])
        assert served >= set(DOCUMENT_TYPES)
        assert FALLBACK_DOCUMENT_TYPE in served

    def test_matches_the_constant(self):
        assert get_config()["document_types"] == DOCUMENT_TYPE_VALUES

    def test_extraction_cannot_produce_an_unoffered_type(self):
        """Behavioural check, so it survives the constants being rearranged.

        Runs the real extractor over a document of each recognised type and
        over one that declares no type at all, then asserts every value it
        came back with is on offer.
        """
        served = set(get_config()["document_types"])
        samples = [*DOCUMENT_TYPES, "Ein Dokument ohne jede Typangabe"]

        produced = set()
        for sample in samples:
            markdown = f"# {sample}\n\nText des Dokuments.\n"
            furniture = "WD 7 - 3000 - 001/20 (01.01.2020)"
            metadata = extract_metadata(markdown, furniture, "test.pdf")
            produced.add(metadata.document_type)

        assert produced, "extractor returned nothing to check"
        assert produced <= served, f"extraction can produce {produced - served}"


class TestReferate:
    def test_numbers_are_the_mapping_keys(self):
        """The number is the filter value, and only fachbereich_number is
        indexed in Qdrant, so these have to be the numbers and not the names.
        """
        numbers = [r["number"] for r in get_config()["referate"]]
        assert numbers == list(FACHBEREICH_NAMES)

    def test_every_referat_has_a_label(self):
        for referat in get_config()["referate"]:
            assert referat["name"].strip(), f"{referat['number']} has no name"

    def test_names_come_from_the_mapping_not_the_documents(self):
        """Deliberate: the names the documents carry are inconsistent (14
        spellings for WD 2 in the real corpus, and WD 5 and WD 8 were both
        reorganised), so the mapping is the only usable label source.
        """
        for referat in get_config()["referate"]:
            assert referat["name"] == FACHBEREICH_NAMES[referat["number"]]


class TestNoDependencies:
    def test_works_without_qdrant_or_overrides(self):
        """Built above with no dependency_overrides at all, so reaching this
        assertion is itself the check. Kept explicit so the reason is written
        down: the UI must be able to render its filters and prompt dialog even
        when the index is unreachable.
        """
        body = get_config()
        assert set(body) == {"prompts", "document_types", "referate"}
