"""The label rules that need no database (#286)."""

import pytest

from sentra_eval import labels


@pytest.mark.parametrize(
    ("testart", "expected"),
    [
        ("Präzision", "PRZ"),
        ("Grenzfall · außerhalb des Bestands", "GAB"),
        ("Rechenweg", "REC"),
        ("Ökonomie", "OKO"),
        ("Ab", "ABX"),
        ("!!", "XXX"),
    ],
)
def test_every_testart_has_three_letters(testart, expected):
    assert labels.kuerzel(testart) == expected


def test_a_tag_without_a_testart_is_just_the_category():
    assert labels.tag_prefix("FI", "") == "FI"
    assert labels.tag_prefix("FI", "Synthese") == "FI-SYN"


@pytest.mark.parametrize(("value", "expected"), [("fi", "FI"), (" WD 3 ", "WD3")])
def test_a_category_is_normalised(value, expected):
    assert labels.normalise_kategorie(value) == expected


@pytest.mark.parametrize("value", ["", "W-3", "VIELZULANG9"])
def test_a_malformed_category_is_refused(value):
    with pytest.raises(labels.LabelError):
        labels.normalise_kategorie(value)


def test_every_herkunft_an_importer_writes_is_offered():
    from sentra_eval import pruefer, vorlagen

    assert {pruefer.HERKUNFT, vorlagen.HERKUNFT, "Feedback", "manuell"} <= set(labels.HERKUENFTE)
