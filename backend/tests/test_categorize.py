"""Rule-based grocery/restaurant tagging."""

import pytest

from app.ingest.base import iso_from_compact, iso_from_loose, parse_states
from app.ingest.categorize import categorize
from app.models import CATEGORY_GROCERY, CATEGORY_RESTAURANT


@pytest.mark.parametrize(
    "name",
    [
        "McDonald's",
        "McDonalds USA, LLC",
        "Chipotle Mexican Grill",
        "Taco Bell Corp.",
        "Jimmy John's Franchise LLC",
        "Dave & Buster's",
        "Panda Express, Inc.",
    ],
)
def test_named_chains_are_restaurants(name):
    assert categorize(name) == CATEGORY_RESTAURANT


@pytest.mark.parametrize(
    "name",
    [
        "Sunset Diner",
        "Luigi's Pizzeria",
        "Harbor Grill Restaurant Group",
        "El Camino Taqueria",
        "The Copper Steakhouse",
        "Midtown Bar and Grill",
    ],
)
def test_generic_foodservice_terms_are_restaurants(name):
    assert categorize(name) == CATEGORY_RESTAURANT


@pytest.mark.parametrize(
    "name",
    [
        "Acme Foods, Inc.",
        "Sunrise Meats",
        "Valley Foods",
        "Pharmatech LLC",
        "Great Lakes Cheese Co.",
    ],
)
def test_unmatched_brands_default_to_grocery(name):
    assert categorize(name) == CATEGORY_GROCERY


@pytest.mark.parametrize("name", ["Kitchen Basics", "Cafe Bustelo", "Grill Mates Seasoning"])
def test_ambiguous_grocery_brands_are_not_mistagged(name):
    # These carry foodservice-sounding words but are packaged retail brands.
    # The term list is deliberately tuned to leave them alone.
    assert categorize(name) == CATEGORY_GROCERY


def test_chain_named_only_in_the_description_still_counts():
    assert categorize("Not identified", "Illnesses linked to Panera locations") == (
        CATEGORY_RESTAURANT
    )


@pytest.mark.parametrize(
    "name",
    [
        "Hatfield Smokey Chipotle Dry Rub Seasoned Ribs",
        "Chipotle Aioli Sauce",
        "Chipotle Cheddar Sausage",
    ],
)
def test_chipotle_the_pepper_is_not_the_chain(name):
    """Chipotle is a pepper long before it is a burrito chain.

    Real FSIS product names use it constantly, so only the full company name
    "Chipotle Mexican Grill" counts as the restaurant.
    """
    assert categorize(name) == CATEGORY_GROCERY


def test_the_chipotle_chain_itself_still_counts():
    assert categorize("Chipotle Mexican Grill") == CATEGORY_RESTAURANT


def test_description_is_not_consulted_for_generic_terms():
    # "restaurant" appearing in prose is far weaker evidence than in the entity
    # name, so it must not flip a grocery brand.
    assert categorize("Acme Foods", "Sold to restaurant distributors") == CATEGORY_GROCERY


class TestParseStates:
    def test_extracts_codes_from_a_list(self):
        assert parse_states("FL, MI, MS, and OH.") == ["FL", "MI", "MS", "OH"]

    def test_nationwide_is_empty(self):
        assert parse_states("Nationwide distribution") == []
        assert parse_states("Product had national distribution.") == []

    def test_full_state_names_resolve(self):
        assert parse_states("Nebraska, Iowa, Kansas") == ["IA", "KS", "NE"]

    def test_lowercase_words_are_not_state_codes(self):
        # "in", "or" and "me" must not become Indiana, Oregon and Maine.
        assert parse_states("Shipped in or near the metro area") == []

    def test_empty_input(self):
        assert parse_states(None) == []
        assert parse_states("") == []

    def test_deduplicates_and_sorts(self):
        assert parse_states("TX, CA, TX, California") == ["CA", "TX"]


class TestDates:
    def test_compact_dates(self):
        assert iso_from_compact("20160808") == "2016-08-08"
        assert iso_from_compact(20160808) == "2016-08-08"

    def test_invalid_compact_dates(self):
        assert iso_from_compact("2016") is None
        assert iso_from_compact("notadate") is None
        assert iso_from_compact(None) is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-07-18", "2026-07-18"),
            ("7/22/2026", "2026-07-22"),
            ("2026-07-18T00:00:00", "2026-07-18"),
            ("July 18, 2026", "2026-07-18"),
        ],
    )
    def test_loose_dates(self, raw, expected):
        assert iso_from_loose(raw) == expected

    def test_unparseable_loose_date(self):
        assert iso_from_loose("sometime last week") is None
        assert iso_from_loose("") is None
