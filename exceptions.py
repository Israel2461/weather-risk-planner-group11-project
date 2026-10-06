class LocationNotFoundError(Exception):
    """Raised when a location can't be geocoded (bad/unknown location name)."""
    pass


class WeatherDataError(Exception):
    """Raised for network errors, bad API responses, or missing weather/AI data."""
    pass
