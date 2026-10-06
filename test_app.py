"""
test_app.py — Tests for every module.


Run with: python -m pytest test_app.py -v
(or just `python test_app.py` — it also runs standalone below)

None of these tests use the internet: network calls are replaced with fake
responses using unittest.mock.patch, so the tests are fast and repeatable.
"""

import json
import os
import tempfile
from datetime import date
from unittest.mock import patch

import requests

from models import Forecast
from risk_analyzer import ActivityRiskAnalyzer, ACTIVITIES, RISK_LEVELS
from recommendation import RecommendationEngine, ACTIVITY_EXTRAS
from weather_client import WeatherClient
from exceptions import LocationNotFoundError, WeatherDataError
from storage import HistoryStore, make_favourite
import gemini_client
import location_data as ld
import time_utils as tu


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_forecast(hour, temp=20, rain=10, wind=10, code=1):
    return Forecast(
        time=f"2026-09-29T{hour:02d}:00",
        temperature_c=temp,
        precipitation_prob=rain,
        wind_speed_kmh=wind,
        weather_code=code,
        description="Mainly clear",
    )


class FakeResponse:
    """A stand-in for requests.Response."""

    def __init__(self, json_data=None, status_code=200, bad_json=False):
        self.json_data = json_data
        self.status_code = status_code
        self.bad_json = bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error", response=self)


def geo_result(name, region, lat=9.0, lon=7.0, country="Nigeria"):
    return {"name": name, "admin1": region, "latitude": lat, "longitude": lon, "country": country}


def fake_geocoder(table):
    """Builds a fake requests.get that answers geocoding searches from a
    dictionary {searched name: [results]} and records every name searched."""
    searched = []

    def fake_get(url, params=None, timeout=None):
        searched.append(params["name"])
        return FakeResponse({"results": table.get(params["name"], [])})

    fake_get.searched = searched
    return fake_get


def expect_error(error_type, function, *args, **kwargs):
    """Calls function and checks that it raises error_type."""
    try:
        function(*args, **kwargs)
    except error_type as e:
        return str(e)
    assert False, f"Expected {error_type.__name__}"


def failing_get(*args, **kwargs):
    raise AssertionError("The network must not be used in this test")


# ---------------------------------------------------------------------------
# Forecast model
# ---------------------------------------------------------------------------

def test_forecast_hour_property():
    f = make_forecast(14)
    assert f.hour == 14


# ---------------------------------------------------------------------------
# Time selection (time_utils.py)
# ---------------------------------------------------------------------------

def test_time_label_conversion_examples():
    assert tu.parse_time_label("5:30 PM") == (17, 30)
    assert tu.parse_time_label("9:00 AM") == (9, 0)
    assert tu.parse_time_label("11:30 PM") == (23, 30)


def test_time_midnight_and_noon():
    assert tu.parse_time_label("12:00 AM") == (0, 0)    # midnight
    assert tu.parse_time_label("12:30 AM") == (0, 30)
    assert tu.parse_time_label("12:00 PM") == (12, 0)   # noon
    assert tu.parse_time_label("12:30 PM") == (12, 30)


def test_time_parse_is_forgiving_about_case_and_spaces():
    assert tu.parse_time_label("  5:30 pm ") == (17, 30)
    assert tu.parse_time_label("5:30PM") == (17, 30)


def test_time_invalid_labels_are_rejected():
    for bad in ["17:30", "5:30", "13:00 PM", "0:30 AM", "5:75 PM", "noon", "", "5 PM"]:
        expect_error(ValueError, tu.parse_time_label, bad)


def test_to_24_hour_validates_input():
    expect_error(ValueError, tu.to_24_hour, 5, 30, "XM")
    expect_error(ValueError, tu.to_24_hour, 0, 30, "AM")
    expect_error(ValueError, tu.to_24_hour, 13, 30, "AM")
    expect_error(ValueError, tu.to_24_hour, 5, 60, "PM")


def test_format_time_and_round_trip_for_every_option():
    assert tu.format_time(17, 30) == "5:30 PM"
    assert tu.format_time(0, 0) == "12:00 AM"
    assert tu.format_hour(12) == "12:00 PM"
    for label in tu.build_time_options(30):
        hour, minute = tu.parse_time_label(label)
        assert tu.format_time(hour, minute) == label


def test_time_options_list():
    options = tu.build_time_options(30)
    assert len(options) == 48
    assert options[0] == "12:00 AM" and options[-1] == "11:30 PM"
    assert tu.DEFAULT_TIME_LABEL in options
    assert len(tu.build_time_options(60)) == 24
    expect_error(ValueError, tu.build_time_options, 7)


# ---------------------------------------------------------------------------
# Location data (data/locations.json via location_data.py)
# ---------------------------------------------------------------------------

FCT = "Federal Capital Territory (FCT)"
FCT_COUNCILS = ["Abaji", "Abuja Municipal Area Council", "Bwari", "Gwagwalada", "Kuje", "Kwali"]


def test_location_data_file_is_valid():
    data = ld.load_location_data()
    assert ld.check_location_data(data) == []


def test_nigeria_has_37_states_and_774_lgas():
    data = ld.load_location_data()
    states = ld.get_states(data, "Nigeria")
    assert len(states) == 37
    total = sum(len(ld.get_places(data, "Nigeria", s)) for s in states)
    assert total == 774


def test_fct_dropdown_contains_all_six_area_councils():
    data = ld.load_location_data()
    assert FCT in ld.get_states(data, "Nigeria")
    assert ld.get_places(data, "Nigeria", FCT) == FCT_COUNCILS


def test_third_dropdown_changes_with_the_state():
    data = ld.load_location_data()
    lagos = ld.get_places(data, "Nigeria", "Lagos")
    assert "Ikeja" in lagos and "Kwali" not in lagos
    assert len(lagos) == 20
    assert lagos != ld.get_places(data, "Nigeria", FCT)
    assert "Aba North" in ld.get_places(data, "Nigeria", "Abia")


def test_every_nigerian_state_has_lgas_and_a_capital():
    data = ld.load_location_data()
    for state in ld.get_states(data, "Nigeria"):
        assert ld.get_places(data, "Nigeria", state), state
        assert ld.get_state_info(data, "Nigeria", state)["capital"], state


def test_country_helpers_for_unknown_countries():
    data = ld.load_location_data()
    assert ld.has_country_data(data, "Nigeria")
    assert not ld.has_country_data(data, "Narnia")
    assert ld.get_states(data, "Narnia") == []
    assert ld.get_places(data, "Nigeria", "Not a state") == []
    assert ld.get_place_coords(data, "Nigeria", "Lagos", "Agege") is None   # no coordinates stored
    assert ld.get_country_code(data, "Nigeria") == "NG"


def test_state_search_names_include_aliases():
    data = ld.load_location_data()
    names = ld.get_state_search_names(data, "Nigeria", FCT)
    assert "Federal Capital Territory" in names and "FCT" in names and "Abuja" in names


def test_country_list_includes_nigeria():
    names = [name for name, code in ld.build_country_list()]
    assert "Nigeria" in names and "Ghana" in names
    assert "European Union" not in names


def test_missing_or_broken_location_file_gives_clear_error():
    expect_error(WeatherDataError, ld.load_location_data, "/no/such/file.json")
    path = os.path.join(tempfile.mkdtemp(), "bad.json")
    with open(path, "w") as f:
        f.write("{ not valid json")
    expect_error(WeatherDataError, ld.load_location_data, path)
    with open(path, "w") as f:
        json.dump({"hello": 1}, f)
    expect_error(WeatherDataError, ld.load_location_data, path)


def test_check_location_data_catches_mistakes():
    bad = {"countries": {"X": {"code": "", "states": {"S": {"places": ["A", "A"],
           "coordinates": {"B": [999, 0]}}}}}}
    problems = ld.check_location_data(bad)
    assert len(problems) >= 4


# ---------------------------------------------------------------------------
# Selecting a location -> coordinates (the FCT cases from the brief)
# ---------------------------------------------------------------------------

def place_for(country, state, city):
    """Mimics what app.py does: read the JSON, then call find_place()."""
    data = ld.load_location_data()
    coords = ld.get_place_coords(data, country, state, city)
    lat, lon = coords if coords else (None, None)
    return WeatherClient().find_place(
        city=city, state=state, country=country, country_code=ld.get_country_code(data, country),
        state_names=ld.get_state_search_names(data, country, state),
        capital=ld.get_state_info(data, country, state).get("capital", ""),
        latitude=lat, longitude=lon,
    )


def test_fct_councils_progress_through_location_system_without_network():
    with patch("weather_client.requests.get", failing_get):
        for council in ["Kwali", "Bwari", "Abaji", "Gwagwalada", "Kuje", "Abuja Municipal Area Council"]:
            place = place_for("Nigeria", FCT, council)
            assert -90 < place["latitude"] < 90 and -180 < place["longitude"] < 180
            assert place["label"] == f"{council}, {FCT}, Nigeria"
            assert 8 < place["latitude"] < 10 and 6.5 < place["longitude"] < 8   # inside the FCT


def test_lagos_ikeja_works_without_network():
    with patch("weather_client.requests.get", failing_get):
        place = place_for("Nigeria", "Lagos", "Ikeja")
    assert abs(place["latitude"] - 6.6) < 0.1 and abs(place["longitude"] - 3.35) < 0.1


def test_find_place_uses_the_selected_state_when_names_repeat():
    # "Bassa" exists in both Kogi and Plateau; the API returns Kogi first.
    table = {"Bassa": [geo_result("Bassa", "Kogi", 7.9, 6.7), geo_result("Bassa", "Plateau", 9.9, 8.7)]}
    fake = fake_geocoder(table)
    with patch("weather_client.requests.get", fake):
        place = place_for("Nigeria", "Plateau", "Bassa")
    assert place["latitude"] == 9.9 and place["note"] == ""


def test_find_place_tries_shorter_name_variants():
    # The geocoder only knows "Obio", not "Obio/Akpor".
    fake = fake_geocoder({"Obio": [geo_result("Obio", "Rivers", 4.8, 7.0)]})
    with patch("weather_client.requests.get", fake):
        place = place_for("Nigeria", "Rivers", "Obio/Akpor")
    assert place["latitude"] == 4.8
    assert fake.searched[0] == "Obio/Akpor" and "Obio" in fake.searched


def test_find_place_falls_back_to_state_capital_with_a_note():
    # Nothing found for "Agege" -> search the capital "Ikeja" instead.
    fake = fake_geocoder({"Ikeja": [geo_result("Ikeja", "Lagos", 6.6, 3.35)]})
    with patch("weather_client.requests.get", fake):
        place = place_for("Nigeria", "Lagos", "Agege")
    assert place["latitude"] == 6.6
    assert "Ikeja" in place["note"] and "Agege" in place["note"]


def test_find_place_accepts_other_region_only_as_a_last_resort():
    fake = fake_geocoder({"Agege": [geo_result("Agege", "Ogun", 7.0, 3.0)]})
    with patch("weather_client.requests.get", fake):
        place = place_for("Nigeria", "Lagos", "Agege")
    assert place["latitude"] == 7.0
    assert "Ogun" in place["note"] and "right place" in place["note"]


def test_find_place_raises_location_not_found_with_useful_message():
    fake = fake_geocoder({})
    with patch("weather_client.requests.get", fake):
        message = expect_error(LocationNotFoundError, place_for, "Nigeria", "Lagos", "Agege")
    assert "Agege" in message and "Lagos" in message and "current location" in message


def test_find_place_without_state_uses_first_result():
    fake = fake_geocoder({"Toronto": [geo_result("Toronto", "Ontario", 43.7, -79.4, "Canada")]})
    with patch("weather_client.requests.get", fake):
        place = WeatherClient().find_place(city="Toronto", country="Canada", country_code="CA")
    assert place["latitude"] == 43.7 and place["label"] == "Toronto, Canada"


def test_state_matching_ignores_case_punctuation_and_the_word_state():
    client = WeatherClient()
    assert client._same_state("federal capital territory", ["Federal Capital Territory"])
    assert client._same_state("Lagos State", ["Lagos"])
    assert not client._same_state("Ogun", ["Lagos"])
    assert not client._same_state("", ["Lagos"])


def test_name_variants():
    client = WeatherClient()
    assert client.make_name_variants("Abuja Municipal Area Council") == ["Abuja Municipal Area Council", "Abuja"]
    assert client.make_name_variants("Kwali") == ["Kwali"]
    assert "Obio" in client.make_name_variants("Obio/Akpor") and "Akpor" in client.make_name_variants("Obio/Akpor")
    assert "Ikot Ekpene" in client.make_name_variants("Ikot-Ekpene")


def test_geocoding_network_failure_raises_weather_data_error():
    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")
    with patch("weather_client.requests.get", boom):
        message = expect_error(WeatherDataError, place_for, "Nigeria", "Lagos", "Agege")
    assert "internet" in message


def test_geocoding_unreadable_response_raises_weather_data_error():
    with patch("weather_client.requests.get", lambda *a, **k: FakeResponse(bad_json=True)):
        expect_error(WeatherDataError, place_for, "Nigeria", "Lagos", "Agege")


def test_geocoding_skips_malformed_results():
    results = [{"name": "Broken"}, geo_result("Agege", "Lagos", 6.6, 3.3)]
    with patch("weather_client.requests.get", fake_geocoder({"Agege": results})):
        place = place_for("Nigeria", "Lagos", "Agege")
    assert place["latitude"] == 6.6


def test_simple_geocode_for_free_text_places():
    fake = fake_geocoder({"Accra": [geo_result("Accra", "Greater Accra", 5.6, -0.2, "Ghana")]})
    with patch("weather_client.requests.get", fake):
        place = WeatherClient().geocode("Accra", country_code="GH")
    assert place["latitude"] == 5.6
    with patch("weather_client.requests.get", fake_geocoder({})):
        expect_error(LocationNotFoundError, WeatherClient().geocode, "Zzzzzz")


# ---------------------------------------------------------------------------
# Current location (coordinates from the browser)
# ---------------------------------------------------------------------------

def test_place_from_gps_coordinates_uses_them_directly():
    with patch("weather_client.requests.get", failing_get):
        place = WeatherClient().find_place(city="Your current location (8.87, 7.02)",
                                           latitude=8.8667, longitude=7.0167)
    assert place["latitude"] == 8.8667 and place["longitude"] == 7.0167
    assert place["name"] == "Your current location"


def test_invalid_coordinates_are_rejected():
    client = WeatherClient()
    for lat, lon in [(91, 0), (-91, 0), (0, 181), (0, -181), ("abc", 1), (None, 1)]:
        expect_error(LocationNotFoundError, client.validate_coordinates, lat, lon)
    assert client.validate_coordinates("8.5", "7.5") == (8.5, 7.5)


# ---------------------------------------------------------------------------
# Location text cleaning
# ---------------------------------------------------------------------------

def test_clean_location_strips_invalid_characters():
    client = WeatherClient()
    assert client.clean_location("Lagos123!!") == "Lagos"


def test_clean_location_rejects_empty_input():
    client = WeatherClient()
    expect_error(LocationNotFoundError, client.clean_location, "!!!123")


def test_clean_location_keeps_accented_letters():
    assert WeatherClient().clean_location("São  Paulo") == "São Paulo"


# ---------------------------------------------------------------------------
# Forecast fetching
# ---------------------------------------------------------------------------

def hourly_payload(**overrides):
    hourly = {
        "time": [f"2026-10-06T{h:02d}:00" for h in range(3)],
        "temperature_2m": [24.0, 25.0, 26.0],
        "precipitation_probability": [10, 20, 30],
        "wind_speed_10m": [5.0, 6.0, 7.0],
        "weather_code": [0, 1, 61],
    }
    hourly.update(overrides)
    return {"hourly": hourly}


def test_get_forecast_builds_forecast_objects():
    with patch("weather_client.requests.get", lambda *a, **k: FakeResponse(hourly_payload())):
        forecasts = WeatherClient().get_forecast(9.0, 7.0, date(2026, 10, 6))
    assert len(forecasts) == 3
    assert forecasts[2].description == "Slight rain" and forecasts[2].hour == 2


def test_get_forecast_handles_null_values():
    payload = hourly_payload(precipitation_probability=[None, 20, 30], temperature_2m=[24.0, None, 26.0])
    with patch("weather_client.requests.get", lambda *a, **k: FakeResponse(payload)):
        forecasts = WeatherClient().get_forecast(9.0, 7.0, date(2026, 10, 6))
    assert len(forecasts) == 2                      # the hour with no temperature is skipped
    assert forecasts[0].precipitation_prob == 0     # a missing rain chance becomes 0


def test_get_forecast_with_no_usable_data_raises():
    payload = hourly_payload(temperature_2m=[None, None, None])
    with patch("weather_client.requests.get", lambda *a, **k: FakeResponse(payload)):
        expect_error(WeatherDataError, WeatherClient().get_forecast, 9.0, 7.0, date(2026, 10, 6))


def test_get_forecast_missing_fields_raises():
    with patch("weather_client.requests.get", lambda *a, **k: FakeResponse({"hourly": {"time": []}})):
        expect_error(WeatherDataError, WeatherClient().get_forecast, 9.0, 7.0, date(2026, 10, 6))
    with patch("weather_client.requests.get", lambda *a, **k: FakeResponse({"oops": 1})):
        expect_error(WeatherDataError, WeatherClient().get_forecast, 9.0, 7.0, date(2026, 10, 6))


def test_get_forecast_network_error_message():
    def boom(*args, **kwargs):
        raise requests.exceptions.Timeout("slow")
    with patch("weather_client.requests.get", boom):
        message = expect_error(WeatherDataError, WeatherClient().get_forecast, 9.0, 7.0, date(2026, 10, 6))
    assert "internet" in message


def test_get_forecast_explains_date_out_of_range():
    response = FakeResponse({"error": True, "reason": "start_date is out of allowed range"}, status_code=400)
    with patch("weather_client.requests.get", lambda *a, **k: response):
        message = expect_error(WeatherDataError, WeatherClient().get_forecast, 9.0, 7.0, date(2030, 1, 1))
    assert "out of allowed range" in message and "16 days" in message


def test_get_forecast_rejects_bad_coordinates_before_calling_the_api():
    with patch("weather_client.requests.get", failing_get):
        expect_error(LocationNotFoundError, WeatherClient().get_forecast, 123, 7.0, date(2026, 10, 6))


# ---------------------------------------------------------------------------
# Risk analysis — every activity
# ---------------------------------------------------------------------------

EXPECTED_ACTIVITIES = [
    "Football", "Jogging / Running", "Farming", "Picnic", "Travelling", "Outdoor event",
    "Hiking", "Cycling", "Camping", "Fishing", "Swimming / Beach day",
    "Outdoor wedding / ceremony", "Gardening", "Construction / outdoor work",
    "Motorcycle / bike riding", "Market / outdoor trading",
]


def test_all_expected_activities_exist_with_complete_rules():
    for name in EXPECTED_ACTIVITIES:
        assert name in ACTIVITIES, name
    for name, rules in ACTIVITIES.items():
        for key in ("max_wind", "max_rain_chance", "min_temp", "max_temp", "concerns", "tips"):
            assert key in rules, f"{name} is missing {key}"
        assert "storm" in rules["concerns"], name
        assert set(rules["tips"]) == set(rules["concerns"]), f"{name}: tips must match concerns"
        assert rules["min_temp"] < rules["max_temp"], name
        assert name in ACTIVITY_EXTRAS, f"{name} has no packing extras"


def test_the_concerns_listed_in_the_brief():
    assert set(ACTIVITIES["Football"]["concerns"]) >= {"rain", "wind", "heat", "storm"}
    assert set(ACTIVITIES["Hiking"]["concerns"]) >= {"rain", "wind", "heat", "storm"}
    assert set(ACTIVITIES["Picnic"]["concerns"]) >= {"rain", "wind", "heat", "cold"}
    assert set(ACTIVITIES["Farming"]["concerns"]) >= {"heat", "rain", "storm"}
    assert set(ACTIVITIES["Cycling"]["concerns"]) >= {"wind", "rain", "heat"}
    assert set(ACTIVITIES["Camping"]["concerns"]) >= {"rain", "wind", "storm", "cold", "heat"}


def test_every_activity_is_safe_in_mild_weather():
    mild = make_forecast(12, temp=27, rain=5, wind=8, code=1)
    for name in ACTIVITIES:
        assert ActivityRiskAnalyzer(name).score_hour(mild) == 0, name


def test_every_activity_avoids_thunderstorms():
    storm = make_forecast(12, temp=27, rain=5, wind=8, code=95)
    for name in ACTIVITIES:
        assert ActivityRiskAnalyzer(name).score_hour(storm) == 3, name


def test_every_activity_gets_riskier_in_bad_weather():
    bad = make_forecast(12, temp=27, rain=95, wind=70, code=65)
    for name in ACTIVITIES:
        assert ActivityRiskAnalyzer(name).score_hour(bad) >= 1, name


def test_risk_analyzer_safe_conditions():
    analyzer = ActivityRiskAnalyzer("Jogging / Running")
    f = make_forecast(8, temp=20, rain=5, wind=10)
    score = analyzer.score_hour(f)
    assert score == 0  # Safe


def test_risk_analyzer_storm_is_always_avoid():
    analyzer = ActivityRiskAnalyzer("Travelling")
    f = make_forecast(12, temp=20, rain=5, wind=5, code=95)  # thunderstorm
    assert analyzer.score_hour(f) == 3  # Avoid, regardless of other values


def test_activity_specific_hazards():
    # Cold matters for camping but not for football.
    cold = make_forecast(6, temp=1)
    assert "cold" in ActivityRiskAnalyzer("Camping").find_hazards(cold)
    assert "cold" not in ActivityRiskAnalyzer("Football").find_hazards(cold)
    # Fog matters for hiking and riding, not for football.
    fog = make_forecast(6, code=45)
    assert "fog" in ActivityRiskAnalyzer("Hiking").find_hazards(fog)
    assert "fog" in ActivityRiskAnalyzer("Motorcycle / bike riding").find_hazards(fog)
    assert ActivityRiskAnalyzer("Football").find_hazards(fog) == []
    # Wind matters for cycling, not for farming.
    windy = make_forecast(12, wind=60)
    assert "wind" in ActivityRiskAnalyzer("Cycling").find_hazards(windy)
    assert ActivityRiskAnalyzer("Farming").find_hazards(windy) == []
    # Heat matters for football and farming.
    hot = make_forecast(14, temp=42)
    assert "heat" in ActivityRiskAnalyzer("Football").find_hazards(hot)
    assert "heat" in ActivityRiskAnalyzer("Farming").find_hazards(hot)


def test_heavy_rain_code_counts_even_with_low_rain_chance():
    f = make_forecast(12, rain=0, code=65)
    assert "rain" in ActivityRiskAnalyzer("Picnic").find_hazards(f)


def test_severe_weather_adds_an_extra_point():
    analyzer = ActivityRiskAnalyzer("Cycling")
    assert analyzer.score_hour(make_forecast(12, wind=40)) == 1      # a little over the limit
    assert analyzer.score_hour(make_forecast(12, wind=60)) == 2      # far over the limit


def test_score_never_exceeds_avoid():
    f = make_forecast(12, temp=50, rain=100, wind=200, code=65)
    assert ActivityRiskAnalyzer("Camping").score_hour(f) == 3


def test_analyze_returns_labels():
    analyzed = ActivityRiskAnalyzer("Picnic").analyze([make_forecast(8), make_forecast(9, code=95)])
    assert analyzed[0][2] == "Safe" and analyzed[1][2] == "Avoid"
    assert analyzed[1][2] == RISK_LEVELS[3]


def test_unknown_activity_is_rejected():
    expect_error(ValueError, ActivityRiskAnalyzer, "Skydiving on Mars")


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def full_day(activity, overrides=None):
    """A 24-hour forecast analysed for an activity. overrides: {hour: forecast}."""
    forecasts = [make_forecast(h, temp=24, rain=5, wind=5) for h in range(24)]
    for hour, forecast in (overrides or {}).items():
        forecasts[hour] = forecast
    return RecommendationEngine(activity, ActivityRiskAnalyzer(activity).analyze(forecasts))


def test_recommendation_engine_picks_lowest_risk_hour():
    analyzer = ActivityRiskAnalyzer("Picnic")
    forecasts = [make_forecast(h, temp=20, rain=5, wind=5) for h in range(6, 20)]
    forecasts[10] = make_forecast(16, temp=40, rain=90, wind=80)  # bad hour
    analyzed = analyzer.analyze(forecasts)
    engine = RecommendationEngine("Picnic", analyzed)
    best = engine.best_time()
    assert best is not None
    assert best[1] < 3  # not the "Avoid" hour we injected


def test_best_time_stays_in_daytime_even_if_night_is_calmer():
    # Daytime is windy (score 1); the night is perfectly calm (score 0).
    overrides = {h: make_forecast(h, temp=24, rain=5, wind=45) for h in range(7, 20)}
    engine = full_day("Cycling", overrides)
    best = engine.best_time()
    assert 7 <= best[0].hour <= 19


def test_best_time_allows_the_users_own_night_hour():
    overrides = {h: make_forecast(h, temp=24, rain=5, wind=45) for h in range(7, 20)}
    engine = full_day("Cycling", overrides)
    assert engine.best_time(preferred_hour=22)[0].hour == 22


def test_best_time_prefers_hour_closest_to_preferred_when_tied():
    engine = full_day("Picnic")                        # every hour equally safe
    assert engine.best_time(preferred_hour=17)[0].hour == 17
    assert engine.best_time()[0].hour == 15            # default anchor is 3 PM


def test_best_time_with_no_data():
    assert RecommendationEngine("Picnic", []).best_time() is None


def test_risk_at_a_specific_hour():
    engine = full_day("Picnic", {17: make_forecast(17, code=95)})
    assert engine.risk_at(17)[2] == "Avoid"
    assert engine.risk_at(9)[2] == "Safe"
    assert RecommendationEngine("Picnic", []).risk_at(9) is None


def test_overall_risk_exactly_half_rounds_up():
    # Two daytime hours scored 0 and 1: the average is exactly 0.5.
    # Python's round(0.5) gives 0 ("Safe"); we want the cautious "Manageable".
    analyzed = [(make_forecast(8), 0, "Safe"), (make_forecast(9), 1, "Manageable")]
    assert RecommendationEngine("Picnic", analyzed).overall_risk() == "Manageable"
    analyzed = [(make_forecast(8), 2, "Risky"), (make_forecast(9), 3, "Avoid")]   # average 2.5
    assert RecommendationEngine("Picnic", analyzed).overall_risk() == "Avoid"


def test_overall_risk_rounds_half_up():
    # 13 daytime hours: 6 or 7 of them scored 1 -> average about 0.5.
    overrides = {h: make_forecast(h, temp=24, rain=5, wind=45) for h in range(7, 14)}
    engine = full_day("Cycling", overrides)          # 7 windy hours out of 13 -> avg 0.54
    assert engine.overall_risk() == "Manageable"
    assert full_day("Cycling").overall_risk() == "Safe"


def test_risk_reasons_mention_the_limits_that_were_passed():
    overrides = {12: make_forecast(12, temp=24, rain=90, wind=50)}
    reasons = " ".join(full_day("Cycling", overrides).risk_reasons())
    assert "Rain chance reaches 90%" in reasons and "Wind reaches 50 km/h" in reasons


def test_risk_reasons_mention_storms_in_12_hour_time():
    reasons = " ".join(full_day("Hiking", {15: make_forecast(15, code=95)}).risk_reasons())
    assert "Thunderstorms" in reasons and "3:00 PM" in reasons


def test_risk_reasons_ignore_factors_that_do_not_matter_for_the_activity():
    # Wind is not a concern for farming, so a gale is not mentioned.
    reasons = " ".join(full_day("Farming", {12: make_forecast(12, wind=90)}).risk_reasons())
    assert "Wind" not in reasons


def test_risk_reasons_when_everything_is_fine():
    reasons = full_day("Picnic").risk_reasons()
    assert len(reasons) == 1 and "No weather factor" in reasons[0]


def test_activity_advice_only_for_problems_that_happen():
    engine = full_day("Football", {12: make_forecast(12, rain=95)})
    advice = engine.activity_advice()
    assert advice == [ACTIVITIES["Football"]["tips"]["rain"]]


def test_activity_advice_when_weather_is_fine():
    advice = full_day("Football").activity_advice()
    assert len(advice) == 1 and "fine" in advice[0]


def test_packing_checklist_reacts_to_weather_and_activity():
    rainy_hot = full_day("Hiking", {12: make_forecast(12, temp=36, rain=80)})
    items = rainy_hot.packing_checklist()
    assert "Umbrella or rain jacket" in items and "Sunscreen" in items and "Hiking boots" in items
    assert items == sorted(items)


def test_every_activity_has_a_checklist():
    for name in ACTIVITIES:
        items = full_day(name).packing_checklist()
        assert "Water bottle" in items
        assert any(extra in items for extra in ACTIVITY_EXTRAS[name]), name


def test_rule_based_advice_uses_12_hour_time():
    text = full_day("Picnic").rule_based_advice()
    assert "picnic" in text and "3:00 PM" in text and "safe" in text


# ---------------------------------------------------------------------------
# Gemini (all network calls are faked)
# ---------------------------------------------------------------------------

def gemini_ok(text="Looks fine. Bring water."):
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}}]})


def run_gemini(responses, key="test-key"):
    """Runs ask_gemini with a list of fake responses; returns (result_or_error, number_of_calls)."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    with patch("gemini_client.requests.post", fake_post), patch("gemini_client.time.sleep", lambda s: None):
        try:
            return gemini_client.ask_gemini(key, "Hiking", "summary"), len(calls)
        except WeatherDataError as e:
            return e, len(calls)


def test_gemini_success_sends_key_in_header_not_url():
    result, calls = run_gemini([gemini_ok()])
    assert result == "Looks fine. Bring water." and calls == 1
    assert "key=" not in gemini_client.GEMINI_URL


def test_gemini_joins_multiple_text_parts():
    data = {"candidates": [{"content": {"parts": [{"text": "One."}, {"text": "Two."}]}}]}
    assert gemini_client.read_gemini_text(data) == "One. Two."


def test_gemini_without_key_raises_weather_data_error():
    with patch("gemini_client.requests.post", failing_get):
        expect_error(WeatherDataError, gemini_client.ask_gemini, "", "Hiking", "summary")
        expect_error(WeatherDataError, gemini_client.ask_gemini, "   ", "Hiking", "summary")


def test_gemini_bad_key_is_not_retried_and_explained():
    result, calls = run_gemini([FakeResponse({}, status_code=403)])
    assert isinstance(result, WeatherDataError) and calls == 1
    assert "key" in str(result)


def test_gemini_retries_when_busy_then_succeeds():
    result, calls = run_gemini([FakeResponse({}, status_code=503), gemini_ok("Recovered.")])
    assert result == "Recovered." and calls == 2


def test_gemini_gives_up_after_repeated_503():
    result, calls = run_gemini([FakeResponse({}, status_code=503)])
    assert isinstance(result, WeatherDataError) and calls == 3


def test_gemini_network_error_becomes_weather_data_error():
    result, calls = run_gemini([requests.exceptions.ConnectionError("offline")])
    assert isinstance(result, WeatherDataError) and calls == 3


def test_gemini_malformed_responses_become_weather_data_error():
    for bad in [FakeResponse({"nothing": 1}), FakeResponse({"candidates": []}),
                FakeResponse({"candidates": [{"content": {"parts": []}}]}),
                FakeResponse({"candidates": [{"content": {"parts": [{"text": "  "}]}}]}),
                FakeResponse(bad_json=True), FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}}),
                FakeResponse(["not", "a", "dict"])]:
        result, calls = run_gemini([bad])
        assert isinstance(result, WeatherDataError), bad.json_data


def test_gemini_unexpected_status_and_missing_model():
    assert isinstance(run_gemini([FakeResponse({}, status_code=404)])[0], WeatherDataError)
    assert isinstance(run_gemini([FakeResponse({}, status_code=418)])[0], WeatherDataError)


def test_gemini_prompt_contains_context():
    prompt = gemini_client.build_prompt("Hiking", "sunny", overall_risk="Safe", chosen_time="5:30 PM")
    assert "Hiking" in prompt and "sunny" in prompt and "Safe" in prompt and "5:30 PM" in prompt


def test_describe_extremes_flags_hot_windy_wet_hours():
    note = gemini_client.describe_extremes(make_forecast(12, temp=38, rain=80, wind=50))
    assert "🌡️" in note and "🌧️" in note and "💨" in note
    assert "🌡️" not in gemini_client.describe_extremes(make_forecast(12))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def temp_store(initial=None):
    path = os.path.join(tempfile.mkdtemp(), "planner_data.json")
    if initial is not None:
        with open(path, "w") as f:
            json.dump(initial, f)
    return HistoryStore(path)


def test_storage_favourites_keep_coordinates():
    store = temp_store()
    store.add_favourite(make_favourite("Kwali, Federal Capital Territory (FCT), Nigeria", 8.867, 7.017))
    store.add_favourite(make_favourite("Kwali, Federal Capital Territory (FCT), Nigeria", 8.867, 7.017))  # duplicate
    favourites = store.get_favourites()
    assert len(favourites) == 1 and favourites[0]["latitude"] == 8.867
    assert store.is_favourite("Kwali, Federal Capital Territory (FCT), Nigeria")
    store.remove_favourite("Kwali, Federal Capital Territory (FCT), Nigeria")
    assert store.get_favourites() == []


def test_storage_understands_old_text_favourites():
    store = temp_store({"favourites": ["Ikeja, Nigeria"], "history": [], "plans": []})
    assert store.get_favourites() == [{"label": "Ikeja, Nigeria", "latitude": None, "longitude": None}]
    store.add_favourite("Lagos, Nigeria")        # plain text is accepted too
    assert len(store.get_favourites()) == 2


def test_storage_history_and_plans_are_capped():
    store = temp_store()
    for i in range(25):
        store.add_history({"location": f"Place {i}"})
        store.add_plan({"location": f"Place {i}"})
    assert len(store.get_history()) == 20 and store.get_history()[0]["location"] == "Place 24"
    assert len(store.get_plans()) == 20
    store.remove_plan(0)
    assert len(store.get_plans()) == 19
    store.remove_plan(99)                         # out of range is ignored
    assert len(store.get_plans()) == 19


def test_storage_survives_a_corrupted_file():
    store = temp_store()
    with open(store.path, "w") as f:
        f.write("{ broken")
    assert store.get_favourites() == [] and store.get_history() == []
    store.add_history({"location": "X"})          # and it can still save afterwards
    assert len(store.get_history()) == 1


# ---------------------------------------------------------------------------
# End to end (no Streamlit): selection -> place -> forecast -> risk -> advice
# ---------------------------------------------------------------------------

def test_full_pipeline_for_kwali_hiking_at_530_pm():
    hours = list(range(24))
    payload = {"hourly": {
        "time": [f"2026-10-06T{h:02d}:00" for h in hours],
        "temperature_2m": [24 + (4 if 12 <= h <= 16 else 0) for h in hours],
        "precipitation_probability": [10] * 24,
        "wind_speed_10m": [8] * 24,
        "weather_code": [1] * 24,
    }}
    with patch("weather_client.requests.get", lambda url, params=None, timeout=None: FakeResponse(payload)):
        place = place_for("Nigeria", FCT, "Kwali")
        forecasts = WeatherClient().get_forecast(place["latitude"], place["longitude"], date(2026, 10, 6))
    hour, minute = tu.parse_time_label("5:30 PM")
    engine = RecommendationEngine("Hiking", ActivityRiskAnalyzer("Hiking").analyze(forecasts))
    assert engine.risk_at(hour)[2] == "Safe"
    assert engine.overall_risk() == "Safe"
    assert engine.best_time(hour)[0].hour == 17
    assert "Kwali" in place["label"]


def test_streamlit_app_module_imports():
    try:
        import streamlit  # noqa: F401
    except ImportError:
        return          # Streamlit is not installed here; nothing to check
    import app          # noqa: F401  (importing checks for syntax and import errors)
    assert callable(app.main)


if __name__ == "__main__":
    # Lets teammates run `python test_app.py` even without pytest installed.
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__} — {e}")
            failed += 1
        except Exception as e:  # an unexpected crash is a failure too
            print(f"ERROR: {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
