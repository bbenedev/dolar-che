"""The only place that talks to the internet: current rates and daily history. Read-only."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from .core import DayClose, DolarError, Quote, parse_history, parse_quotes

DOLARES_URL = "https://dolarapi.com/v1/dolares"
MONEDAS_URL = "https://dolarapi.com/v1/cotizaciones"
HISTORY_URL = "https://api.argentinadatos.com/v1/cotizaciones/dolares/{rate}"

# Both services refuse Python's default User-Agent, so the bot says who it is.
HEADERS = {"User-Agent": "DOLAR-CHE/1.0 (Discord bot; +https://github.com/bbenedev/dolar-che)"}
CACHE_SECONDS = 60
HISTORY_CACHE_SECONDS = 600

Fetch = Callable[[str], object]


def fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise DolarError("Uh, no pude traer las cotizaciones. Probá en un ratito.") from None


class Rates:
    """Current rates and history, cached for a minute: many people asking at once cost one request."""

    def __init__(self, fetch: Fetch = fetch_json, clock: Callable[[], float] = time.monotonic):
        self._fetch = fetch
        self._clock = clock
        self._cache: dict[str, tuple[float, object]] = {}

    def _get(self, url: str, ttl: float = CACHE_SECONDS) -> object:
        hit = self._cache.get(url)
        if hit and self._clock() - hit[0] < ttl:
            return hit[1]
        data = self._fetch(url)
        self._cache[url] = (self._clock(), data)
        return data

    def dollars(self) -> dict[str, Quote]:
        return parse_quotes(self._get(DOLARES_URL))

    def currencies(self) -> dict[str, Quote]:
        # This list repeats the US dollar; other currencies are keyed by their code.
        quotes = parse_quotes(self._get(MONEDAS_URL), key_field="moneda")
        quotes.pop("USD", None)
        return quotes

    def history(self, rate: str) -> list[DayClose]:
        # Daily data that is large and changes once a day: keep it for ten minutes.
        return parse_history(self._get(HISTORY_URL.format(rate=rate), HISTORY_CACHE_SECONDS))

    def histories(self, rates: tuple[str, ...]) -> dict[str, list[DayClose]]:
        """History of several rates; one that fails is left out instead of failing them all."""
        out = {}
        for rate in rates:
            try:
                out[rate] = self.history(rate)
            except DolarError:
                continue
        return out
