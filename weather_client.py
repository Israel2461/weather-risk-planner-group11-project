"""
Responsibility: turn what the user selected into a place with latitude and
longitude, and fetch the hourly forecast for it. This is the ONLY module
that talks to the weather API — nothing else in the app should call
`requests` directly for weather data.

HOW A PLACE IS FOUND (most reliable first) — see find_place():
  1. The JSON data file already has coordinates for it -> use them directly.
  2. Search Open-Meteo for the place name and keep the result whose
     state/region matches what the user picked.
  3. Search again for the state's capital and use that (the user is told).
  4. Last resort: accept a result from the right country but another region
     (the user is told).
  If all of that fails -> LocationNotFoundError with a helpful message.
"""

import re
import requests
from datetime import date

from exceptions import LocationNotFoundError, WeatherDataError
from models import Forecast

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

# Words that are part of an official area name but are rarely part of the
# name a map/geocoder uses. e.g. "Abuja Municipal Area Council" -> "Abuja".
NAME_SUFFIXES = [
    "Municipal Area Council", "Area Council", "Local Government Area",
    "Local Government", "Metropolitan", "Municipal", "LGA",
]


class WeatherClient:
    GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def clean_location(self, raw: str) -> str:
        """Regex-based cleanup: remove digits and symbols, keep letters (including
        accented ones like "ã"), spaces, commas, hyphens, apostrophes and
        slashes, and collapse repeated whitespace."""
        cleaned = re.sub(r"[\d_]", "", raw)                 # drop digits and underscores
        cleaned = re.sub(r"[^\w\s,\-'/]", "", cleaned)       # drop other symbols
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            raise LocationNotFoundError("Please enter a location name.")
        return cleaned

    def make_name_variants(self, city: str) -> list:
        """Different spellings of a place name worth searching for.

        "Abuja Municipal Area Council" -> ["Abuja Municipal Area Council", "Abuja"]
        "Obio/Akpor"                   -> ["Obio/Akpor", "Obio", "Akpor"]
        """
        city = self.clean_location(city)
        variants = [city]

        # Remove official suffix words.
        shortened = city
        for suffix in NAME_SUFFIXES:
            shortened = re.sub(rf"\s*\b{suffix}\b", "", shortened, flags=re.IGNORECASE).strip()
        if shortened:
            variants.append(shortened)

        # Names like "Ado-Odo/Ota" are really two places joined by a slash.
        for text in list(variants):
            if "/" in text:
                variants.extend(part.strip() for part in text.split("/"))

        # Hyphens: geocoders often store "Ikot Ekpene", not "Ikot-Ekpene".
        for text in list(variants):
            if "-" in text:
                variants.append(text.replace("-", " "))

        unique = []
        for text in variants:
            text = text.strip()
            if len(text) >= 2 and text not in unique:   # Open-Meteo needs 2+ characters
                unique.append(text)
        return unique

    def _normalise(self, text: str) -> str:
        """Lowercase and keep letters only, so "Federal Capital Territory" and
        "federal-capital territory" compare as equal."""
        text = re.sub(r"\bstate\b", "", (text or "").lower())
        return re.sub(r"[^a-z]", "", text)

    def _same_state(self, region_from_api: str, state_names: list) -> bool:
        wanted = [self._normalise(name) for name in state_names]
        return bool(region_from_api) and self._normalise(region_from_api) in wanted

    def validate_coordinates(self, latitude, longitude) -> tuple:
        """Make sure latitude/longitude are real numbers in the valid range."""
        try:
            lat, lon = float(latitude), float(longitude)
        except (TypeError, ValueError):
            raise LocationNotFoundError("The coordinates are not valid numbers.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise LocationNotFoundError(
                "The coordinates are out of range (latitude -90 to 90, longitude -180 to 180)."
            )
        return lat, lon

    def place_from_coordinates(self, latitude, longitude, label: str = "", country: str = "") -> dict:
        """Build a place dictionary when we ALREADY know the coordinates
        (from the data file, a favourite, or the browser's GPS)."""
        lat, lon = self.validate_coordinates(latitude, longitude)
        if not label:
            label = f"Your location ({lat:.2f}, {lon:.2f})"
        return {
            "name": label.split(" (")[0].split(",")[0],
            "country": country,
            "label": label,
            "latitude": lat,
            "longitude": lon,
            "note": "",
        }

    # ------------------------------------------------------------------
    # Geocoding (name -> coordinates)
    # ------------------------------------------------------------------
    def search_places(self, name: str, country_code: str = None, count: int = 10) -> list:
        """Ask Open-Meteo for places called `name`. Returns a (possibly empty)
        list of dictionaries. Raises WeatherDataError on network problems."""
        params = {"name": name, "count": count, "language": "en", "format": "json"}
        # The ISO country code (e.g. "NG") keeps a name like "Bassa" in Nigeria.
        if country_code:
            params["countryCode"] = country_code
        try:
            resp = requests.get(self.GEOCODE_URL, params=params, timeout=10)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise WeatherDataError(
                f"Could not reach the location service while looking up '{name}'. "
                f"Check your internet connection and try again. ({e})"
            )

        try:
            payload = resp.json()
        except ValueError:
            raise WeatherDataError("The location service returned an unreadable response.")

        places = []
        for item in payload.get("results") or []:
            try:
                places.append({
                    "name": item.get("name", name),
                    "country": item.get("country", ""),
                    "region": item.get("admin1", ""),      # state / province
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                })
            except KeyError:
                continue        # skip a malformed result instead of crashing
        return places

    def geocode(self, location: str, country_code: str = None) -> dict:
        """Simple 'first match' lookup for ONE free-text name (used when a
        country has no dropdown data, and for old favourites)."""
        location = self.clean_location(location)
        results = self.search_places(location, country_code, count=1)
        if not results:
            raise LocationNotFoundError(
                f"Could not find a location called '{location}'. "
                f"Check the spelling or try a nearby larger town."
            )
        top = results[0]
        top["label"] = f"{top['name']}, {top['country']}" if top["country"] else top["name"]
        top["note"] = ""
        return top

    def find_place(self, city: str, state: str = "", country: str = "", country_code: str = None,
                   state_names: list = None, capital: str = "",
                   latitude=None, longitude=None) -> dict:
        """Turn a selected Country/State/City into a place with coordinates.
        See the notes at the top of this file for the order of attempts."""
        state = (state or "").strip()
        label_parts = [p for p in [city, state, country] if p and p.strip()]
        label = ", ".join(label_parts)

        # 1) Coordinates already known -> no search needed.
        if latitude is not None and longitude is not None:
            return self.place_from_coordinates(latitude, longitude, label, country)

        state_names = state_names or ([state] if state else [])
        variants = self.make_name_variants(city)
        other_region_match = None     # remember a same-country result in case nothing better exists

        # 2) Search for the place name; accept the result inside the chosen state.
        for name in variants:
            results = self.search_places(name, country_code)
            if not state:
                if results:
                    return self._build_place(results[0], label, country)
                continue
            for result in results:
                if self._same_state(result["region"], state_names):
                    return self._build_place(result, label, country)
            if results and other_region_match is None:
                other_region_match = results[0]

        # 3) Fall back to the state's capital.
        if state and capital:
            for result in self.search_places(capital, country_code):
                if self._same_state(result["region"], state_names):
                    place = self._build_place(result, label, country)
                    place["note"] = (
                        f"Could not pinpoint '{city}' on the map, so this forecast is for "
                        f"{capital}, the capital of {state}. Nearby weather is usually similar."
                    )
                    return place

        # 4) Last resort: same country, different region. Better than nothing, but say so.
        if other_region_match:
            place = self._build_place(other_region_match, label, country)
            found_in = other_region_match["region"] or "another region"
            place["note"] = (
                f"Could not find '{city}' inside {state}. Showing the closest match, "
                f"which is in {found_in}. Please check this is the right place."
            )
            return place

        where = ", ".join(p for p in [state, country] if p)
        raise LocationNotFoundError(
            f"Could not find '{city}' in {where}. "
            f"We searched for: {', '.join(variants)}. "
            f"Try a nearby larger town, or use 'Use my current location'."
        )

    def _build_place(self, result: dict, label: str, country: str) -> dict:
        return {
            "name": label.split(",")[0] if label else result["name"],
            "country": country or result.get("country", ""),
            "label": label or result["name"],
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "note": "",
        }

    # ------------------------------------------------------------------
    # Forecast (coordinates -> hourly weather)
    # ------------------------------------------------------------------
    def get_forecast(self, latitude: float, longitude: float, target_date: date) -> list:
        lat, lon = self.validate_coordinates(latitude, longitude)
        try:
            resp = requests.get(
                self.FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,weather_code",
                    "start_date": target_date.isoformat(),
                    "end_date": target_date.isoformat(),
                    "timezone": "auto",
                },
                timeout=10,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            raise WeatherDataError(self._forecast_error_message(e))
        except requests.exceptions.RequestException as e:
            raise WeatherDataError(
                f"Could not reach the weather service. Check your internet connection "
                f"and try again. ({e})"
            )

        try:
            payload = resp.json()
            hourly = payload["hourly"]
            times = hourly["time"]
            temps = hourly["temperature_2m"]
            precs = hourly["precipitation_probability"]
            winds = hourly["wind_speed_10m"]
            codes = hourly["weather_code"]
        except (ValueError, KeyError, TypeError) as e:
            raise WeatherDataError(f"Forecast response was missing expected data ({e}).")

        forecasts = []
        for i in range(len(times)):
            # The API sometimes sends null for an hour. Skip hours without the
            # essentials; treat a missing rain chance as 0%.
            if temps[i] is None or winds[i] is None or codes[i] is None:
                continue
            rain = precs[i] if precs[i] is not None else 0
            code = codes[i]
            forecasts.append(
                Forecast(
                    time=times[i],
                    temperature_c=temps[i],
                    precipitation_prob=rain,
                    wind_speed_kmh=winds[i],
                    weather_code=code,
                    description=WEATHER_CODES.get(code, "Unknown"),
                )
            )
        if not forecasts:
            raise WeatherDataError("No forecast data was returned for that date.")
        return forecasts

    def _forecast_error_message(self, error) -> str:
        """Open-Meteo explains HTTP 400 errors in JSON ({"reason": "..."}); show that."""
        reason = ""
        try:
            reason = error.response.json().get("reason", "")
        except (ValueError, AttributeError):
            pass
        if reason:
            return (f"The weather service rejected the request: {reason} "
                    f"(Forecasts are available for about 16 days ahead.)")
        return f"The weather service returned an error: {error}"
