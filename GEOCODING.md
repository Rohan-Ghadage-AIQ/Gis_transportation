# Geocoding Feature - Address-Based Input

## Overview

The system now supports **address-based input** in addition to the legacy lat/lon format. Users can upload CSV files with addresses, and the system will automatically geocode them to coordinates using **Ola Krutrim API** with **Nominatim (OpenStreetMap)** as fallback.

---

## CSV Formats Supported

### 1. Address-Based (Recommended) ✨

```csv
id,address,parcel_weight,service_time,window_start,window_end
1,"Shop 23, MG Road, Andheri West, Mumbai, Maharashtra 400053",25,10,0,480
2,"Flat 5B, Linking Road, Bandra West, Mumbai, Maharashtra 400050",30,10,0,480
```

**Columns:**
- `id`: Unique identifier
- `address`: Full address (street, locality, city, state, PIN)
- `parcel_weight`: Weight in kg (optional, defaults to random 10-30kg)
- `service_time`: Service time in minutes (optional, defaults to 10)
- `window_start`: Time window start in minutes from 7 AM (optional)
- `window_end`: Time window end in minutes from 7 AM (optional)

### 2. Coordinate-Based (Legacy)

```csv
id,latitude,longitude,parcel_weight,service_time,window_start,window_end
1,19.189476,72.972706,25,10,0,480
2,19.054892,72.832825,30,10,0,480
```

**Columns:**
- `id`: Unique identifier
- `latitude`: Latitude coordinate
- `longitude`: Longitude coordinate
- Other columns same as above

---

## How It Works

### 1. Upload CSV with Addresses

When you upload a CSV with an `address` column, the system:

1. **Detects** the address column automatically
2. **Geocodes** each address using:
   - **Primary**: Ola Krutrim API (India-optimized)
   - **Fallback**: Nominatim/OpenStreetMap (free, rate-limited)
3. **Caches** results to avoid redundant API calls
4. **Validates** coordinates are within India
5. **Returns** geocoded data with lat/lon added

### 2. Geocoding Process

```
Address Input → Cache Check → Krutrim API → Nominatim Fallback → Coordinates
                     ↓              ↓              ↓
                  Hit (fast)    Success       Last resort
```

### 3. Caching

All geocoded addresses are cached in `backend/geocode_cache.json`:

```json
{
  "a1b2c3d4...": {
    "latitude": 19.189476,
    "longitude": 72.972706,
    "formatted_address": "Shop 23, MG Road, Andheri West, Mumbai, Maharashtra 400053",
    "confidence": 0.95,
    "source": "krutrim"
  }
}
```

**Benefits:**
- ✅ Instant results for repeated addresses
- ✅ Reduced API costs
- ✅ Works offline for cached addresses

---

## Setup

### 1. Get Ola Krutrim API Key (Optional)

1. Visit https://olakrutrim.com
2. Sign up for an account
3. Generate an API key
4. Add to `backend/.env`:

```bash
KRUTRIM_API_KEY=your_api_key_here
```

**Note:** If you don't have a Krutrim API key, the system will automatically use Nominatim (OpenStreetMap) as the only geocoding source.

### 2. Install Dependencies

```bash
cd backend
pip install requests
```

---

## Usage

### Upload Address-Based CSV

1. **Prepare CSV** with address column
2. **Upload** via frontend
3. **Wait** for geocoding (progress shown in console)
4. **Review** results - all addresses should have coordinates
5. **Compute** routes as normal

### Example Addresses (India)

Good address formats:
```
"Shop 23, MG Road, Andheri West, Mumbai, Maharashtra 400053"
"Flat 5B, Linking Road, Bandra, Mumbai, Maharashtra"
"Office 301, Hiranandani Gardens, Powai, Mumbai"
"Building 12, Senapati Bapat Marg, Dadar, Mumbai"
```

Tips for best results:
- ✅ Include street name, locality, city, state
- ✅ Add PIN code if available
- ✅ Use commas to separate address components
- ❌ Avoid vague addresses like "Near Railway Station"

---

## Error Handling

### Failed Geocoding

If some addresses fail to geocode, you'll see:

```json
{
  "error": "geocoding_failed",
  "message": "3 addresses could not be geocoded",
  "failed_addresses": [
    {"id": 5, "address": "Invalid address xyz"},
    {"id": 12, "address": "asdfghjkl"}
  ]
}
```

**Solutions:**
1. **Fix addresses** - correct typos, add more details
2. **Use coordinates** - manually find lat/lon for failed addresses
3. **Remove** - exclude problematic addresses from CSV

---

## Performance

### Geocoding Speed

| Addresses | Krutrim | Nominatim | Cached |
|-----------|---------|-----------|--------|
| 10 | ~5s | ~15s | <1s |
| 50 | ~20s | ~60s | <1s |
| 100 | ~40s | ~120s | <1s |

**Note:** Nominatim has 1 request/second rate limit

### Cost (Ola Krutrim)

- **Free tier**: 1,000 requests/month
- **Paid**: ~₹0.50 per request
- **Monthly (50 deliveries/day)**: ~₹375/month

Very affordable for most use cases!

---

## API Reference

### Geocoding Functions

**`geocode_address(address: str) -> Dict`**
```python
from geocoding import geocode_address

result = geocode_address("MG Road, Mumbai, Maharashtra")
# Returns:
# {
#     "latitude": 19.189476,
#     "longitude": 72.972706,
#     "formatted_address": "MG Road, Andheri West, Mumbai, Maharashtra",
#     "confidence": 0.95,
#     "source": "krutrim"
# }
```

**`batch_geocode(addresses: List[str]) -> List[Dict]`**
```python
from geocoding import batch_geocode

addresses = ["Address 1", "Address 2", "Address 3"]
results = batch_geocode(addresses)
# Returns list of geocoded results
```

### Cache Functions

**`get_cached_geocode(address: str) -> Dict`**
```python
from geocode_cache import get_cached_geocode

cached = get_cached_geocode("MG Road, Mumbai")
if cached:
    print(f"Found in cache: {cached['latitude']}, {cached['longitude']}")
```

**`clear_cache()`**
```python
from geocode_cache import clear_cache

clear_cache()  # Removes all cached geocodes
```

**`get_cache_stats() -> Dict`**
```python
from geocode_cache import get_cache_stats

stats = get_cache_stats()
# Returns:
# {
#     "total_entries": 150,
#     "cache_file_size_kb": 12.5,
#     "sources": {"krutrim": 120, "nominatim": 30}
# }
```

---

## Sample Files

Two sample CSV files are provided:

1. **`sample_data_address.csv`** - Address-based format (recommended)
2. **`sample_data_coordinates.csv`** - Legacy lat/lon format

Use these as templates for your own data!

---

## Troubleshooting

### Issue: "Geocoding failed for all addresses"

**Cause:** No API key and Nominatim is down/rate-limited

**Solution:**
1. Get Ola Krutrim API key
2. Add to `.env` file
3. Retry upload

### Issue: "Some addresses geocoded incorrectly"

**Cause:** Ambiguous or incomplete addresses

**Solution:**
1. Add more details (street, locality, PIN code)
2. Verify addresses on Google Maps first
3. Use lat/lon for problematic addresses

### Issue: "Geocoding is slow"

**Cause:** Using Nominatim fallback (1 req/sec limit)

**Solution:**
1. Get Krutrim API key for faster geocoding
2. Use cached addresses when possible
3. Reduce number of addresses per upload

---

## Future Enhancements

- [ ] Frontend progress bar for geocoding
- [ ] Manual correction UI for failed addresses
- [ ] Bulk geocoding optimization
- [ ] Google Maps API fallback option
- [ ] Address validation before geocoding

---

## Questions?

Refer to the main [README.md](../README.md) or [ARCHITECTURE.md](../ARCHITECTURE.md) for more information.
