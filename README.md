# Weather Risk & Outdoor Activity Planner — Group 11

A Streamlit app: choose a location (by GPS or Country → State → City/LGA), an
activity, a date and a time. It checks the day's weather, rates the risk for
that activity, explains why, recommends the best time, gives activity-specific
advice, builds a packing checklist, and asks Google Gemini for a plain-language
safety explanation (with rule-based advice as a fallback).

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

**Gemini API key (optional, one-time, per person running the app):**

1. Get a free key at https://aistudio.google.com/apikey
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
3. Paste your real key into that new file (it is in `.gitignore`, so it is never pushed)

No key is needed for the weather itself (Open-Meteo is free). Without a Gemini
key, or if Gemini fails, the app shows rule-based advice instead, it never crashes.

## How the location system works

```
data/locations.json  --(location_data.py)-->  3 cascading dropdowns in app.py
                                                    |
                                       selection: city, state, country, (coordinates)
                                                    |
                                  weather_client.find_place()  -->  latitude / longitude
                                                    |
                                  weather_client.get_forecast()  -->  list of Forecast
```

1. **Dropdowns come from a local JSON file** (`data/locations.json`) — no API call.
   Nigeria is complete (36 states + FCT, all 774 LGAs / area councils). Ghana,
   Kenya, South Africa, the UK and the US have a starter set of major cities.
   Any other country: pick the country, then type the place.
2. **Coordinates:** `find_place()` tries, in order:
   1. coordinates stored in the JSON file (the six FCT councils and Ikeja have them);
   2. an Open-Meteo search for the name, keeping only the result whose region matches the chosen state
      (it also tries variants: "Abuja Municipal Area Council" → "Abuja", "Obio/Akpor" → "Obio", "Akpor");
   3. the state's capital (the user sees a note explaining this);
   4. a same-country match in another region (the user sees a note).
   If everything fails you get a `LocationNotFoundError` that lists what was searched.
3. **The weather request always uses latitude/longitude.**

### `data/locations.json` format

```json
{"countries": {"Nigeria": {
    "code": "NG", "state_label": "State", "place_label": "City / LGA",
    "states": {"Federal Capital Territory (FCT)": {
        "capital": "Abuja",
        "aliases": ["Federal Capital Territory", "FCT", "Abuja"],
        "places": ["Abaji", "Abuja Municipal Area Council", "Bwari", "Gwagwalada", "Kuje", "Kwali"],
        "coordinates": {"Kwali": [8.867, 7.017]}
}}}}}
```

`places` fills the third dropdown. `coordinates` is optional (`[latitude, longitude]`).
`aliases` are other names the geocoder may use for the state. To add a country, add a block like this —
no Python changes needed. Coordinates in the file are approximate town centres.

### Use my current location

Streamlit cannot read GPS by itself, so the app uses the small `streamlit-geolocation`
add-on, which calls the browser's own geolocation. The **browser** asks for permission.
Limitations:

- Browsers only allow geolocation on **https://** pages or **localhost**. A plain `http://192.168...` address will not work.
- If permission is denied (or the add-on is missing) the app says so, and manual selection or typed coordinates still work.
- There is no reverse geocoding (no extra API), so a GPS location is shown as "Your current location (lat, lon)".

## Project structure & who owns what

| File | Owner | Responsibility |
|---|---|---|
| `app.py` | Oluwaferanmi Olotu (coordinator) | Streamlit UI; wires every module together |
| `weather_client.py` | Oluwaferanmi Olotu | Place lookup (`find_place`) + forecast fetching (Open-Meteo) |
| `models.py` | Oluwaferanmi Olotu | Shared `Forecast` data structure |
| `risk_analyzer.py` | Abimbola Ajayi | Activity rules (`ACTIVITIES`) and risk scoring |
| `recommendation.py` | Abimbola Ajayi | Best time, risk reasons, activity advice, packing list, fallback advice |
| `gemini_client.py` | Abimbola Ajayi | AI safety explanation (Gemini API) |
| `storage.py` | Abimbola Ajayi | Favourites / history / saved plans (JSON file) |
| `exceptions.py` | Oluwaferanmi Olotu | `LocationNotFoundError`, `WeatherDataError` |
| `location_data.py` | Weather/API & data group | Reads `data/locations.json` for the dropdowns |
| `time_utils.py` | App/integration group | "5:30 PM" ↔ 24-hour conversion |
| `data/locations.json` | Weather/API & data group | Country → state → place hierarchy |
| `test_app.py` | Oluwaferanmi Olotu | Tests for every module |

## Activities

16 activities, each with its own limits (wind, rain chance, min/max temperature), its own list of
weather problems that matter for it (`concerns`: rain, wind, heat, cold, storm, fog) and a tip for each
one. Thunderstorms are always "Avoid". **These limits are simple project rules, not scientific safety standards.**

## Git workflow

1. The leader (Oluwaferanmi) creates the GitHub repo and adds everyone as a collaborator.
2. Push this folder as the first commit on `main`.
3. Each person creates their own branch named after their file, e.g. `git checkout -b feature/weather-client`.
4. Commit and push your own file's changes on your branch. If you need a change to a shared file
   (`models.py`, `exceptions.py`, `data/locations.json`), flag it in the group chat first.
5. Open a pull request into `main` when your piece works. The coordinator reviews and merges it.
6. Pull the latest `main` regularly.

## Running the tests

```bash
python -m pytest test_app.py -v
```

or, without pytest installed:

```bash
python test_app.py
```

The tests use fake network responses, so they run offline.

## Files created at run time

- `planner_data.json` — created the first time you save a favourite, run a search, or save a plan
  (in `.gitignore`). Old text-only favourites from earlier versions are still understood.
