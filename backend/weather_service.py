"""
OpenWeatherMap Weather Service
Fetches real-time weather data to detect rainfall and waterlogging risk.
Used by VRP solver to penalize road segments near stations with heavy rain.

API: https://api.openweathermap.org/data/2.5/weather
Response includes: rain.1h (mm/hr), weather[0].main, weather[0].description
"""
import requests
import os
import random
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

# OpenWeatherMap Current Weather API
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

# Rainfall thresholds (mm/hr) — based on IMD classification
RAIN_LIGHT = 2.5       # < 2.5 mm/hr → no penalty
RAIN_MODERATE = 7.5    # 2.5–7.5 mm/hr → moderate penalty (road is slow)
# >= 7.5 mm/hr → heavy/very heavy → severe penalty (likely waterlogging)

# Cost penalties applied to road segments near rainy stations
PENALTY_MODERATE = 3.0   # 3× cost → pgRouting will prefer alternate roads
PENALTY_SEVERE = 10.0    # 10× cost → pgRouting will strongly avoid these roads


class OpenWeatherService:
    """Fetches live weather data using OpenWeatherMap API"""

    def __init__(self):
        self.api_key = os.getenv("OPENWEATHER_API_KEY", "")
        self._api_reachable: Optional[bool] = None
        self.simulate_rain = os.getenv("WEATHER_SIMULATE_RAIN", "").lower() in ("true", "1", "yes")

    def _simulate_monsoon(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Simulate monsoon-like rainfall for testing.
        Uses lat/lon hash so the same stations always get rain (deterministic).
        ~40% of stations get rain, split between moderate and heavy.
        """
        # Deterministic randomness based on location — same station = same weather
        seed = int(abs(lat * 10000 + lon * 10000)) % 100
        
        if seed < 15:
            # ~15% get heavy rain (waterlogging risk)
            rain_mm = round(random.uniform(8.0, 18.0), 1)
            return {
                "rain_mm": rain_mm,
                "description": f"Heavy Rain ({rain_mm} mm/hr) [SIMULATED]",
                "weather_main": "Rain",
                "severity": "heavy",
                "penalty_factor": PENALTY_SEVERE,
                "temp_c": round(random.uniform(22, 28), 1),
                "humidity": random.randint(85, 98),
                "wind_speed": round(random.uniform(5, 15), 1),
            }
        elif seed < 40:
            # ~25% get moderate rain
            rain_mm = round(random.uniform(3.0, 7.0), 1)
            return {
                "rain_mm": rain_mm,
                "description": f"Moderate Rain ({rain_mm} mm/hr) [SIMULATED]",
                "weather_main": "Rain",
                "severity": "moderate",
                "penalty_factor": PENALTY_MODERATE,
                "temp_c": round(random.uniform(24, 30), 1),
                "humidity": random.randint(75, 90),
                "wind_speed": round(random.uniform(3, 8), 1),
            }
        else:
            # ~60% stay clear
            return {
                "rain_mm": 0.0,
                "description": "Overcast Clouds [SIMULATED]",
                "weather_main": "Clouds",
                "severity": "none",
                "penalty_factor": 1.0,
                "temp_c": round(random.uniform(26, 32), 1),
                "humidity": random.randint(60, 80),
                "wind_speed": round(random.uniform(1, 5), 1),
            }

    def get_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Get current weather for a lat/lon coordinate.

        Returns:
            {
                "rain_mm": float,          # precipitation in mm/hr (0 if no rain)
                "description": str,        # e.g. "Heavy Rain", "Light Rain", "Clear"
                "weather_main": str,       # e.g. "Rain", "Thunderstorm", "Clear"
                "severity": str,           # "none", "moderate", "heavy"
                "penalty_factor": float,   # 1.0, 3.0, or 10.0
                "temp_c": float,           # temperature in Celsius
                "humidity": int,           # humidity %
                "wind_speed": float,       # wind speed in m/s
            }
        """
        # SIMULATION MODE — fake monsoon conditions for testing
        if self.simulate_rain:
            return self._simulate_monsoon(lat, lon)

        default = {
            "rain_mm": 0.0,
            "description": "Unknown",
            "weather_main": "Unknown",
            "severity": "none",
            "penalty_factor": 1.0,
            "temp_c": 0.0,
            "humidity": 0,
            "wind_speed": 0.0,
        }

        if not self.api_key:
            return default

        # Don't retry after a confirmed failure
        if self._api_reachable is False:
            return default

        try:
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric",  # Celsius, m/s (rain is always mm)
            }

            response = requests.get(OWM_URL, params=params, timeout=8)

            if response.status_code == 200:
                self._api_reachable = True
                data = response.json()

                # Extract rainfall (mm/hr)
                rain_mm = 0.0
                if "rain" in data:
                    rain_mm = data["rain"].get("1h", data["rain"].get("3h", 0.0))
                # Thunderstorm with rain
                if "thunderstorm" in str(data.get("weather", [{}])[0].get("main", "")).lower():
                    rain_mm = max(rain_mm, 5.0)  # Assume at least moderate if thunderstorm

                # Weather description
                weather_info = data.get("weather", [{}])[0]
                description = weather_info.get("description", "Unknown").title()
                weather_main = weather_info.get("main", "Unknown")

                # Determine severity and penalty
                if rain_mm >= RAIN_MODERATE:
                    severity = "heavy"
                    penalty = PENALTY_SEVERE
                    description = f"Heavy Rain ({rain_mm:.1f} mm/hr)"
                elif rain_mm >= RAIN_LIGHT:
                    severity = "moderate"
                    penalty = PENALTY_MODERATE
                    description = f"Moderate Rain ({rain_mm:.1f} mm/hr)"
                else:
                    severity = "none"
                    penalty = 1.0

                return {
                    "rain_mm": round(rain_mm, 2),
                    "description": description,
                    "weather_main": weather_main,
                    "severity": severity,
                    "penalty_factor": penalty,
                    "temp_c": round(data.get("main", {}).get("temp", 0), 1),
                    "humidity": data.get("main", {}).get("humidity", 0),
                    "wind_speed": round(data.get("wind", {}).get("speed", 0), 1),
                }

            elif response.status_code in (401, 403):
                self._api_reachable = False
                print(
                    f"⚠️  OpenWeatherMap auth failed ({response.status_code}) — "
                    f"check OPENWEATHER_API_KEY in .env"
                )
            elif response.status_code == 429:
                print("⚠️  OpenWeatherMap rate limit reached — skipping weather check")
            else:
                print(
                    f"⚠️  OpenWeatherMap API error {response.status_code}: "
                    f"{response.text[:120]}"
                )

        except requests.exceptions.Timeout:
            print("⚠️  OpenWeatherMap API timeout — skipping weather check")
        except Exception as exc:
            print(f"⚠️  Weather service error: {exc}")

        return default

    async def get_weather_async(self, lat: float, lon: float, client: Optional['httpx.AsyncClient'] = None) -> Dict[str, Any]:
        """Async version of get_weather using httpx."""
        if self.simulate_rain:
            return self._simulate_monsoon(lat, lon)

        default = {
            "rain_mm": 0.0,
            "description": "Unknown",
            "weather_main": "Unknown",
            "severity": "none",
            "penalty_factor": 1.0,
            "temp_c": 0.0,
            "humidity": 0,
            "wind_speed": 0.0,
        }

        if not self.api_key or self._api_reachable is False:
            return default

        import httpx
        try:
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric",
            }

            if client:
                response = await client.get(OWM_URL, params=params, timeout=8)
            else:
                async with httpx.AsyncClient() as c:
                    response = await c.get(OWM_URL, params=params, timeout=8)

            if response.status_code == 200:
                self._api_reachable = True
                data = response.json()

                rain_mm = 0.0
                if "rain" in data:
                    rain_mm = data["rain"].get("1h", data["rain"].get("3h", 0.0))
                if "thunderstorm" in str(data.get("weather", [{}])[0].get("main", "")).lower():
                    rain_mm = max(rain_mm, 5.0)

                weather_info = data.get("weather", [{}])[0]
                description = weather_info.get("description", "Unknown").title()
                weather_main = weather_info.get("main", "Unknown")

                if rain_mm >= RAIN_MODERATE:
                    severity = "heavy"
                    penalty = PENALTY_SEVERE
                    description = f"Heavy Rain ({rain_mm:.1f} mm/hr)"
                elif rain_mm >= RAIN_LIGHT:
                    severity = "moderate"
                    penalty = PENALTY_MODERATE
                    description = f"Moderate Rain ({rain_mm:.1f} mm/hr)"
                else:
                    severity = "none"
                    penalty = 1.0

                return {
                    "rain_mm": round(rain_mm, 2),
                    "description": description,
                    "weather_main": weather_main,
                    "severity": severity,
                    "penalty_factor": penalty,
                    "temp_c": round(data.get("main", {}).get("temp", 0), 1),
                    "humidity": data.get("main", {}).get("humidity", 0),
                    "wind_speed": round(data.get("wind", {}).get("speed", 0), 1),
                }
            elif response.status_code == 429:
                print("⚠️  OpenWeatherMap rate limit reached")
            else:
                print(f"⚠️  OpenWeatherMap error {response.status_code}")
                if response.status_code in (401, 403):
                    self._api_reachable = False

        except Exception as exc:
            print(f"⚠️  Async weather error: {exc}")

        return default

    async def get_bulk_weather_async(self, locations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fetch weather for multiple locations in parallel."""
        import httpx
        import asyncio
        
        async with httpx.AsyncClient() as client:
            tasks = [self.get_weather_async(loc["latitude"], loc["longitude"], client) for loc in locations]
            results = await asyncio.gather(*tasks)
            
            for i, res in enumerate(results):
                res["station_id"] = locations[i]["station_id"]
                res["lat"] = locations[i]["latitude"]
                res["lon"] = locations[i]["longitude"]
            return results


# Singleton instance — imported by vrp_solver
weather_service = OpenWeatherService()
