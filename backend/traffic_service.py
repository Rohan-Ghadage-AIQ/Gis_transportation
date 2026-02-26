"""
Traffic Service — Multi-source traffic factor provider.
Supports Google (Routes API via OAuth2) and TomTom (Flow Segment API).

Google uses the same Service Account as Route Optimization (OAuth2 Bearer token).
TomTom uses API key authentication.
"""
import os
import httpx
import asyncio
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# TomTom Flow Segment Data API v4
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"


class TomTomTrafficService:
    """Fetches live traffic congestion factors using TomTom Flow Segment Data API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._api_reachable: Optional[bool] = None

    async def get_traffic_factor_async(self, lat: float, lon: float, client: httpx.AsyncClient) -> float:
        """Async version of get_traffic_factor using httpx."""
        if not self.api_key or self._api_reachable is False:
            return 1.0

        try:
            params = {
                "key": self.api_key,
                "point": f"{lat},{lon}",
                "unit": "KMPH",
            }

            response = await client.get(TOMTOM_FLOW_URL, params=params, timeout=8)

            if response.status_code == 200:
                self._api_reachable = True
                data = response.json()
                flow = data.get("flowSegmentData", {})

                current_speed = flow.get("currentSpeed", 0)
                free_flow_speed = flow.get("freeFlowSpeed", 0)

                if current_speed > 0 and free_flow_speed > 0:
                    factor = free_flow_speed / current_speed
                    factor = round(min(max(factor, 0.8), 10.0), 3)
                    return factor

                return 1.0

            elif response.status_code == 404:
                return 1.0
            else:
                print(f"⚠️  TomTom API error {response.status_code}")
                if response.status_code in (401, 403):
                    self._api_reachable = False

        except Exception as exc:
            print(f"⚠️  Async TomTom traffic error: {exc}")

        return 1.0


class GoogleTrafficService:
    """
    Fetches live traffic congestion factors using Google Routes API (Compute Routes).
    Uses OAuth2 Service Account authentication (same as Route Optimization).
    """

    ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(self):
        self._api_reachable: Optional[bool] = None
        self._error_logged = False
        self._cached_token: Optional[str] = None

    def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token from Service Account (reuses google_solver logic)."""
        if self._cached_token:
            return self._cached_token
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests

            sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
            if not sa_file:
                return None

            sa_path = Path(__file__).parent / sa_file
            if not sa_path.exists():
                return None

            credentials = service_account.Credentials.from_service_account_file(
                str(sa_path),
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
            self._cached_token = credentials.token
            return self._cached_token

        except Exception as e:
            if not self._error_logged:
                print(f"⚠️  Google traffic OAuth2 error: {e}")
                self._error_logged = True
            return None

    async def get_traffic_factor_async(self, lat: float, lon: float, client: httpx.AsyncClient) -> float:
        """
        Estimate congestion factor using Google Routes API (Compute Routes).
        
        Strategy: Compare duration (with live traffic) vs staticDuration (no traffic).
        Factor = duration / staticDuration
        """
        if self._api_reachable is False:
            return 1.0

        token = self._get_access_token()
        if not token:
            return 1.0

        try:
            # Create a short trip (~500m north) to measure local congestion
            dest_lat = lat + 0.005
            dest_lon = lon

            body = {
                "origin": {
                    "location": {
                        "latLng": {"latitude": lat, "longitude": lon}
                    }
                },
                "destination": {
                    "location": {
                        "latLng": {"latitude": dest_lat, "longitude": dest_lon}
                    }
                },
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE"
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-Goog-FieldMask": "routes.duration,routes.staticDuration"
            }

            response = await client.post(self.ROUTES_URL, json=body, headers=headers, timeout=8)

            if response.status_code == 200:
                self._api_reachable = True
                data = response.json()
                
                routes = data.get("routes", [])
                if routes:
                    route = routes[0]
                    duration_str = route.get("duration", "0s").rstrip("s")
                    static_str = route.get("staticDuration", "0s").rstrip("s")
                    
                    duration = float(duration_str) if duration_str else 0
                    static = float(static_str) if static_str else 0
                    
                    if static > 0:
                        factor = duration / static
                        factor = round(min(max(factor, 0.8), 10.0), 3)
                        return factor
                
                return 1.0

            elif response.status_code in (401, 403):
                self._api_reachable = False
                if not self._error_logged:
                    error_msg = response.json().get("error", {}).get("message", response.text[:200])
                    print(f"⚠️  Google Routes API denied: {error_msg}")
                    self._error_logged = True
            else:
                if not self._error_logged:
                    print(f"⚠️  Google Routes API error {response.status_code}: {response.text[:200]}")
                    self._error_logged = True

        except Exception as exc:
            if not self._error_logged:
                print(f"⚠️  Async Google traffic error: {exc}")
                self._error_logged = True

        return 1.0


class MultiSourceTrafficService:
    """Delegates traffic requests to the configured source (Google or TomTom)"""

    def __init__(self):
        self.source = os.getenv("TRAFFIC_SOURCE", "tomtom").lower()
        self.tomtom_key = os.getenv("TOMTOM_API_KEY", "")
        
        self.tomtom_service = TomTomTrafficService(self.tomtom_key)
        self.google_service = GoogleTrafficService()  # Uses OAuth2, not API key

    async def get_traffic_factor_async(self, lat: float, lon: float, client: Optional[httpx.AsyncClient] = None) -> float:
        """Async version: routes to the correct service provider."""
        service = self.google_service if self.source == "google" else self.tomtom_service
        
        if client:
            return await service.get_traffic_factor_async(lat, lon, client)
        else:
            async with httpx.AsyncClient() as c:
                return await service.get_traffic_factor_async(lat, lon, c)

    async def get_station_traffic_factor_async(self, lat: float, lon: float, client: Optional[httpx.AsyncClient] = None) -> float:
        """Alias for compatibility with vrp_solver.py"""
        return await self.get_traffic_factor_async(lat, lon, client)

    def get_traffic_factor(self, lat: float, lon: float) -> float:
        """Synchronous wrapper for async call (using asyncio.run internally)"""
        try:
            return asyncio.run(self.get_traffic_factor_async(lat, lon))
        except Exception:
            return 1.0

    def get_station_traffic_factor(self, lat: float, lon: float, **kwargs) -> float:
        """Alias for compatibility with vrp_solver.py"""
        return self.get_traffic_factor(lat, lon)


# Singleton instance — imported by vrp_solver
traffic_service = MultiSourceTrafficService()
