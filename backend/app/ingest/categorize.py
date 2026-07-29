"""Rule-based grocery/restaurant tagging.

Deliberately a keyword and entity list, not a model. Two design notes:

1. `grocery` is the default. The overwhelming majority of FDA and FSIS recalls are
   packaged retail products, so an unmatched entity is far more likely to be a
   grocery brand than a restaurant.
2. The generic-term list is tuned for precision over recall. Words like "kitchen",
   "cafe" and a bare "grill" are intentionally absent: "Kitchen Basics" broth and
   "Cafe Bustelo" coffee are grocery brands, and matching those tokens would
   mistag them. A restaurant that only says "Joe's Grill" will fall through to
   `grocery` — an acceptable trade for not corrupting the far larger grocery set.
"""

from __future__ import annotations

import re

from app.models import CATEGORY_GROCERY, CATEGORY_RESTAURANT

# Named chains. Matched as substrings after punctuation is normalized away, so
# "McDonald's" and "McDonalds" both hit.
RESTAURANT_CHAINS = {
    "mcdonalds", "burger king", "wendys", "taco bell", "kfc", "kentucky fried chicken",
    # "chipotle" on its own is a pepper, and turns up constantly in product
    # names ("Smokey Chipotle Dry Rub"). Only the full company name counts.
    "chipotle mexican grill", "subway", "starbucks", "dunkin", "popeyes",
    "chick fil a", "panera",
    "olive garden", "applebees", "chilis", "dennys", "ihop", "sonic drive in", "arbys",
    "jack in the box", "del taco", "five guys", "shake shack", "panda express",
    "dominos", "papa johns", "pizza hut", "little caesars", "whataburger", "in n out",
    "culvers", "raising canes", "zaxbys", "bojangles", "hardees", "carls jr",
    "white castle", "dairy queen", "sbarro", "quiznos", "jimmy johns", "firehouse subs",
    "jersey mikes", "potbelly", "noodles and company", "qdoba", "moes southwest",
    "wingstop", "buffalo wild wings", "red lobster", "outback steakhouse",
    "texas roadhouse", "cracker barrel", "waffle house", "golden corral",
    "cheesecake factory", "red robin", "tgi fridays", "ruby tuesday", "longhorn",
    "bonefish", "carrabbas", "pf changs", "benihana", "hooters", "dave and busters",
    "chuck e cheese", "boston market", "el pollo loco", "captain ds", "long john silvers",
    "hardee", "checkers", "rallys", "krystal", "steak n shake", "portillos",
}

# Generic words that reliably indicate a foodservice operator rather than a brand.
RESTAURANT_TERMS = {
    "restaurant", "restaurants", "pizzeria", "steakhouse", "taqueria", "diner",
    "buffet", "eatery", "food truck", "cantina", "bistro", "brasserie", "trattoria",
    "osteria", "sushi bar", "noodle bar", "bar and grill", "bar grill", "grill house",
    "sports bar", "gastropub", "coffee shop", "ice cream shop", "sandwich shop",
    "dining", "food service establishment",
}


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation so entity matching is forgiving."""
    lowered = text.lower()
    lowered = lowered.replace("&", " and ")
    # Drop apostrophes rather than turning them into spaces, so "McDonald's"
    # normalizes to "mcdonalds" and not "mcdonald s".
    lowered = re.sub(r"['’ʼ`]", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def categorize(brand_or_chain: str, description: str = "") -> str:
    """Tag an advisory as `restaurant` or `grocery` from its entity name.

    The entity name is the primary signal; the description is only consulted for
    the explicit chain list, where a match is unambiguous.
    """
    name = _normalize(brand_or_chain)
    haystack = f" {name} "

    for chain in RESTAURANT_CHAINS:
        if f" {chain} " in haystack:
            return CATEGORY_RESTAURANT

    for term in RESTAURANT_TERMS:
        if f" {term} " in haystack:
            return CATEGORY_RESTAURANT

    # A chain named in the product/description text is still a strong signal —
    # outbreak rows often carry the chain there rather than in the entity field.
    if description:
        desc = f" {_normalize(description)} "
        for chain in RESTAURANT_CHAINS:
            if f" {chain} " in desc:
                return CATEGORY_RESTAURANT

    return CATEGORY_GROCERY
