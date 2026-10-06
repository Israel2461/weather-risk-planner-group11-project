from dataclasses import dataclass, field


@dataclass
class Forecast:
    """One hour's worth of weather data."""
    time: str
    temperature_c: float
    precipitation_prob: float
    wind_speed_kmh: float
    weather_code: int
    description: str = field(default="")

    @property
    def hour(self) -> int:
        return int(self.time[11:13])
