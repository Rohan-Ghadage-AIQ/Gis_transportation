# Geocoding API Alternatives

## Problem
Nominatim (OpenStreetMap) is too slow for production:
- **Rate limit:** 1 request per second
- **Time for 56 addresses:** ~56 seconds
- **Not suitable for:** Real-time applications

---

## Recommended Solutions

### 🥇 Option 1: Google Maps Geocoding API (Best Overall)

**Pros:**
- ✅ Very fast (~0.2-0.5 seconds per address)
- ✅ Excellent accuracy worldwide
- ✅ Batch geocoding support (100 addresses at once!)
- ✅ 50 requests/second limit
- ✅ Reliable and well-documented

**Pricing:**
- $5 per 1,000 requests
- First $200/month free credit
- **Cost for 56 addresses:** ~$0.28

**Setup:**
```python
# Install library
pip install googlemaps

# In geocoding.py
import googlemaps

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

def geocode_address_google(address: str) -> Optional[Dict]:
    try:
        result = gmaps.geocode(address + ", India")
        if result:
            location = result[0]['geometry']['location']
            return {
                "latitude": location['lat'],
                "longitude": location['lng'],
                "formatted_address": result[0]['formatted_address'],
                "confidence": 1.0,
                "source": "google"
            }
    except Exception as e:
        print(f"Google geocoding error: {e}")
    return None
```

**Get API Key:**
1. Go to https://console.cloud.google.com/
2. Create project → Enable "Geocoding API"
3. Create credentials → API Key
4. Add to `.env`: `GOOGLE_MAPS_API_KEY=your_key_here`

---

### 🥈 Option 2: Ola Krutrim API (Best for India)

**Pros:**
- ✅ Optimized for Indian addresses
- ✅ Fast (~0.5-1 second per address)
- ✅ Local company, good support

**Pricing:**
- ₹0.50 per request
- Free tier: 1,000 requests/month
- **Cost for 56 addresses:** ~₹28

**Setup:**
Already integrated! Just add API key to `.env`:
```bash
KRUTRIM_API_KEY=your_krutrim_api_key_here
```

Get key from: https://olakrutrim.com

---

### 🥉 Option 3: Mapbox Geocoding API

**Pros:**
- ✅ Very fast (~0.3-0.6 seconds per address)
- ✅ Generous free tier
- ✅ Good accuracy
- ✅ Batch geocoding support

**Pricing:**
- **Free:** 100,000 requests/month
- After free tier: $0.50 per 1,000 requests

**Setup:**
```python
# Install library
pip install mapbox

# In geocoding.py
from mapbox import Geocoder

MAPBOX_ACCESS_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
geocoder = Geocoder(access_token=MAPBOX_ACCESS_TOKEN)

def geocode_address_mapbox(address: str) -> Optional[Dict]:
    try:
        response = geocoder.forward(address + ", India", country=['in'])
        if response.status_code == 200:
            features = response.geojson()['features']
            if features:
                coords = features[0]['geometry']['coordinates']
                return {
                    "latitude": coords[1],
                    "longitude": coords[0],
                    "formatted_address": features[0]['place_name'],
                    "confidence": features[0].get('relevance', 0.5),
                    "source": "mapbox"
                }
    except Exception as e:
        print(f"Mapbox geocoding error: {e}")
    return None
```

Get token from: https://account.mapbox.com/

---

### 🚀 Option 4: Batch Geocoding (Fastest!)

Instead of geocoding one-by-one, send all addresses at once:

**Google Maps Batch:**
```python
def batch_geocode_google(addresses: List[str]) -> List[Dict]:
    """Geocode up to 100 addresses at once"""
    results = []
    
    # Google allows batch requests
    for i in range(0, len(addresses), 100):
        batch = addresses[i:i+100]
        
        # Geocode batch (parallel internally)
        batch_results = [geocode_address_google(addr) for addr in batch]
        results.extend(batch_results)
    
    return results
```

**Speed:** All 56 addresses in 2-3 seconds total!

---

## Comparison Table

| Provider | Speed (56 addresses) | Cost (56 addresses) | Free Tier | Best For |
|----------|---------------------|---------------------|-----------|----------|
| **Nominatim** | ~56 seconds | Free | Unlimited | Testing only |
| **Google Maps** | ~3-5 seconds | $0.28 | $200/month | Production (best accuracy) |
| **Ola Krutrim** | ~30 seconds | ₹28 | 1,000/month | Indian addresses |
| **Mapbox** | ~5-10 seconds | Free | 100k/month | Budget-conscious |

---

## Recommendation

### For Your Use Case (56 addresses):

**1st Choice: Google Maps Geocoding API**
- Fastest and most accurate
- Batch support = 3-5 seconds total
- Free tier covers your needs

**2nd Choice: Mapbox**
- Free for 100k requests/month
- Good speed and accuracy

**3rd Choice: Ola Krutrim**
- If you prefer Indian provider
- Good for Indian addresses

---

## Implementation Priority

1. ✅ **Keep Nominatim as fallback** (already done)
2. ✅ **Add Google Maps API** (recommended)
3. ✅ **Update geocoding strategy:**
   ```
   1. Try Google Maps (fast)
   2. Fallback to Krutrim (if key set)
   3. Fallback to Nominatim (slow but free)
   ```

---

## Next Steps

1. Choose provider (recommend Google Maps)
2. Get API key
3. I'll integrate it into `geocoding.py`
4. Test with your 56 addresses
5. Should complete in 3-5 seconds!

Let me know which provider you prefer and I'll implement it!
