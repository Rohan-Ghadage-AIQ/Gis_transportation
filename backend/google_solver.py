import os
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

# Fleet Routing API Endpoint
GOOGLE_CLOUD_FLEET_ROUTING_URL = "https://routeoptimization.googleapis.com/v1/projects/{project_id}:optimizeTours"

# OAuth2 scope required for Route Optimization
ROUTE_OPTIMIZATION_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _get_access_token() -> Optional[str]:
    """
    Generate an OAuth2 access token from the Service Account JSON file.
    Uses google.oauth2.service_account to create credentials and refresh them.
    """
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
        
        sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not sa_file:
            print("❌ GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
            return None
        
        # Resolve path relative to backend directory
        sa_path = Path(__file__).parent / sa_file
        if not sa_path.exists():
            print(f"❌ Service Account JSON not found: {sa_path}")
            return None
        
        credentials = service_account.Credentials.from_service_account_file(
            str(sa_path),
            scopes=[ROUTE_OPTIMIZATION_SCOPE]
        )
        
        # Refresh to get a valid access token
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        
        print(f"✓ OAuth2 token generated for: {credentials.service_account_email}")
        return credentials.token
        
    except Exception as e:
        print(f"❌ Failed to generate OAuth2 token: {e}")
        return None


async def solve_google_vrp(
    stations: List[Dict[str, Any]],
    fleet: List[Dict[str, Any]],
    warehouse_lon: float,
    warehouse_lat: float
) -> Dict[str, Any]:
    """
    Solve VRP using Google Route Optimization (Fleet Routing) API.
    
    Uses Service Account OAuth2 for authentication.
    Maps internal data structures to Google's OptimizeToursRequest.
    """
    project_id = os.getenv("GOOGLE_PROJECT_ID", "")
    
    if not project_id:
        return {
            "success": False, 
            "error": "Google Project ID missing. Please add GOOGLE_PROJECT_ID to your .env file."
        }

    # 1. Get OAuth2 access token from Service Account
    access_token = _get_access_token()
    if not access_token:
        return {
            "success": False, 
            "error": "Failed to generate OAuth2 token. Check GOOGLE_SERVICE_ACCOUNT_JSON in .env."
        }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Reference time (start of day)
    model_start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    # Use 2-day window to accommodate overnight shifts (e.g., 10:00 to 09:54 next day)
    global_end_time = model_start_time + timedelta(days=2)
    
    # 2. Build Shipments (one per delivery station)
    shipments = []
    for station in stations:
        # Use delivery-only mode (no pickups) so that loadDemands = total weight on vehicle
        # This ensures total assigned weight never exceeds vehicle capacity
        shipment = {
            "deliveries": [{
                "arrivalLocation": {"latitude": station["latitude"], "longitude": station["longitude"]},
                "timeWindows": [{
                    "startTime": (model_start_time + timedelta(minutes=station["window_start"])).isoformat() + "Z",
                    "endTime": (model_start_time + timedelta(minutes=station["window_end"])).isoformat() + "Z"
                }],
                "duration": f"{station['service_time'] * 60}s"
            }],
            "loadDemands": {
                "weight": {"amount": str(station["parcel_weight"])}
            },
            "label": str(station["station_id"])
        }
        shipments.append(shipment)

    # 3. Build Vehicles (one per fleet vehicle)
    vehicles = []
    for i, v in enumerate(fleet):
        vehicle = {
            "startLocation": {"latitude": warehouse_lat, "longitude": warehouse_lon},
            "endLocation": {"latitude": warehouse_lat, "longitude": warehouse_lon},
            "loadLimits": {
                "weight": {"maxLoad": str(v["capacity_kg"])}
            },
            "costPerKilometer": float(v["cost_per_km"]),
            "fixedCost": 20.0,
            "label": f"Vehicle_{i+1}"
        }
        
        # Shift times
        start_min = v["shift_start"]
        end_min = v["shift_end"]
        if end_min < start_min: end_min += 1440
        
        # Clamp all time windows within the global window
        v_start = model_start_time + timedelta(minutes=start_min)
        v_start_end = model_start_time + timedelta(minutes=start_min + 30)
        v_end_start = model_start_time + timedelta(minutes=end_min)
        v_end_end = model_start_time + timedelta(minutes=end_min + 60)
        
        # Ensure nothing exceeds global end
        v_end_end = min(v_end_end, global_end_time)
        v_end_start = min(v_end_start, v_end_end)
        
        vehicle["startTimeWindows"] = [{
            "startTime": v_start.isoformat() + "Z",
            "endTime": v_start_end.isoformat() + "Z"
        }]
        vehicle["endTimeWindows"] = [{
            "startTime": v_end_start.isoformat() + "Z",
            "endTime": v_end_end.isoformat() + "Z"
        }]
        
        vehicles.append(vehicle)

    # 4. Build Request
    request_payload = {
        "model": {
            "shipments": shipments,
            "vehicles": vehicles,
            "globalStartTime": model_start_time.isoformat() + "Z",
            "globalEndTime": global_end_time.isoformat() + "Z",
        }
    }

    url = GOOGLE_CLOUD_FLEET_ROUTING_URL.format(project_id=project_id)
    
    # 5. Send Request
    async with httpx.AsyncClient() as client:
        try:
            print(f"→ Sending Request to Google Route Optimization (OAuth2)...")
            print(f"  URL: {url}")
            response = await client.post(url, json=request_payload, headers=headers, timeout=60)
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Google Route Optimization succeeded!")
                return parse_google_response(data, stations, fleet)
            else:
                error_text = response.text[:500]
                print(f"❌ Google API Error {response.status_code}: {error_text}")
                return {"success": False, "error": f"Google API Error ({response.status_code}): {error_text}"}
                
        except Exception as e:
            print(f"❌ Google Request Exception: {e}")
            return {"success": False, "error": str(e)}


def parse_google_response(data: Dict[str, Any], stations: List[Dict[str, Any]], fleet: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse Google's OptimizeToursResponse into our internal format.
    """
    routes = []
    google_routes = data.get("routes", [])
    
    # Debug: Log raw response structure
    print(f"  📊 Google returned {len(google_routes)} routes")
    
    # Check for skipped shipments
    skipped = data.get("skippedShipments", [])
    if skipped:
        print(f"  ⚠️ Google skipped {len(skipped)} shipments!")
        for s in skipped[:5]:
            print(f"    - {s.get('label', s.get('index', '?'))}: {s.get('reasons', [{}])[0].get('exampleExceededCapacityType', 'unknown')}")
    
    for i, g_route in enumerate(google_routes):
        vehicle_label = g_route.get("vehicleLabel", f"Vehicle_{i+1}")
        v_idx = int(vehicle_label.split("_")[-1]) - 1
        v_id = v_idx + 1
        
        visits = g_route.get("visits", [])
        transitions = g_route.get("transitions", [])
        metrics = g_route.get("metrics", {})
        
        print(f"  🚗 Vehicle_{v_id}: {len(visits)} visits, metrics={metrics}")
        
        stops = []
        for visit in visits:
            # Google has both pickup and delivery visits - we only want deliveries
            is_pickup = visit.get("isPickup", False)
            if is_pickup:
                continue
            
            shipment_label = visit.get("shipmentLabel", "")
            # If no label, try shipmentIndex
            if not shipment_label and "shipmentIndex" in visit:
                idx = visit["shipmentIndex"]
                if idx < len(stations):
                    shipment_label = str(stations[idx]["station_id"])
            
            arrival_time_str = visit.get("startTime", "")
            
            # Convert ISO string to HH:MM
            try:
                dt = datetime.fromisoformat(arrival_time_str.replace("Z", "+00:00"))
                arrival_clock = dt.strftime("%H:%M")
            except:
                arrival_clock = "00:00"
            
            stops.append({
                "station_id": shipment_label,
                "arrival_time": arrival_clock,
                "status": "ON TIME"
            })
        
        # Calculate distance from metrics
        travel_meters = 0
        if "travelDistanceMeters" in metrics:
            travel_meters = float(metrics["travelDistanceMeters"])
        
        routes.append({
            "vehicle_id": v_id,
            "stops": stops,
            "total_weight": 0,  # Will be computed from DB
            "distance_km": travel_meters / 1000.0,
            "cost": float(metrics.get("totalCost", "0") if metrics.get("totalCost") else "0"),
            "utilization": 0,
            "start_time": stops[0]["arrival_time"] if stops else "00:00",
            "end_time": stops[-1]["arrival_time"] if stops else "00:00"
        })
        
        print(f"    → {len(stops)} delivery stops, {travel_meters/1000:.1f} km")
    
    print(f"  ✅ Parsed {len(routes)} routes with {sum(len(r['stops']) for r in routes)} total deliveries")
        
    return {
        "success": True,
        "routes": routes,
    }
