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


def geocode_address_krutrim(address: str) -> Optional[Dict]:
    """
    Geocode a single address using Ola Krutrim API
    
    Args:
        address: Full address string
        
    Returns:
        {
            "latitude": float,
            "longitude": float,
            "formatted_address": str,
            "confidence": float,
            "source": "krutrim"
        }
        or None if geocoding fails
    """
    if not KRUTRIM_API_KEY:
        print("Warning: KRUTRIM_API_KEY not set, skipping Krutrim geocoding")
        return None
    
    try:
        response = requests.post(
            KRUTRIM_API_URL,
            headers={
                "Authorization": f"Bearer {KRUTRIM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "address": address,
                "region": "IN"
            },
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
        else:
            print(f"Krutrim API error {response.status_code}: {response.text}")
        
        return None
        
    except Exception as e:
        print(f"Krutrim geocoding error for '{address}': {e}")
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


def geocode_address_nominatim(address: str) -> Optional[Dict]:
    """
    Geocode using Nominatim (OpenStreetMap) as fallback
    
    Args:
        address: Full address string
        
    Returns:
        Geocoded result or None
    """
    try:
        # Simplify address for better Nominatim results
        simplified_address = simplify_address_for_nominatim(address)
        
        # Add "India" to improve accuracy
        search_query = f"{simplified_address}, India"
        
        print(f"  → Nominatim query: {search_query[:80]}...")
        
        response = requests.get(
            NOMINATIM_URL,
            params={
                "q": search_query,
                "format": "json",
                "limit": 1,
                "countrycodes": "in"
            },
            headers={
                "User-Agent": "VehicleRoutingSystem/1.0"
            },
            timeout=10
        )
        
        print(f"  → Nominatim status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"  → Nominatim results: {len(data) if data else 0} found")
            
            if data and len(data) > 0:
                result = data[0]
                geocoded = {
                    "latitude": float(result["lat"]),
                    "longitude": float(result["lon"]),
                    "formatted_address": result.get("display_name", address),
                    "confidence": float(result.get("importance", 0.5)),
                    "source": "nominatim"
                }
                print(f"  → Success: {geocoded['latitude']:.6f}, {geocoded['longitude']:.6f}")
                return geocoded
            else:
                print(f"  → No results returned from Nominatim")
        else:
            print(f"  → Nominatim HTTP error: {response.status_code}")
        
        return None
        
    except Exception as e:
        print(f"Nominatim geocoding error for '{address}': {e}")
        import traceback
        traceback.print_exc()
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


def batch_geocode(addresses: List[str], progress_callback=None) -> List[Dict]:
    """
    Geocode multiple addresses with progress tracking
    
    Args:
        addresses: List of address strings
        progress_callback: Optional callback function(current, total, address)
        
    Returns:
        List of results with structure:
        [
            {
                "address": str,
                "latitude": float or None,
                "longitude": float or None,
                "formatted_address": str,
                "confidence": float,
                "source": str,
                "error": str (if failed)
            }
        ]
    """
    results = []
    total = len(addresses)
    
    for i, address in enumerate(addresses):
        current = i + 1
        
        # Progress callback
        if progress_callback:
            progress_callback(current, total, address)
        
        print(f"\n[{current}/{total}] Processing: {address[:60]}...")
        
        result = geocode_address(address)
        
        if result:
            results.append({
                "address": address,
                "latitude": result["latitude"],
                "longitude": result["longitude"],
                "formatted_address": result["formatted_address"],
                "confidence": result["confidence"],
                "source": result["source"]
            })
            print(f"✓ Success: ({result['latitude']:.6f}, {result['longitude']:.6f}) via {result['source']}")
        else:
            # Geocoding failed
            results.append({
                "address": address,
                "latitude": None,
                "longitude": None,
                "formatted_address": address,
                "confidence": 0.0,
                "source": "none",
                "error": "Geocoding failed"
            })
            print(f"✗ Failed to geocode")
    
    return results


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
