import re
import time
import requests

from exceptions import WeatherDataError
from models import Forecast


def extract_numbers(text: str) -> list:
    """Regex helper: pull numeric values out of a free-text description."""
    return [float(n) for n in re.findall(r"-?\d+\.?\d*", text)]


def describe_extremes(f: Forecast) -> str:
    """Builds a free-text weather note, then uses extract_numbers() on it to
    flag which figures are extreme enough to call out. This is the practical
    use of the numeric-extraction regex: parsing a human-readable weather
    note back into numbers so we can decide what deserves a warning icon."""
    note = f"{f.description}, {f.temperature_c:.0f}C, {f.precipitation_prob:.0f}% rain, {f.wind_speed_kmh:.0f}kmh wind"
    numbers = extract_numbers(note)
    # numbers[0]=temp, numbers[1]=rain%, numbers[2]=wind kmh (order matches the note above)
    flags = []
    if len(numbers) >= 3:
        temp, rain, wind = numbers[0], numbers[1], numbers[2]
        if temp >= 34 or temp <= 3:
            flags.append("🌡️")
        if rain >= 70:
            flags.append("🌧️")
        if wind >= 40:
            flags.append("💨")
    return note + (" " + "".join(flags) if flags else "")


# "gemini-flash-latest" is Google's rolling alias for their current fast model,
# so it keeps working when specific versions are retired. Change it here if needed.
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# HTTP codes that mean "try again in a moment" (Google busy / rate limit).
RETRY_CODES = (429, 500, 502, 503, 504)


def build_prompt(activity: str, summary: str, overall_risk: str = "", chosen_time: str = "") -> str:
    """Builds the text we send to Gemini."""
    extra = ""
    if overall_risk:
        extra += f" The app's rule-based overall risk for the day is: {overall_risk}."
    if chosen_time:
        extra += f" The user plans to go at {chosen_time}."
    return (
        f"You are a concise outdoor-safety assistant. Activity: {activity}. "
        f"Weather summary: {summary}.{extra} In 3-4 short sentences, explain in plain, "
        f"friendly language whether this activity is safe, manageable, risky, or "
        f"should be avoided, and give one practical safety tip."
    )


def read_gemini_text(data: dict) -> str:
    """Pulls the answer text out of Gemini's JSON reply. Raises WeatherDataError
    if the reply is blocked, empty or in an unexpected shape."""
    try:
        if data.get("promptFeedback", {}).get("blockReason"):
            raise WeatherDataError("Gemini declined to answer this request.")
        parts = data["candidates"][0]["content"]["parts"]
        text = " ".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise WeatherDataError("Gemini API returned an unexpected response.")
    if not text:
        raise WeatherDataError("Gemini API returned an empty answer.")
    return text


def ask_gemini(api_key: str, activity: str, summary: str, max_retries: int = 3,
               overall_risk: str = "", chosen_time: str = "") -> str:
    """Ask Gemini for a short safety explanation. Returns the text, or raises
    WeatherDataError (never any other kind of error) so the caller can fall back."""
    if not api_key or not api_key.strip():
        raise WeatherDataError("No Gemini API key is set.")

    prompt = build_prompt(activity, summary, overall_risk, chosen_time)
    last_error = None
    for attempt in range(max_retries):
        try:
            # The key goes in a header rather than the URL, so it never shows up in error text.
            resp = requests.post(
                GEMINI_URL,
                headers={"x-goog-api-key": api_key.strip(), "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=15,
            )
        except requests.exceptions.RequestException as e:
            # Network problem (offline, timeout...): worth another try.
            last_error = f"network problem: {type(e).__name__}"
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            break

        if resp.status_code in RETRY_CODES:
            last_error = f"Google servers busy (HTTP {resp.status_code})"
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            break

        # Problems that retrying cannot fix: say clearly what is wrong.
        if resp.status_code in (400, 401, 403):
            raise WeatherDataError(
                f"Gemini rejected the request (HTTP {resp.status_code}). "
                f"The API key is probably invalid, expired or not allowed to use this model."
            )
        if resp.status_code == 404:
            raise WeatherDataError(f"Gemini model '{GEMINI_MODEL}' was not found (HTTP 404).")
        if resp.status_code != 200:
            raise WeatherDataError(f"Gemini returned an error (HTTP {resp.status_code}).")

        try:
            data = resp.json()
        except ValueError:
            raise WeatherDataError("Gemini API returned a response that is not valid JSON.")
        return read_gemini_text(data)

    raise WeatherDataError(
        f"Gemini is unavailable after {max_retries} attempts ({last_error}). "
        f"Try again in a moment."
    )

