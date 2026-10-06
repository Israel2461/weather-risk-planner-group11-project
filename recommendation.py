from typing import Optional

from risk_analyzer import (
    ACTIVITIES, RISK_LEVELS, ActivityRiskAnalyzer, STORM_CODES, FOG_CODES,
)
from time_utils import format_hour

# "Daytime" for this app means 7:00 AM to 7:59 PM.
DAY_START_HOUR = 7
DAY_END_HOUR = 19

# Extra things to pack for each activity (added to the weather-based items).
ACTIVITY_EXTRAS = {
    "Football": ["Football boots", "Shin guards", "Spare kit"],
    "Jogging / Running": ["Running shoes", "Moisture-wicking clothing"],
    "Farming": ["Gloves", "Boots", "Hat"],
    "Picnic": ["Picnic blanket", "Cooler bag", "Insect repellent"],
    "Travelling": ["Travel documents", "Power bank"],
    "Outdoor event": ["Portable chair", "Snacks"],
    "Hiking": ["Hiking boots", "Trekking pole", "First aid kit"],
    "Cycling": ["Helmet", "Reflective vest", "Bike repair kit"],
    "Camping": ["Tent", "Sleeping bag", "Flashlight/torch"],
    "Fishing": ["Fishing rod & tackle", "Life jacket", "Cooler for catch"],
    "Swimming / Beach day": ["Swimwear", "Towel", "Waterproof bag"],
    "Outdoor wedding / ceremony": ["Umbrella (just in case)", "Change of shoes", "Portable fan"],
    "Gardening": ["Gardening gloves", "Sun hat", "Pruning shears"],
    "Construction / outdoor work": ["Safety helmet", "High-visibility vest", "Work gloves"],
    "Motorcycle / bike riding": ["Rain poncho", "Helmet", "Reflective gear"],
    "Market / outdoor trading": ["Tarpaulin cover", "Umbrella", "Cash pouch"],
}


class RecommendationEngine:
    def __init__(self, activity: str, analyzed: list):
        self.activity = activity
        self.analyzed = analyzed  # list of (Forecast, score, label)

    # ---- helpers --------------------------------------------------------
    def _daytime_items(self) -> list:
        """The (Forecast, score, label) items between 7 AM and 7 PM (or all
        hours if the forecast has no daytime hours)."""
        daytime = [item for item in self.analyzed if DAY_START_HOUR <= item[0].hour <= DAY_END_HOUR]
        return daytime or self.analyzed

    def risk_at(self, hour: int) -> Optional[tuple]:
        """The (Forecast, score, label) item for one specific hour, or None."""
        for item in self.analyzed:
            if item[0].hour == hour:
                return item
        return None

    # ---- recommendations ------------------------------------------------
    def best_time(self, preferred_hour: Optional[int] = None) -> Optional[tuple]:
        """Lowest-risk hour during the daytime. Ties go to the hour closest to
        the user's preferred hour (or 3 PM if none was given). The user's own
        preferred hour is always allowed as a candidate, even at night."""
        if not self.analyzed:
            return None
        anchor = preferred_hour if preferred_hour is not None else 15
        candidates = list(self._daytime_items())
        chosen = self.risk_at(preferred_hour) if preferred_hour is not None else None
        if chosen is not None and chosen not in candidates:
            candidates.append(chosen)
        return min(candidates, key=lambda item: (item[1], abs(item[0].hour - anchor)))

    def overall_risk(self) -> str:
        # Judge the daytime window as a whole.
        pool = self._daytime_items()
        avg_score = sum(item[1] for item in pool) / len(pool)
        # int(x + 0.5) always rounds .5 UP (Python's round() would round 0.5 down to 0).
        return RISK_LEVELS[int(avg_score + 0.5)]

    def risk_reasons(self) -> list:
        """Plain-English sentences explaining which weather factors push the
        risk up for this activity (only factors that matter for it)."""
        rules = ACTIVITIES[self.activity]
        concerns = rules["concerns"]
        forecasts = [item[0] for item in self._daytime_items()]
        reasons = []

        storm_hours = [format_hour(f.hour) for f in forecasts if f.weather_code in STORM_CODES]
        if "storm" in concerns and storm_hours:
            reasons.append(f"Thunderstorms are forecast around {', '.join(storm_hours)}.")

        if "rain" in concerns:
            top_rain = max(f.precipitation_prob for f in forecasts)
            if top_rain > rules["max_rain_chance"]:
                reasons.append(
                    f"Rain chance reaches {top_rain:.0f}% (limit used for {self.activity.lower()}: "
                    f"{rules['max_rain_chance']}%)."
                )
        if "wind" in concerns:
            top_wind = max(f.wind_speed_kmh for f in forecasts)
            if top_wind > rules["max_wind"]:
                reasons.append(
                    f"Wind reaches {top_wind:.0f} km/h (limit: {rules['max_wind']} km/h)."
                )
        if "heat" in concerns:
            top_temp = max(f.temperature_c for f in forecasts)
            if top_temp > rules["max_temp"]:
                reasons.append(f"Temperature reaches {top_temp:.0f}°C (limit: {rules['max_temp']}°C).")
        if "cold" in concerns:
            low_temp = min(f.temperature_c for f in forecasts)
            if low_temp < rules["min_temp"]:
                reasons.append(f"Temperature drops to {low_temp:.0f}°C (minimum: {rules['min_temp']}°C).")
        if "fog" in concerns and any(f.weather_code in FOG_CODES for f in forecasts):
            reasons.append("Fog is forecast, so visibility may be poor.")

        if not reasons:
            reasons.append(
                f"No weather factor goes beyond the limits used for {self.activity.lower()} "
                f"during the daytime."
            )
        return reasons

    def activity_advice(self) -> list:
        """Activity-specific tips, but only for the weather problems that
        actually happen at some point during the day."""
        analyzer = ActivityRiskAnalyzer(self.activity)
        tips = ACTIVITIES[self.activity]["tips"]
        seen = []
        for f, _, _ in self.analyzed:
            for hazard in analyzer.find_hazards(f):
                if hazard not in seen:
                    seen.append(hazard)

        advice = [tips[hazard] for hazard in seen if hazard in tips]
        if not advice:
            advice = [f"Weather looks fine for {self.activity.lower()}. Still check the forecast again before you leave."]
        return advice

    def packing_checklist(self) -> list:
        checklist = {"Water bottle", "Phone / ID"}
        temps = [f.temperature_c for f, _, _ in self.analyzed]
        rains = [f.precipitation_prob for f, _, _ in self.analyzed]
        winds = [f.wind_speed_kmh for f, _, _ in self.analyzed]

        if max(rains, default=0) > 40:
            checklist.update({"Umbrella or rain jacket", "Waterproof bag cover"})
        if max(temps, default=20) > 30:
            checklist.update({"Sunscreen", "Sunglasses", "Extra water"})
        if min(temps, default=20) < 12:
            checklist.update({"Warm jacket", "Gloves"})
        if max(winds, default=0) > 35:
            checklist.add("Windbreaker")

        checklist.update(ACTIVITY_EXTRAS.get(self.activity, []))
        return sorted(checklist)

    def rule_based_advice(self) -> str:
        overall = self.overall_risk()
        best = self.best_time()
        best_hour = format_hour(best[0].hour) if best else "N/A"
        return (
            f"Overall, conditions for {self.activity.lower()} today look **{overall.lower()}**. "
            f"The best window is around **{best_hour}**, when risk is lowest. "
            f"Keep an eye on wind and rain chances before heading out."
        )
