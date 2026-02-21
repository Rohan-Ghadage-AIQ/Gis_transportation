"""
TomTom Traffic Service
Fetches real-time traffic data using the TomTom Flow Segment Data API v4.
Uses TOMTOM_API_KEY for authentication (simple query param).

API Docs: https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
Response includes: currentSpeed, freeFlowSpeed, currentTravelTime, freeFlowTravelTime
"""
import requests
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# TomTom Flow Segment Data API v4
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"


class TomTomTrafficService:
    """Fetches live traffic congestion factors using TomTom Flow Segment Data API"""

    def __init__(self):
        self.api_key = os.getenv("TOMTOM_API_KEY", "")
        # Fail-fast flag: set to False after first confirmed failure
        self._api_reachable: Optional[bool] = None

    def get_traffic_factor(self, lat: float, lon: float) -> float:
        """
        Get congestion factor for the road nearest to (lat, lon).

        Factor = freeFlowSpeed / currentSpeed
        e.g. 70 / 41 = 1.71x  (road is 71% slower than free flow)
             60 / 60 = 1.0    (free flow, no congestion)

        Returns 1.0 if API fails or key is missing.
        """
        if not self.api_key:
            return 1.0

        # Don't retry after a confirmed failure
        if self._api_reachable is False:
            return 1.0

        try:
            params = {
                "key": self.api_key,
                "point": f"{lat},{lon}",
                "unit": "KMPH",
            }

            response = requests.get(
                TOMTOM_FLOW_URL,
                params=params,
                timeout=8,
            )

            if response.status_code == 200:
                self._api_reachable = True
                data = response.json()
                flow = data.get("flowSegmentData", {})

                current_speed = flow.get("currentSpeed", 0)
                free_flow_speed = flow.get("freeFlowSpeed", 0)

                if current_speed > 0 and free_flow_speed > 0:
                    factor = free_flow_speed / current_speed
                    # Clamp: 0.8 min (slightly faster than usual) to 10x max
                    factor = round(min(max(factor, 0.8), 10.0), 3)
                    return factor

                return 1.0

            elif response.status_code in (401, 403):
                self._api_reachable = False
                print(
                    f"⚠️  TomTom API auth failed ({response.status_code}) — "
                    f"check TOMTOM_API_KEY in .env"
                )
            elif response.status_code == 404:
                # No road segment found near this point — skip silently
                return 1.0
            else:
                self._api_reachable = False
                print(
                    f"⚠️  TomTom API error {response.status_code}: "
                    f"{response.text[:120]}"
                )

        except requests.exceptions.Timeout:
            print("⚠️  TomTom API timeout — using static costs")
        except Exception as exc:
            print(f"⚠️  TomTom traffic error: {exc}")

        return 1.0  # Safe default: no penalty

    def get_station_traffic_factor(self, station_lat: float, station_lon: float,
                                   **kwargs) -> float:
        """
        Get congestion factor for the road nearest to a delivery station.
        TomTom Flow Segment Data works per-point (no origin/destination needed),
        so we just query the station's coordinates directly.
        """
        return self.get_traffic_factor(station_lat, station_lon)


# Singleton instance — imported by vrp_solver
traffic_service = TomTomTrafficService()
