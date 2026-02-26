import asyncio
import os
from dotenv import load_dotenv
from google_solver import solve_google_vrp

load_dotenv()

async def test_google():
    print("🧪 Testing Google Route Optimization Integration...")
    
    # Dummy station data (Maharashtra region)
    stations = [
        {
            "station_id": "ST_001",
            "latitude": 19.2183,
            "longitude": 72.9781,
            "parcel_weight": 20,
            "service_time": 15,
            "window_start": 480,
            "window_end": 1080
        },
        {
            "station_id": "ST_002",
            "latitude": 18.5204,
            "longitude": 73.8567,
            "parcel_weight": 30,
            "service_time": 20,
            "window_start": 480,
            "window_end": 1080
        }
    ]
    
    # Dummy fleet
    fleet = [
        {
            "capacity_kg": 200,
            "cost_per_km": 15,
            "shift_start": 480,
            "shift_end": 1200
        }
    ]
    
    # Mumbai Warehouse
    warehouse_lon = 72.8777
    warehouse_lat = 19.0760
    
    # This will likely fail with 404 or 403 because of the PROJECT_ID placeholder
    # but it verifies the payload construction and request logic.
    result = await solve_google_vrp(stations, fleet, warehouse_lon, warehouse_lat)
    
    print(f"\nResult Success: {result.get('success')}")
    if not result.get('success'):
        print(f"Error: {result.get('error')}")
    else:
        print(f"Routes generated: {len(result.get('routes', []))}")

if __name__ == "__main__":
    asyncio.run(test_google())
