"""
Cache for geocoded addresses to avoid redundant API calls
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional

CACHE_FILE = Path(__file__).parent / "geocode_cache.json"


def get_address_hash(address: str) -> str:
    """
    Generate a unique hash for an address
    
    Args:
        address: Address string
        
    Returns:
        MD5 hash of normalized address
    """
    normalized = address.lower().strip()
    return hashlib.md5(normalized.encode()).hexdigest()


def load_cache() -> Dict:
    """
    Load geocode cache from file
    
    Returns:
        Dictionary of cached geocodes
    """
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading cache: {e}")
            return {}
    return {}


def save_cache(cache: Dict):
    """
    Save geocode cache to file
    
    Args:
        cache: Dictionary of geocoded addresses
    """
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving cache: {e}")


def get_cached_geocode(address: str) -> Optional[Dict]:
    """
    Get geocoded result from cache
    
    Args:
        address: Address string
        
    Returns:
        Cached geocode result or None
    """
    cache = load_cache()
    addr_hash = get_address_hash(address)
    
    if addr_hash in cache:
        return cache[addr_hash]
    
    return None


def save_to_cache(address: str, result: Dict):
    """
    Save geocoded result to cache
    
    Args:
        address: Original address string
        result: Geocoded result dictionary
    """
    cache = load_cache()
    addr_hash = get_address_hash(address)
    
    cache[addr_hash] = result
    save_cache(cache)


def clear_cache():
    """
    Clear all cached geocodes
    """
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    print("Geocode cache cleared")


def get_cache_stats() -> Dict:
    """
    Get statistics about the cache
    
    Returns:
        {
            "total_entries": int,
            "cache_file_size_kb": float,
            "sources": {"krutrim": int, "nominatim": int}
        }
    """
    cache = load_cache()
    
    sources = {}
    for entry in cache.values():
        source = entry.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1
    
    size_kb = 0
    if CACHE_FILE.exists():
        size_kb = CACHE_FILE.stat().st_size / 1024
    
    return {
        "total_entries": len(cache),
        "cache_file_size_kb": round(size_kb, 2),
        "sources": sources
    }
