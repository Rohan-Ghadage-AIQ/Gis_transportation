"""
Geocoding module for converting addresses to coordinates using Ola Maps API
"""

import os
import requests
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
import time

load_dotenv()

KRUTRIM_API_KEY = os.getenv("KRUTRIM_API_KEY", "")
# Ola Maps rebranded from olakrutrim.com → olamaps.io
OLA_MAPS_GEOCODE_URL = "https://api.olamaps.io/places/v1/geocode"

# Fallback to Nominatim (OpenStreetMap) if Ola Maps fails
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


async def geocode_address_krutrim_async(address: str, client: 'httpx.AsyncClient') -> Optional[Dict]:
    """Async geocode using Ola Maps API (formerly Krutrim)."""
    if not KRUTRIM_API_KEY:
        return None
    
    try:
        response = await client.get(
            OLA_MAPS_GEOCODE_URL,
            params={
                "address": address,
                "language": "en",
                "api_key": KRUTRIM_API_KEY
            },
            headers={
                "X-Request-Id": "vrp-geocode",
                "Origin": "http://localhost:5173",
                "Referer": "http://localhost:5173/"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("geocodingResults", [])
            if results:
                result = results[0]
                geo = result.get("geometry", {}).get("location", {})
                lat = geo.get("lat")
                lng = geo.get("lng")
                if lat and lng:
                    return {
                        "latitude": float(lat),
                        "longitude": float(lng),
                        "formatted_address": result.get("formatted_address", address),
                        "confidence": 1.0,
                        "source": "krutrim"
                    }
        elif response.status_code in (401, 403):
            print(f"⚠️  Ola Maps API auth failed ({response.status_code})")
    except Exception as e:
        print(f"Krutrim async error: {e}")
    return None


def simplify_address_for_nominatim(address: str) -> str:
    """
    Simplify address for better Nominatim results
    
    Removes:
    - Building/shop/flat numbers (Shop 23, Flat 5B, etc.)
    - Office numbers
    
    Keeps:
    - Street names
    - Locality/area names
    - City, state, PIN
    
    Example:
    "Shop 23, MG Road, Andheri West, Mumbai, Maharashtra 400053"
    → "MG Road, Andheri West, Mumbai, Maharashtra 400053"
    """
    import re
    
    # Remove patterns like "Shop 23,", "Flat 5B,", "Office 301,", "Building 12,"
    patterns = [
        r'^Shop\s+\d+[A-Z]?,\s*',
        r'^Flat\s+\d+[A-Z]?,\s*',
        r'^Office\s+\d+[A-Z]?,\s*',
        r'^Building\s+[A-Z0-9]+,\s*',
        r'^Office\s+Tower,\s*',
        r'^Building\s+[A-Z],\s*',
    ]
    
    simplified = address
    for pattern in patterns:
        simplified = re.sub(pattern, '', simplified, flags=re.IGNORECASE)
    
    return simplified.strip()


async def geocode_address_nominatim_async(address: str, client: 'httpx.AsyncClient') -> Optional[Dict]:
    """Async geocode using Nominatim."""
    try:
        simplified_address = simplify_address_for_nominatim(address)
        search_query = f"{simplified_address}, India"
        
        response = await client.get(
            NOMINATIM_URL,
            params={
                "q": search_query,
                "format": "json",
                "limit": 1,
                "countrycodes": "in"
            },
            headers={"User-Agent": "VehicleRoutingSystem/1.0"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                result = data[0]
                return {
                    "latitude": float(result["lat"]),
                    "longitude": float(result["lon"]),
                    "formatted_address": result.get("display_name", address),
                    "confidence": float(result.get("importance", 0.5)),
                    "source": "nominatim"
                }
    except Exception as e:
        print(f"Nominatim async error: {e}")
    return None


def geocode_address(address: str, use_cache: bool = True) -> Optional[Dict]:
    """
    Geocode a single address with fallback strategy
    
    Strategy:
    1. Check cache (if enabled)
    2. Try Ola Krutrim
    3. Fallback to Nominatim
    
    Args:
        address: Full address string
        use_cache: Whether to use cache
        
    Returns:
        Geocoded result or None
    """
    if not address or not address.strip():
        return None
    
    address = address.strip()
    
    # Try cache first
    if use_cache:
        from geocode_cache import get_cached_geocode
        cached = get_cached_geocode(address)
        if cached:
            print(f"✓ Cache hit: {address[:50]}...")
            return cached
    
    result = None
    # Try Ola Maps (Krutrim)
    if KRUTRIM_API_KEY:
        print(f"→ Geocoding with Ola Maps: {address[:50]}...")
        try:
            resp = requests.get(
                OLA_MAPS_GEOCODE_URL,
                params={"address": address, "language": "en", "api_key": KRUTRIM_API_KEY},
                headers={"Origin": "http://localhost:5173", "Referer": "http://localhost:5173/"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                geo_results = data.get("geocodingResults", [])
                if geo_results:
                    geo = geo_results[0].get("geometry", {}).get("location", {})
                    if geo.get("lat") and geo.get("lng"):
                        result = {
                            "latitude": float(geo["lat"]),
                            "longitude": float(geo["lng"]),
                            "formatted_address": geo_results[0].get("formatted_address", address),
                            "confidence": 1.0,
                            "source": "krutrim"
                        }
        except Exception as e:
            print(f"Ola Maps sync error: {e}")
    
    # Fallback to Nominatim
    if not result:
        print(f"→ Fallback to Nominatim: {address[:50]}...")
        result = geocode_address_nominatim(address)
        # Rate limit for Nominatim (1 request per second)
        time.sleep(1)
    
    # Save to cache
    if result and use_cache:
        from geocode_cache import save_to_cache
        save_to_cache(address, result)
    
    return result


async def batch_geocode(addresses: List[str]) -> List[Dict]:
    """Geocode multiple addresses in parallel with rate limiting."""
    import asyncio
    import httpx
    from geocode_cache import get_cached_geocode, save_to_cache
    
    use_krutrim = os.getenv("USE_KRUTRIM_GEOCODING", "true").lower() in ("true", "1", "yes")
    results_map = {}
    remaining_addresses = []
    
    # 1. Check cache first
    for addr in addresses:
        cached = get_cached_geocode(addr)
        if cached:
            results_map[addr] = cached
        else:
            remaining_addresses.append(addr)
    
    cached_count = len(addresses) - len(remaining_addresses)
    if cached_count > 0:
        print(f"✓ {cached_count} addresses found in cache")
            
    if not remaining_addresses:
        print("✓ All addresses found in cache!")
        return [results_map[addr] for addr in addresses]
    
    print(f"→ Geocoding {len(remaining_addresses)} addresses...")
    
    # 2. Track if Krutrim is reachable (skip after first DNS failure)
    krutrim_reachable = use_krutrim
    
    # Nominatim must be serialized (1 request per second rate limit)
    nominatim_lock = asyncio.Lock()
    
    async def geocode_single(addr: str, client: httpx.AsyncClient) -> tuple:
        nonlocal krutrim_reachable
        res = None
        
        # Try Krutrim (skip if already known to be down)
        if krutrim_reachable:
            res = await geocode_address_krutrim_async(addr, client)
            if res is None and not krutrim_reachable:
                pass  # Already flagged by another task
        
        # Fallback to Nominatim (serialized with lock)
        if not res:
            async with nominatim_lock:
                await asyncio.sleep(1.1)  # Nominatim rate limit: 1 req/sec
                res = await geocode_address_nominatim_async(addr, client)
        
        if res:
            save_to_cache(addr, res)
            return addr, res
        return addr, {"latitude": None, "longitude": None, "formatted_address": addr, "confidence": 0.0, "source": "none", "error": "Failed"}

    # 3. First, test if Krutrim is reachable with a single request
    async with httpx.AsyncClient() as client:
        if use_krutrim and remaining_addresses:
            test_result = await geocode_address_krutrim_async(remaining_addresses[0], client)
            if test_result:
                results_map[remaining_addresses[0]] = test_result
                save_to_cache(remaining_addresses[0], test_result)
                remaining_addresses = remaining_addresses[1:]
                krutrim_reachable = True
                print("✓ Krutrim API is reachable — using fast parallel geocoding")
            else:
                krutrim_reachable = False
                print("⚠️  Krutrim API unreachable — falling back to Nominatim (slower, ~1 addr/sec)")
        
        # 4. Process remaining addresses
        if remaining_addresses:
            if krutrim_reachable:
                # Krutrim works — geocode in parallel batches of 5
                sem = asyncio.Semaphore(5)
                async def krutrim_task(addr):
                    async with sem:
                        return await geocode_single(addr, client)
                tasks = [krutrim_task(addr) for addr in remaining_addresses]
                done = await asyncio.gather(*tasks)
            else:
                # Krutrim is down — run Nominatim sequentially (it handles its own lock)
                done = []
                for i, addr in enumerate(remaining_addresses):
                    result = await geocode_single(addr, client)
                    done.append(result)
                    if (i + 1) % 10 == 0:
                        print(f"  Geocoded {i + 1}/{len(remaining_addresses)}...")
            
            for addr, res in done:
                results_map[addr] = res
    
    success = sum(1 for r in results_map.values() if r.get("latitude") is not None)
    print(f"\n✓ Successfully geocoded {success}/{len(addresses)} addresses!")
            
    return [results_map[addr] for addr in addresses]



def validate_coordinates(lat: float, lon: float) -> bool:
    """
    Validate if coordinates are within India's approximate bounds
    
    India bounds (approximate):
    - Latitude: 6.5° to 35.5° N
    - Longitude: 68° to 97.5° E
    """
    return (6.5 <= lat <= 35.5) and (68.0 <= lon <= 97.5)


def extract_city_from_address(address: str) -> Optional[str]:
    """
    Extract city name from address string
    
    Common patterns:
    - "Street, Locality, City, State"
    - "Building, City, State PIN"
    """
    # Common Indian cities
    cities = [
        "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
        "Kolkata", "Pune", "Ahmedabad", "Surat", "Jaipur",
        "Lucknow", "Kanpur", "Nagpur", "Indore", "Thane",
        "Bhopal", "Visakhapatnam", "Pimpri", "Patna", "Vadodara"
    ]
    
    address_upper = address.upper()
    for city in cities:
        if city.upper() in address_upper:
            return city
    
    return None
