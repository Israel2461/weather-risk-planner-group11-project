from models import Forecast

# Weather codes (from Open-Meteo) that mean a particular problem.
STORM_CODES = (95, 96, 99)
FOG_CODES = (45, 48)
HEAVY_RAIN_CODES = (65, 82)

ACTIVITIES = {
    "Football": {
        "max_wind": 40, "max_rain_chance": 60, "min_temp": 5, "max_temp": 38,
        "concerns": ["rain", "wind", "heat", "storm"],
        "tips": {
            "rain": "A wet pitch means slips and ankle injuries. Wear boots with good grip, or move the match.",
            "wind": "Strong wind spoils passing and long balls. Shorten the game or pick a sheltered pitch.",
            "heat": "Hot hours cause cramps and heat exhaustion. Take a water break every 15 minutes or play early/late.",
            "storm": "Never play in a thunderstorm — an open field attracts lightning. Stop and take shelter at once.",
        },
    },
    "Jogging / Running": {
        "max_wind": 45, "max_rain_chance": 70, "min_temp": -5, "max_temp": 33,
        "concerns": ["rain", "wind", "heat", "storm"],
        "tips": {
            "rain": "Wet roads are slippery. Shorten your stride, wear shoes with grip and a light rain jacket.",
            "wind": "Headwinds make a run much harder. Plan the first half into the wind so you finish with it behind you.",
            "heat": "Run at sunrise or after sunset, drink before you feel thirsty, and slow down if you feel dizzy.",
            "storm": "Skip the run during thunderstorms; use a treadmill or rest.",
        },
    },
    "Farming": {
        "max_wind": 50, "max_rain_chance": 80, "min_temp": 2, "max_temp": 40,
        "concerns": ["rain", "heat", "storm"],
        "tips": {
            "rain": "Heavy rain makes fields muddy and can wash away seeds or fertiliser. Delay planting and spraying.",
            "heat": "Work early morning and late afternoon, rest in shade at midday and keep drinking water.",
            "storm": "Leave open fields and put machinery away — farmers in open fields are at high risk from lightning.",
        },
    },
    "Picnic": {
        "max_wind": 30, "max_rain_chance": 40, "min_temp": 12, "max_temp": 34,
        "concerns": ["rain", "wind", "heat", "cold", "storm"],
        "tips": {
            "rain": "Rain ends a picnic quickly. Choose a spot with a shelter or have a covered backup plan.",
            "wind": "Wind blows plates and napkins away. Weigh things down and sit in a sheltered spot.",
            "heat": "Sit in shade and keep food in a cooler bag so it does not spoil.",
            "cold": "It may feel chilly. Bring a sweater and a hot drink.",
            "storm": "Pack up and shelter indoors if thunder starts; do not stand under lone trees.",
        },
    },
    "Travelling": {
        "max_wind": 60, "max_rain_chance": 85, "min_temp": -10, "max_temp": 45,
        "concerns": ["rain", "wind", "fog", "storm"],
        "tips": {
            "rain": "Wet roads mean longer braking distances and delays. Leave early and drive slowly.",
            "wind": "Strong wind is dangerous for high-sided vehicles and motorbikes. Keep both hands on the wheel.",
            "fog": "Fog cuts visibility. Use low-beam lights, slow down and keep a big gap behind other vehicles.",
            "storm": "Avoid starting a long journey in a thunderstorm; pull over somewhere safe if caught in one.",
        },
    },
    "Outdoor event": {
        "max_wind": 35, "max_rain_chance": 30, "min_temp": 10, "max_temp": 34,
        "concerns": ["rain", "wind", "heat", "cold", "storm"],
        "tips": {
            "rain": "Book a canopy or tent and keep sound equipment covered, or have an indoor backup venue.",
            "wind": "Secure tents, banners and decorations firmly; strong wind can topple them onto guests.",
            "heat": "Provide shade, cold drinks and seating for guests, especially elderly people and children.",
            "cold": "Evening guests may get cold. Consider blankets or a heater.",
            "storm": "Have a clear plan to move everyone indoors fast — tents do not protect against lightning.",
        },
    },
    "Hiking": {
        "max_wind": 45, "max_rain_chance": 55, "min_temp": 0, "max_temp": 35,
        "concerns": ["rain", "wind", "heat", "fog", "storm"],
        "tips": {
            "rain": "Wet trails and rocks are slippery and streams can rise quickly. Wear boots with grip and avoid steep sections.",
            "wind": "Wind on ridges and open slopes can knock you off balance. Stay off exposed edges.",
            "heat": "Start at dawn, carry extra water (about 0.5 L per hour) and rest in shade.",
            "fog": "Fog makes trails hard to follow. Stay on marked paths and keep your group together.",
            "storm": "Do not hike during thunderstorms. Get off peaks and ridges and away from tall lone trees.",
        },
    },
    "Cycling": {
        "max_wind": 35, "max_rain_chance": 50, "min_temp": 5, "max_temp": 36,
        "concerns": ["wind", "rain", "heat", "fog", "storm"],
        "tips": {
            "wind": "Crosswinds can push you into traffic. Ride in a lower gear and keep both hands on the bars.",
            "rain": "Wet brakes are weaker and road paint is slippery. Brake early, avoid puddles and wear lights.",
            "heat": "Carry two bottles of water, wear a light cap under your helmet and avoid the midday sun.",
            "fog": "Use front and rear lights and a bright vest; drivers will see you late.",
            "storm": "Do not ride in a thunderstorm. Shelter in a building, not under a tree.",
        },
    },
    "Camping": {
        "max_wind": 40, "max_rain_chance": 50, "min_temp": 5, "max_temp": 38,
        "concerns": ["rain", "wind", "heat", "cold", "storm"],
        "tips": {
            "rain": "Pitch the tent on higher ground (not in a dip), use a groundsheet and keep gear in waterproof bags.",
            "wind": "Use all the tent pegs and guy ropes, and camp away from dead branches that could fall.",
            "heat": "Pitch under shade, ventilate the tent and keep plenty of drinking water.",
            "cold": "Bring a warm sleeping bag and extra layers; nights are colder than the forecast hours show.",
            "storm": "Do not stay on open ground or under tall trees. Move to a building or a car if you can.",
        },
    },
    "Fishing": {
        "max_wind": 35, "max_rain_chance": 60, "min_temp": 5, "max_temp": 40,
        "concerns": ["wind", "rain", "heat", "storm"],
        "tips": {
            "wind": "Wind makes water rough and boats unstable. Stay close to shore and wear a life jacket.",
            "rain": "Rain makes banks and boat decks slippery. Wear non-slip shoes and keep electronics dry.",
            "heat": "Wear a hat and sunscreen — the sun reflects off the water — and carry extra drinking water.",
            "storm": "Get off the water immediately; a fishing rod is a lightning rod.",
        },
    },
    "Swimming / Beach day": {
        "max_wind": 30, "max_rain_chance": 20, "min_temp": 22, "max_temp": 40,
        "concerns": ["rain", "wind", "cold", "heat", "storm"],
        "tips": {
            "rain": "Rain spoils a beach day. Check the water is not muddy or polluted by runoff before swimming.",
            "wind": "Wind brings rougher waves and stronger currents. Swim only where lifeguards are present.",
            "cold": "Cool air and water cause chills quickly. Keep swims short and bring a towel and dry clothes.",
            "heat": "Use high-factor sunscreen, wear a hat and stay hydrated; avoid the strongest sun at midday.",
            "storm": "Leave the water and the beach at once when thunder is heard.",
        },
    },
    "Outdoor wedding / ceremony": {
        "max_wind": 25, "max_rain_chance": 15, "min_temp": 15, "max_temp": 36,
        "concerns": ["rain", "wind", "heat", "cold", "storm"],
        "tips": {
            "rain": "Have a tent or indoor backup ready, and keep a few umbrellas for guests and the photographer.",
            "wind": "Secure decorations, veils and flowers. Strong wind can topple arches and tents.",
            "heat": "Provide shade, fans and water for guests, and schedule the ceremony for the cooler part of the day.",
            "cold": "Guests may need shawls or jackets, especially in the evening.",
            "storm": "Plan a fast, safe move indoors for everyone — tents are not safe in lightning.",
        },
    },
    "Gardening": {
        "max_wind": 45, "max_rain_chance": 70, "min_temp": 5, "max_temp": 38,
        "concerns": ["rain", "heat", "wind", "storm"],
        "tips": {
            "rain": "Heavy rain makes soil soggy and compacted. Wait for the soil to drain before digging or planting.",
            "heat": "Water plants early morning or evening, and work in shade during the hottest hours.",
            "wind": "Wind dries soil and snaps young plants. Stake tall plants and delay spraying.",
            "storm": "Go indoors and put tools away — metal tools attract lightning.",
        },
    },
    "Construction / outdoor work": {
        "max_wind": 30, "max_rain_chance": 50, "min_temp": 0, "max_temp": 42,
        "concerns": ["wind", "rain", "heat", "storm"],
        "tips": {
            "wind": "Stop crane lifts and work on scaffolding or roofs when gusts are strong; secure loose materials.",
            "rain": "Wet surfaces and mud increase slips and electrical risks. Cover materials and postpone concrete pouring.",
            "heat": "Schedule heavy work early, give regular shaded breaks and provide drinking water for all workers.",
            "storm": "Stop all work at height and with machinery; move workers to a safe building.",
        },
    },
    "Motorcycle / bike riding": {
        "max_wind": 35, "max_rain_chance": 35, "min_temp": 10, "max_temp": 40,
        "concerns": ["rain", "wind", "fog", "heat", "storm"],
        "tips": {
            "rain": "Wet roads cut grip sharply. Brake gently, avoid road paint and manhole covers, and wear a rain suit.",
            "wind": "Gusts push a bike sideways, especially on bridges and when passing trucks. Slow down.",
            "fog": "Visibility is poor. Use headlights, wear bright gear and keep a larger distance from other vehicles.",
            "heat": "Wear a ventilated helmet and jacket, and stop to drink water regularly.",
            "storm": "Do not ride in a thunderstorm. Park safely and shelter in a building.",
        },
    },
    "Market / outdoor trading": {
        "max_wind": 40, "max_rain_chance": 50, "min_temp": 10, "max_temp": 40,
        "concerns": ["rain", "wind", "heat", "storm"],
        "tips": {
            "rain": "Cover goods with tarpaulin and raise stock off the ground so it does not get soaked.",
            "wind": "Tie down canopies and light goods; stalls and umbrellas can fly off in strong gusts.",
            "heat": "Keep fresh food in shade or on ice, and drink water often to stay alert.",
            "storm": "Close the stall and take shelter; metal stall frames and umbrellas are dangerous in lightning.",
        },
    },
}

RISK_LEVELS = ["Safe", "Manageable", "Risky", "Avoid"]


class ActivityRiskAnalyzer:
    """Scores an hour's forecast against an activity's tolerance thresholds."""

    def __init__(self, activity: str):
        if activity not in ACTIVITIES:
            raise ValueError(f"Unknown activity: {activity}")
        self.activity = activity
        self.rules = ACTIVITIES[activity]

    def find_hazards(self, f: Forecast) -> list:
        """Returns the list of weather problems (e.g. ["rain", "heat"]) that
        are present in this hour AND matter for this activity."""
        rules = self.rules
        concerns = rules["concerns"]
        hazards = []

        if "storm" in concerns and f.weather_code in STORM_CODES:
            hazards.append("storm")
        if "rain" in concerns and (
            f.precipitation_prob > rules["max_rain_chance"] or f.weather_code in HEAVY_RAIN_CODES
        ):
            hazards.append("rain")
        if "wind" in concerns and f.wind_speed_kmh > rules["max_wind"]:
            hazards.append("wind")
        if "heat" in concerns and f.temperature_c > rules["max_temp"]:
            hazards.append("heat")
        if "cold" in concerns and f.temperature_c < rules["min_temp"]:
            hazards.append("cold")
        if "fog" in concerns and f.weather_code in FOG_CODES:
            hazards.append("fog")
        return hazards

    def score_hour(self, f: Forecast) -> int:
        """Returns a risk score: 0=Safe, 1=Manageable, 2=Risky, 3=Avoid."""
        rules = self.rules

        # Thunderstorms are an automatic "Avoid" for every activity.
        if f.weather_code in STORM_CODES:
            return 3

        # One point for each weather problem that applies to this activity.
        score = len(self.find_hazards(f))

        # One extra point when wind or rain is far beyond the limit.
        very_windy = "wind" in rules["concerns"] and f.wind_speed_kmh > rules["max_wind"] * 1.4
        very_wet = "rain" in rules["concerns"] and f.precipitation_prob > min(95, rules["max_rain_chance"] + 25)
        if very_windy or very_wet:
            score += 1

        return min(score, 3)

    def analyze(self, forecasts: list) -> list:
        """Returns list of (Forecast, risk_score, risk_label) tuples."""
        results = []
        for f in forecasts:
            score = self.score_hour(f)
            results.append((f, score, RISK_LEVELS[score]))
        return results