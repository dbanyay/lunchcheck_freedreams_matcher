"""
Parsing and comparison of Swiss street addresses, used to decide whether a Lunch-Check restaurant
and a Freedreams hotel are the same place.

Addresses are parsed into (street name, house number) and compared structurally:
ZIP code must be equal, street names must be similar after normalisation (accents, "Strasse"/"Str.",
"Route"/"Rte", ...) and house numbers must agree. This is deliberately not a plain string comparison:
"Rte du Belvédère 20" and "Route du Belvedere 20" are the same address, "Talstrasse 43" and
"Talstrasse 45" are not.
"""
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

# Matches e.g. "43", "43a", "43-45", "43/45", "12 B" at the end of a street string
HOUSE_NUMBER_RE = re.compile(r"(?:(?<=\s)|^)(\d+)\s*([a-z]{0,3})(?:\s*[-/–]\s*(\d+)\s*([a-z]{0,3}))?\s*$")

# Abbreviation -> canonical token (applied to whole tokens)
TOKEN_ALIASES = {
    "strasse": "str", "strase": "str", "str": "str",
    "route": "rte", "rte": "rte",
    "chemin": "ch", "ch": "ch",
    "avenue": "av", "av": "av", "ave": "av",
    "place": "pl", "pl": "pl",
    "sankt": "st", "saint": "st", "sainte": "st", "san": "st", "st": "st",
    "dorf": "dorf",
}

STREET_SIMILARITY_DEFAULT = 85


@dataclass(frozen=True)
class ParsedAddress:
    street: str            # normalised street name, no spaces ("talstr")
    numbers: frozenset     # house numbers as ints; a range like 43-45 yields {43, 44, 45}
    zip_code: str          # 4 digits or ""

    @property
    def has_street(self):
        return bool(self.street)


def _strip_accents(text):
    text = text.replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_street(text):
    """Lowercases, strips accents/punctuation, canonicalises abbreviations and removes spaces."""
    text = _strip_accents(str(text).lower())
    text = re.sub(r"[^\w\s]", " ", text)
    # "Talstrasse" / "Talstr" -> "Tal str" so that all spellings end in the same token
    text = re.sub(r"(?<=[a-z])(strasse|strase|str)\b", r" str", text)
    tokens = [TOKEN_ALIASES.get(token, token) for token in text.split()]
    return "".join(tokens)


def parse_zip(value):
    match = re.search(r"\b(\d{4})\b", str(value)) if value is not None else None
    return match.group(1) if match else ""


def parse_street_address(address, zip_code=""):
    """Splits "Talstrasse 43" into a normalised street and the set of house numbers."""
    if address is None or str(address).strip().lower() in ("", "nan", "none"):
        return ParsedAddress("", frozenset(), parse_zip(zip_code))

    text = re.sub(r"\s+", " ", str(address)).strip().strip(",;")
    # Drop anything after the first comma that looks like postcode/city ("Talstrasse 43, 3905 Saas-Almagell")
    first, _, rest = text.partition(",")
    embedded_zip = parse_zip(rest)
    text = first.strip()

    numbers = frozenset()
    match = HOUSE_NUMBER_RE.search(text.lower())
    if match:
        low = int(match.group(1))
        high = int(match.group(3)) if match.group(3) else low
        if high < low or high - low > 20:   # "43-5" style typos / absurd ranges: treat as the two endpoints
            numbers = frozenset({low, high})
        else:
            numbers = frozenset(range(low, high + 1))
        text = text[: match.start()].strip()

    return ParsedAddress(normalize_street(text), numbers, parse_zip(zip_code) or embedded_zip)


def street_similarity(a, b):
    """0-100 similarity of two already normalised street names (spaces removed)."""
    if not a or not b:
        return 0
    return fuzz.ratio(a, b)


def compare_addresses(hotel, restaurant, min_street_similarity=STREET_SIMILARITY_DEFAULT):
    """
    Compares two ParsedAddress objects.

    Returns one of:
      "exact"             same ZIP, similar street, same house number
      "street_no_number"  same ZIP, similar street, but one side has no house number
      None                not the same address
    """
    if not hotel.zip_code or hotel.zip_code != restaurant.zip_code:
        return None
    if not (hotel.has_street and restaurant.has_street):
        return None
    if street_similarity(hotel.street, restaurant.street) < min_street_similarity:
        return None
    if hotel.numbers and restaurant.numbers:
        return "exact" if hotel.numbers & restaurant.numbers else None
    return "street_no_number"
