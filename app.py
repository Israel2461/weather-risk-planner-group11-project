"""
Weather Risk & Outdoor Activity Planner — main app / integration layer.

This file is the Streamlit UI. It imports every other module and wires them
together: it does NOT contain business logic itself (no risk scoring, no
API calls beyond what the imported modules do). If you're adding actual
weather/risk/AI logic, it almost certainly belongs in one of the other
files, not here.

Data flow:
  app.py -> location_data / weather_client -> models (Forecast)
         -> risk_analyzer -> recommendation -> gemini_client -> storage
"""

import os
from datetime import date, timedelta

import streamlit as st

from exceptions import LocationNotFoundError, WeatherDataError
from weather_client import WeatherClient
from risk_analyzer import ActivityRiskAnalyzer, ACTIVITIES
from recommendation import RecommendationEngine
from gemini_client import ask_gemini, describe_extremes
from storage import HistoryStore, make_favourite
from time_utils import (
    build_time_options, parse_time_label, format_hour, DEFAULT_TIME_LABEL,
)
from location_data import (
    load_location_data, build_country_list, has_country_data, get_country_code,
    get_labels, get_states, get_places, get_place_coords, get_state_info,
    get_state_search_names,
)

# The "use my current location" button needs a small add-on package, because
# Streamlit itself cannot read the browser's GPS. If it is not installed the
# app still works: the user can pick manually or type coordinates.
try:
    from streamlit_geolocation import streamlit_geolocation
    GEOLOCATION_AVAILABLE = True
except ImportError:
    GEOLOCATION_AVAILABLE = False

MODE_CURRENT = "📍 Use my current location"
MODE_MANUAL = "🌍 Choose location manually"
FORECAST_DAYS_AHEAD = 15   # Open-Meteo forecasts reach about 16 days ahead


# --------------------------------------------------------------------------
# Cached data loaders (Streamlit re-runs this whole file on every click, so
# we cache things that never change to avoid re-reading them each time).
# --------------------------------------------------------------------------

@st.cache_data
def get_country_list():
    """Sorted list of (country_name, iso_code) tuples for every country."""
    return build_country_list()


@st.cache_data
def get_location_data():
    """The country -> state -> city hierarchy from data/locations.json."""
    return load_location_data()


# --------------------------------------------------------------------------
# Location pickers. Each returns a "selection" dictionary (or None if the
# user hasn't chosen anything usable yet) that run_check() passes to
# WeatherClient.find_place().
# --------------------------------------------------------------------------

def make_selection(city, state="", country="", country_code=None, state_names=None,
                   capital="", latitude=None, longitude=None):
    return {
        "city": city, "state": state, "country": country, "country_code": country_code,
        "state_names": state_names or [], "capital": capital,
        "latitude": latitude, "longitude": longitude,
    }


def manual_location_picker(data):
    """Country -> State -> City/LGA. The 2nd and 3rd dropdowns change
    depending on what was picked above them."""
    countries = get_country_list()
    country_names = [c[0] for c in countries]
    name_to_code = dict(countries)
    default_index = country_names.index("Nigeria") if "Nigeria" in country_names else 0

    country = st.selectbox("Country", country_names, index=default_index)

    if has_country_data(data, country):
        state_label, place_label = get_labels(data, country)
        # The widget keys include the parent choice, so a new Country/State
        # gives a fresh dropdown that starts at its first option.
        state = st.selectbox(state_label, get_states(data, country), key=f"state_{country}")
        city = st.selectbox(place_label, get_places(data, country, state), key=f"place_{country}_{state}")

        coords = get_place_coords(data, country, state, city)
        latitude, longitude = coords if coords else (None, None)
        return make_selection(
            city=city, state=state, country=country,
            country_code=get_country_code(data, country),
            state_names=get_state_search_names(data, country, state),
            capital=get_state_info(data, country, state).get("capital", ""),
            latitude=latitude, longitude=longitude,
        )

    # No dropdown data for this country: fall back to typing.
    st.caption(
        "Dropdown lists are available for Nigeria, Ghana, Kenya, South Africa, the "
        "United Kingdom and the United States. For other countries, type the place."
    )
    state = st.text_input("State / Region (optional)", key=f"free_state_{country}")
    city = st.text_input("City / Town", key=f"free_city_{country}", placeholder="e.g. Toronto")
    if not city.strip():
        return None
    return make_selection(city=city.strip(), state=state.strip(), country=country,
                          country_code=name_to_code.get(country))


def current_location_picker():
    """Asks the browser for the user's GPS position (the browser itself shows
    the permission pop-up). Returns a selection, or None if we have no position."""
    st.caption(
        "Your browser will ask for permission before sharing your location. "
        "Nothing is shared unless you click Allow."
    )
    latitude = longitude = None

    if GEOLOCATION_AVAILABLE:
        st.write("Click the button, then choose **Allow** when the browser asks:")
        location = streamlit_geolocation() or {}
        latitude, longitude = location.get("latitude"), location.get("longitude")
    else:
        st.warning(
            "The browser-location add-on is not installed. Run "
            "`pip install streamlit-geolocation`, or choose a location manually."
        )

    # Backup: type the coordinates yourself (also handy for testing).
    with st.expander("Or type your coordinates"):
        lat_text = st.text_input("Latitude", placeholder="e.g. 8.87")
        lon_text = st.text_input("Longitude", placeholder="e.g. 7.02")
        if lat_text.strip() and lon_text.strip():
            try:
                latitude, longitude = float(lat_text), float(lon_text)
            except ValueError:
                st.error("Latitude and longitude must be numbers, like 8.87 and 7.02.")
                return None

    if latitude is None or longitude is None:
        st.info(
            "No location received yet. If you blocked the permission, that's fine — "
            "choose 'Choose location manually' above and everything works the same."
        )
        return None

    st.success(f"Location received: {latitude:.3f}, {longitude:.3f}")
    return make_selection(
        city=f"Your current location ({latitude:.2f}, {longitude:.2f})",
        latitude=latitude, longitude=longitude,
    )


def selection_from_favourite(fav):
    """Turns a saved favourite into a selection. New favourites carry their
    coordinates; old text-only ones are searched by name again."""
    label = fav.get("label", "")
    if fav.get("latitude") is not None and fav.get("longitude") is not None:
        return make_selection(city=label, latitude=fav["latitude"], longitude=fav["longitude"])
    parts = [p.strip() for p in label.split(",")]
    return make_selection(city=parts[0], country=", ".join(parts[1:]))


def time_picker():
    """A single dropdown of times like "5:30 PM". Returns (hour_24, minute, label)."""
    options = build_time_options(30)
    label = st.selectbox("Time", options, index=options.index(DEFAULT_TIME_LABEL))
    hour_24, minute = parse_time_label(label)       # "5:30 PM" -> (17, 30)
    st.caption(
        f"Forecasts are hour by hour, so we use the {format_hour(hour_24)} forecast "
        f"for {label} (the minutes don't change the weather data)."
    )
    return hour_24, minute, label


# --------------------------------------------------------------------------
# The main check: fetch -> analyse -> recommend -> advise -> save
# --------------------------------------------------------------------------

def get_ai_advice(gemini_key, activity, analyzed, engine, overall, time_label):
    """Returns (advice_text, warning). Gemini is optional: ANY problem falls
    back to the rule-based advice, so this function never raises."""
    if not gemini_key.strip():
        return engine.rule_based_advice(), (
            "No Gemini API key set — add one in the sidebar for an AI-generated "
            "explanation. Showing basic rule-based advice for now:"
        )
    summary = ", ".join(
        f"{format_hour(f.hour)} {f.description} {f.temperature_c:.0f}C "
        f"{f.precipitation_prob:.0f}% rain {f.wind_speed_kmh:.0f}kmh wind"
        for f, _, _ in analyzed[::3]  # every 3rd hour keeps the prompt short
    )
    try:
        with st.spinner("Asking Gemini for advice..."):
            text = ask_gemini(gemini_key.strip(), activity, summary,
                              overall_risk=overall, chosen_time=time_label)
        return text, None
    except WeatherDataError as e:
        return engine.rule_based_advice(), f"Gemini advice unavailable ({e}) Showing rule-based advice instead."
    except Exception as e:  # anything unexpected must not wipe the weather results
        return engine.rule_based_advice(), f"Gemini advice unavailable ({e}). Showing rule-based advice instead."


def run_check(store, client, selection, activity, target_date, preferred_hour, time_label, gemini_key):
    """Does the full fetch -> analyze -> recommend -> advise flow and saves
    the result into session_state."""
    try:
        with st.spinner("Looking up location..."):
            place = client.find_place(
                city=selection["city"], state=selection["state"], country=selection["country"],
                country_code=selection["country_code"], state_names=selection["state_names"],
                capital=selection["capital"],
                latitude=selection["latitude"], longitude=selection["longitude"],
            )

        with st.spinner("Fetching forecast..."):
            forecasts = client.get_forecast(place["latitude"], place["longitude"], target_date)

        analyzer = ActivityRiskAnalyzer(activity)
        analyzed = analyzer.analyze(forecasts)
        engine = RecommendationEngine(activity, analyzed)

        overall = engine.overall_risk()
        advice_text, advice_warning = get_ai_advice(
            gemini_key, activity, analyzed, engine, overall, time_label
        )

        # Everything needed to render the results lives in session_state so
        # it survives reruns triggered by clicking a checkbox or a button
        # below (Streamlit reruns the whole script on every widget click).
        st.session_state["result"] = {
            "place": place,
            "target_date": target_date,
            "activity": activity,
            "time_label": time_label,
            "overall": overall,
            "chosen": engine.risk_at(preferred_hour),
            "best": engine.best_time(preferred_hour),
            "reasons": engine.risk_reasons(),
            "activity_advice": engine.activity_advice(),
            "checklist": engine.packing_checklist(),
            "analyzed": analyzed,
            "advice_text": advice_text,
            "advice_warning": advice_warning,
        }

        # Save this search to history (file handling) - only once, right
        # when the check completes, not on every later rerun.
        store.add_history(
            {
                "location": place["label"],
                "activity": activity,
                "date": target_date.isoformat(),
                "risk": overall,
            }
        )

    except (LocationNotFoundError, WeatherDataError) as e:
        st.session_state.pop("result", None)
        st.error(str(e))
    except Exception as e:  # final safety net
        st.session_state.pop("result", None)
        st.error(f"Something unexpected went wrong: {e}")


# --------------------------------------------------------------------------
# Showing the results
# --------------------------------------------------------------------------

def show_results(store):
    r = st.session_state["result"]
    place, overall, best, chosen = r["place"], r["overall"], r["best"], r["chosen"]
    risk_colors = {"Safe": "green", "Manageable": "blue", "Risky": "orange", "Avoid": "red"}

    st.subheader(f"{place['label']} — {r['target_date'].strftime('%A, %d %b %Y')}")
    if place.get("note"):
        st.warning(place["note"])

    # Weather information at the time the user picked
    if chosen:
        cf, _, clabel = chosen
        st.markdown(f"#### 🌤️ Weather at {r['time_label']}: {cf.description}")
        col1, col2, col3 = st.columns(3)
        col1.metric("Temperature", f"{cf.temperature_c:.0f}°C")
        col2.metric("Rain chance", f"{cf.precipitation_prob:.0f}%")
        col3.metric("Wind", f"{cf.wind_speed_kmh:.0f} km/h")
        st.markdown(f"Risk at your chosen time: :{risk_colors.get(clabel, 'gray')}[**{clabel}**]")

    # Risk level + explanation
    st.markdown(
        f"### Overall risk for {r['activity']}: "
        f":{risk_colors.get(overall, 'gray')}[**{overall}**]"
    )
    st.caption("Based on the daytime hours (7 AM – 7 PM). The limits are simple project rules, not official safety standards.")
    st.markdown("**Why this rating?**")
    for reason in r["reasons"]:
        st.write(f"- {reason}")

    # Recommended time
    if best:
        bf, _, blabel = best
        st.write(
            f"**Best time:** {format_hour(bf.hour)} — {bf.description}, "
            f"{bf.temperature_c:.0f}°C, {bf.precipitation_prob:.0f}% rain chance, "
            f"{bf.wind_speed_kmh:.0f} km/h wind ({blabel})"
        )

    # Activity-specific advice
    st.markdown(f"#### 🧭 Advice for {r['activity'].lower()}")
    for tip in r["activity_advice"]:
        st.write(f"- {tip}")

    # AI advice (or the rule-based fallback)
    st.markdown("#### 🤖 Safety advice")
    if r["advice_warning"]:
        st.warning(r["advice_warning"])
    st.info(r["advice_text"])

    st.markdown("#### 🎒 Packing checklist")
    for item in r["checklist"]:
        st.checkbox(item, key=f"pack_{item}")

    with st.expander("Hourly forecast details"):
        for f, score, label in r["analyzed"]:
            st.write(f"{format_hour(f.hour)} — {describe_extremes(f)} → **{label}**")

    # Favourites and saved plans
    label = place["label"]
    fav_col1, fav_col2, fav_col3 = st.columns(3)
    with fav_col1:
        if st.button("⭐ Save location as favourite"):
            store.add_favourite(make_favourite(label, place["latitude"], place["longitude"]))
            st.success("Saved to favourites.")
    with fav_col2:
        if store.is_favourite(label):
            if st.button("Remove from favourites"):
                store.remove_favourite(label)
                st.success("Removed.")
    with fav_col3:
        if st.button("💾 Save this plan"):
            store.add_plan(
                {
                    "location": label,
                    "activity": r["activity"],
                    "date": r["target_date"].isoformat(),
                    "risk": overall,
                    "best_time": format_hour(best[0].hour) if best else "N/A",
                    "advice": r["advice_text"],
                    "checklist": r["checklist"],
                }
            )
            st.success("Plan saved — see 'Saved plans' in the sidebar.")


# --------------------------------------------------------------------------
# Sidebar + main page
# --------------------------------------------------------------------------

def show_sidebar(store):
    """Settings, favourites, history, plans. Returns the Gemini API key."""
    with st.sidebar:
        st.header("Settings")

        # The key is read from Streamlit secrets (.streamlit/secrets.toml) or an
        # environment variable, so normal users never see or enter it. The manual
        # input only appears as a fallback (e.g. for local testing without secrets set).
        try:
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            gemini_key = ""
        if not gemini_key:
            gemini_key = os.environ.get("GEMINI_API_KEY", "")

        if not gemini_key:
            st.markdown("**Gemini API key** (optional — for the AI safety explanation)")
            gemini_key = st.text_input("Gemini API key", type="password", label_visibility="collapsed")
            st.caption(
                "Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). "
                "Without a key the app uses a basic rule-based note instead of the AI explanation."
            )

        st.divider()
        st.subheader("⭐ Favourite locations")
        favourites = store.get_favourites()
        if favourites:
            labels = [fav.get("label", "") for fav in favourites]
            chosen_label = st.selectbox("Jump to a favourite", ["-"] + labels)
            if chosen_label != "-" and st.button("Use this favourite"):
                st.session_state["selected_favourite"] = favourites[labels.index(chosen_label)]
        else:
            st.caption("No favourites saved yet.")

        st.divider()
        st.subheader("🕓 Recent searches")
        history = store.get_history()
        if history:
            for h in history[:5]:
                st.caption(f"{h.get('location')} — {h.get('activity')} on {h.get('date')}")
        else:
            st.caption("No searches yet.")

        st.divider()
        st.subheader("📋 Saved plans")
        plans = store.get_plans()
        if plans:
            for i, p in enumerate(plans[:5]):
                with st.expander(f"{p.get('location')} — {p.get('activity')} ({p.get('date')})"):
                    st.caption(f"Risk: {p.get('risk')} | Best time: {p.get('best_time')}")
                    st.caption(", ".join(p.get("checklist", [])))
                    if st.button("Delete", key=f"del_plan_{i}"):
                        store.remove_plan(i)
                        st.rerun()
        else:
            st.caption("No saved plans yet.")
    return gemini_key


def main():
    st.set_page_config(page_title="Weather Risk & Outdoor Activity Planner", page_icon="⛅")
    st.title("⛅ Weather Risk & Outdoor Activity Planner")
    st.caption(
        "Pick a location and an activity — we'll check the forecast, flag the risk, "
        "suggest the best time, and build a packing list."
    )

    store = HistoryStore()
    client = WeatherClient()
    gemini_key = show_sidebar(store)

    try:
        data = get_location_data()
    except WeatherDataError as e:
        st.warning(f"{e} You can still type a place for any country.")
        data = {"countries": {}}

    # ---- Location ----
    st.markdown("#### Location")
    favourite = st.session_state.get("selected_favourite")
    if favourite:
        # A favourite chosen in the sidebar replaces the pickers until cleared.
        st.info(f"⭐ Using favourite: **{favourite.get('label')}**")
        if st.button("Choose a different location"):
            st.session_state.pop("selected_favourite", None)
            st.rerun()
        selection = selection_from_favourite(favourite)
    else:
        mode = st.radio("How do you want to choose the location?", [MODE_CURRENT, MODE_MANUAL],
                        index=1, horizontal=True)
        if mode == MODE_CURRENT:
            selection = current_location_picker()
        else:
            selection = manual_location_picker(data)

    # ---- Activity, date, time ----
    st.markdown("#### Activity")
    activity = st.selectbox("Activity", list(ACTIVITIES.keys()))

    st.markdown("#### Date")
    today = date.today()
    target_date = st.date_input(
        "Date", value=today, min_value=today, max_value=today + timedelta(days=FORECAST_DAYS_AHEAD)
    )

    st.markdown("#### Time")
    preferred_hour, _minute, time_label = time_picker()

    if st.button("Check weather & risk", type="primary"):
        if selection is None:
            st.error("Please choose a location first (or type a city / town).")
        else:
            run_check(store, client, selection, activity, target_date,
                      preferred_hour, time_label, gemini_key)

    # Render the last computed result, if any. Living outside the button's `if`
    # block means clicking a checklist item or a save button (which reruns the
    # whole app) no longer makes the results disappear.
    if "result" in st.session_state:
        show_results(store)


if __name__ == "__main__":
    main()
