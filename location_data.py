"""
location_data.py — Reads the local country / state / place hierarchy.

The data lives in data/locations.json (see the "_about" note inside it).
This module only READS that file and answers questions such as "which
states does Nigeria have?" and "which LGAs are in the FCT?". It never talks
to the internet, so the dropdowns work offline and instantly.

Shape of the file (a dictionary of dictionaries):

    {"countries": {
        "Nigeria": {
            "code": "NG",
            "state_label": "State",
            "place_label": "City / LGA",
            "states": {
                "Lagos": {
                    "capital": "Ikeja",
                    "aliases": [],
                    "places": ["Agege", "Ikeja", ...],
                    "coordinates": {"Ikeja": [6.602, 3.352]}   # optional
                }}}}}
"""

import json
import os

from babel import Locale

from exceptions import WeatherDataError

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "locations.json")

# A few of Babel's 2-letter codes are groups of countries, not real places.
_NON_COUNTRY_CODES = {"EU", "UN", "ZZ", "QO"}


def load_location_data(path: str = DATA_FILE) -> dict:
    """Read the JSON file. Raises WeatherDataError with a clear message if the
    file is missing, unreadable, or not shaped as expected."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise WeatherDataError(f"Location data file not found: {path}")
    except (json.JSONDecodeError, OSError) as e:
        raise WeatherDataError(f"Location data file could not be read ({e}).")

    if not isinstance(data, dict) or not isinstance(data.get("countries"), dict):
        raise WeatherDataError("Location data file is missing its 'countries' section.")
    return data


def build_country_list() -> list:
    """Sorted list of (country_name, iso_code) for EVERY country, from Babel's
    built-in ISO data (no download needed)."""
    locale = Locale("en")
    countries = [
        (name, code)
        for code, name in locale.territories.items()
        if len(code) == 2 and code.isalpha() and code not in _NON_COUNTRY_CODES
    ]
    countries.sort(key=lambda c: c[0])
    return countries


def has_country_data(data: dict, country: str) -> bool:
    """True if our JSON file has states/places for this country."""
    return country in data.get("countries", {})


def get_country_code(data: dict, country: str):
    """ISO code (like "NG") for a country that is in the JSON file, else None."""
    return data.get("countries", {}).get(country, {}).get("code")


def get_labels(data: dict, country: str) -> tuple:
    """Returns (state_label, place_label), e.g. ("State", "City / LGA")."""
    info = data.get("countries", {}).get(country, {})
    return info.get("state_label", "State / Region"), info.get("place_label", "City / Town")


def get_states(data: dict, country: str) -> list:
    """Names of the states/provinces of a country (empty list if unknown)."""
    states = data.get("countries", {}).get(country, {}).get("states", {})
    return sorted(states)


def get_state_info(data: dict, country: str, state: str) -> dict:
    """The whole record for one state (capital, aliases, places, coordinates)."""
    return data.get("countries", {}).get(country, {}).get("states", {}).get(state, {})


def get_places(data: dict, country: str, state: str) -> list:
    """Names of the cities / LGAs in a state (empty list if unknown)."""
    return get_state_info(data, country, state).get("places", [])


def get_place_coords(data: dict, country: str, state: str, place: str):
    """(latitude, longitude) if we stored coordinates for this place, else None."""
    coords = get_state_info(data, country, state).get("coordinates", {}).get(place)
    if coords and len(coords) == 2:
        return coords[0], coords[1]
    return None


def get_state_search_names(data: dict, country: str, state: str) -> list:
    """All names the geocoder might use for this state: our display name,
    the display name without a bracketed part, plus any aliases."""
    names = [state, state.split("(")[0].strip()]
    names.extend(get_state_info(data, country, state).get("aliases", []))
    unique = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return unique


def check_location_data(data: dict) -> list:
    """Sanity-checks the JSON and returns a list of problems (empty = all good).
    Used by the tests so a typo in the data file is caught early."""
    problems = []
    for country, info in data.get("countries", {}).items():
        if not info.get("code"):
            problems.append(f"{country}: missing ISO code")
        for state, record in info.get("states", {}).items():
            places = record.get("places", [])
            if not places:
                problems.append(f"{country}/{state}: no places listed")
            if len(places) != len(set(places)):
                problems.append(f"{country}/{state}: duplicate place names")
            for name, coords in record.get("coordinates", {}).items():
                if name not in places:
                    problems.append(f"{country}/{state}: coordinates for unknown place {name}")
                if len(coords) != 2 or not (-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180):
                    problems.append(f"{country}/{state}/{name}: bad coordinates {coords}")
    return problems
