"""Which category a Fachbereich's paper belongs to.

The Word template the reviewers fill in has no category column, so the
category comes from the Aktenzeichen of the paper that answers the question.
Those arrive in whatever spelling the reviewer used.
"""

import pytest

from sentra_eval.categories import KATEGORIE_NAMEN, Kategorie, category_for_fachbereich


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("WD 4", Kategorie.FI),
        ("WD 4 - 3000 - 115/22", Kategorie.FI),
        ("WD-4-113-22", Kategorie.FI),
        ("WD 5 - 3000 – 025/26", Kategorie.WI),
        ("  wd5-018-24.pdf", Kategorie.WI),
    ],
)
def test_a_known_fachbereich_has_its_category(value, expected):
    assert category_for_fachbereich(value) == expected


@pytest.mark.parametrize("value", ["WD 3 - 3000 - 058/25", "EU 6 - 3000 - 042/24", "WD 40", ""])
def test_any_other_gets_none_rather_than_a_guess(value):
    assert category_for_fachbereich(value) is None


def test_every_category_has_a_name():
    assert set(KATEGORIE_NAMEN) == set(Kategorie)
