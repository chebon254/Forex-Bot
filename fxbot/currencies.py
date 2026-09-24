"""The eight currencies in the strategy and how each one maps to outside data."""

# Market quoting order: whichever currency comes first is the base (EURUSD, GBPJPY, AUDNZD...).
PRIORITY = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")

# CFTC contract codes (Legacy COT report). USD uses the ICE Dollar Index, the same
# contract Barchart shows for the dollar.
CFTC_CODES = {
    "EUR": "099741",  # Euro FX, CME
    "GBP": "096742",  # British Pound, CME
    "AUD": "232741",  # Australian Dollar, CME
    "NZD": "112741",  # NZ Dollar, CME
    "USD": "098662",  # USD Index, ICE
    "CAD": "090741",  # Canadian Dollar, CME
    "CHF": "092741",  # Swiss Franc, CME
    "JPY": "097741",  # Japanese Yen, CME
}

# Bank for International Settlements reference areas for central bank policy rates.
BIS_AREAS = {
    "EUR": "XM",
    "GBP": "GB",
    "AUD": "AU",
    "NZD": "NZ",
    "USD": "US",
    "CAD": "CA",
    "CHF": "CH",
    "JPY": "JP",
}

# FRED daily noon rates against the dollar: (series id, True if quoted as USD per unit).
FRED_SERIES = {
    "EUR": ("DEXUSEU", True),
    "GBP": ("DEXUSUK", True),
    "AUD": ("DEXUSAL", True),
    "NZD": ("DEXUSNZ", True),
    "CAD": ("DEXCAUS", False),
    "CHF": ("DEXSZUS", False),
    "JPY": ("DEXJPUS", False),
}


def all_pairs() -> list[str]:
    """The 28 pairs, named the way brokers quote them."""
    return [a + b for i, a in enumerate(PRIORITY) for b in PRIORITY[i + 1 :]]


def pair_name(a: str, b: str) -> str:
    """Broker symbol for two currencies in either order: ('JPY', 'GBP') -> 'GBPJPY'."""
    base, quote = sorted((a, b), key=PRIORITY.index)
    return base + quote


def split(symbol: str) -> tuple[str, str]:
    return symbol[:3], symbol[3:6]


def pip_size(symbol: str) -> float:
    return 0.01 if symbol[3:6] == "JPY" else 0.0001
