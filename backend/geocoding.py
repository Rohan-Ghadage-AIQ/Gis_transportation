"""
Geocoding module for converting addresses to coordinates using Ola Krutrim API
"""

import os
import requests
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
import time

load_dotenv()

KRUTRIM_API_KEY = os.getenv("KRUTRIM_API_KEY", "")
KRUTRIM_API_URL = "https://api.olakrutrim.com/v1/geocode"

# Fallback to Nominatim (OpenStreetMap) if Krutrim fails
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


async def geocode_address_krutrim_async(address: str, client: 'httpx.AsyncClient') -> Optional[Dict]:
    """Async geocode using Ola Krutrim API."""
    if not KRUTRIM_API_KEY:
        return None
    
    try:
        response = await client.post(
            KRUTRIM_API_URL,
            headers={
                "Authorization": f"Bearer {KRUTRIM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"address": address, "region": "IN"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success" and data.get("results"):
                result = data["results"][0]
                return {
                    "latitude": float(result["latitude"]),
                    "longitude": float(result["longitude"]),
                    "formatted_address": result.get("formatted_address", address),
                    "confidence": float(result.get("confidence", 1.0)),
                    "source": "krutrim"
                }
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
    
    # Try Krutrim
    print(f"→ Geocoding with Krutrim: {address[:50]}...")
    result = geocode_address_krutrim(address)
    
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
            
    if not remaining_addresses:
        return [results_map[addr] for addr in addresses]
        
    # 2. Parallel Geocode remaining
    semaphore = asyncio.Semaphore(2) # Limit concurrency to avoid blocking/rate limits
    
    async def geocode_task(addr, client):
        async with semaphore:
            res = None
            if use_krutrim:
                # Try Krutrim
                res = await geocode_address_krutrim_async(addr, client)
            
            if not res:
                # Nominatim rate limit: 1/sec
                await asyncio.sleep(1)
                res = await geocode_address_nominatim_async(addr, client)
            
            if res:
                save_to_cache(addr, res)
                return addr, res
            return addr, {"latitude": None, "longitude": None, "formatted_address": addr, "confidence": 0.0, "source": "none", "error": "Failed"}

    async with httpx.AsyncClient() as client:
        tasks = [geocode_task(addr, client) for addr in remaining_addresses]
        done = await asyncio.gather(*tasks)
        for addr, res in done:
            results_map[addr] = res
            
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
