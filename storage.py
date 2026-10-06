import json
import os

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "planner_data.json")


def make_favourite(label: str, latitude=None, longitude=None) -> dict:
    """A favourite is a small dictionary: its display name plus coordinates.
    Saving the coordinates means a favourite never needs to be searched for again."""
    return {"label": label, "latitude": latitude, "longitude": longitude}


class HistoryStore:
    """Reads/writes favourite locations, previous searches, and saved plans as JSON.

    Favourites used to be saved as plain text like "Ikeja, Nigeria". Those old
    entries are still understood: _load() converts them to the new dictionary
    format (without coordinates) when the file is read.
    """

    def __init__(self, path: str = DATA_FILE):
        self.path = path

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"favourites": [], "history": [], "plans": []}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("favourites", [])
                data.setdefault("history", [])
                data.setdefault("plans", [])
                data["favourites"] = [
                    make_favourite(fav) if isinstance(fav, str) else fav
                    for fav in data["favourites"]
                ]
                return data
        except (json.JSONDecodeError, OSError):
            # Corrupted or unreadable file -> start fresh rather than crash.
            return {"favourites": [], "history": [], "plans": []}

    def _save(self, data: dict) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass  # Caller can check get_* results; a failed save shouldn't crash the app.

    def get_favourites(self) -> list:
        """List of favourite dictionaries: {"label", "latitude", "longitude"}."""
        return self._load()["favourites"]

    def add_favourite(self, favourite) -> None:
        """Accepts a favourite dictionary (or a plain text label)."""
        if isinstance(favourite, str):
            favourite = make_favourite(favourite)
        data = self._load()
        labels = [fav.get("label") for fav in data["favourites"]]
        if favourite.get("label") not in labels:
            data["favourites"].append(favourite)
            self._save(data)

    def is_favourite(self, label: str) -> bool:
        return label in [fav.get("label") for fav in self.get_favourites()]

    def remove_favourite(self, label: str) -> None:
        """Removes the favourite with this label."""
        data = self._load()
        remaining = [fav for fav in data["favourites"] if fav.get("label") != label]
        if len(remaining) != len(data["favourites"]):
            data["favourites"] = remaining
            self._save(data)

    def get_history(self) -> list:
        return self._load()["history"]

    def add_history(self, entry: dict) -> None:
        data = self._load()
        data["history"].insert(0, entry)
        data["history"] = data["history"][:20]  # keep last 20 searches
        self._save(data)

    def get_plans(self) -> list:
        return self._load()["plans"]

    def add_plan(self, plan: dict) -> None:
        data = self._load()
        data["plans"].insert(0, plan)
        data["plans"] = data["plans"][:20]  # keep last 20 saved plans
        self._save(data)

    def remove_plan(self, index: int) -> None:
        data = self._load()
        if 0 <= index < len(data["plans"]):
            data["plans"].pop(index)
            self._save(data)
