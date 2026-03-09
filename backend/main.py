from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import pandas as pd
import io
import os
from dotenv import load_dotenv
import json
import time
from datetime import datetime

# Import database and solver modules
from database import (
    get_db_connection,
    setup_station_node_map_table,
    insert_stations_from_dataframe,
    randomize_station_attributes,
    calculate_distance_matrix,
    fetch_route_geometries_geojson,
    fetch_results_summary,
    get_fleet_vehicles,
    upsert_fleet_vehicle,
    delete_fleet_vehicle
)
from vrp_solver import solve_vrp
from geocoding import batch_geocode
from weather_service import weather_service
from chatbot_service import chat as chatbot_chat, build_data_context
from maintenance_routes import router as maintenance_router

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup"""
    try:
        print("\n🚀 BACKEND STARTING - VERSION 4 (ROBUST PARSING)")
        conn = get_db_connection()
        cur = conn.cursor()
        # Only create the unassigned_parcels table if it doesn't exist
        # NOTE: station_node_map is dropped/recreated during each computation,
        # so we do NOT call setup_station_node_map_table() here (it runs
        # DROP TABLE CASCADE which blocks on active connections).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vector.unassigned_parcels (
                station_id VARCHAR PRIMARY KEY,
                reason VARCHAR NOT NULL,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                parcel_weight INTEGER,
                window_end TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✓ Database tables initialized")
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize tables: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# CORS configuration
origins = [
    os.getenv("FRONTEND_URL", "http://localhost"), # The Docker port
    "http://localhost:80",
    "http://localhost:5173",                       # Default Vite dev port
    "*",                                           # Optional: Keep this only if you want total access
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount maintenance module routes
app.include_router(maintenance_router)

# Database connection
conn = get_db_connection()

# Global variables
uploaded_data = None
warehouse_config = {
    "latitude": 19.05507294355211,
    "longitude": 72.87538873375874
}

# Transient VRP metadata (weather alerts, rerouted vehicles)
# Stored globally because it is not persisted in the DB
LAST_VRP_METADATA = {
    "weather_alerts": [],
    "weather_rerouted": False,
    "rerouted_vehicles": []
}

# Auto re-optimization state
AUTO_REOPTIMIZE = {
    "enabled": False,
    "interval_seconds": 600,  # 10 minutes
    "task": None,              # asyncio.Task reference
    "last_run": None,
    "last_rerouted": [],
}

# Shift logic for time windows
SHIFTS = [(420, 600), (600, 1080), (1080, 1260)]  # 07:00-10:00, 10:00-18:00, 18:00-21:00

def parse_window_end(val):
    """Parse HH:MM:SS string to minutes from midnight"""
    try:
        if val is None or pd.isna(val):
            return 600
        val_str = str(val).strip()
        if ':' in val_str:
            parts = val_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            return hours * 60 + minutes
        
        # If it's a digit string, parse as int
        if val_str.isdigit():
            return int(val_str)
            
        # If it's a float string ending in .0, parse as float then int
        try:
            return int(float(val_str))
        except:
            pass
            
        return 600  # Default: 10:00
    except Exception as e:
        # print(f"Error parsing window_end {val}: {e}")
        return 600  # Default: 10:00

def get_shift_start(window_end_minutes):
    """Auto-assign window_start to the start of the matching shift"""
    for shift_start, shift_end in SHIFTS:
        if window_end_minutes <= shift_end:
            return shift_start
    return SHIFTS[-1][0]  # Fallback: last shift

# Vehicle colors for visualization
VEHICLE_COLORS = [
    "#FF6B6B",  # Red
    "#4ECDC4",  # Teal
    "#45B7D1",  # Blue
    "#FFA07A",  # Light Salmon
    "#98D8C8",  # Mint
    "#F7DC6F",  # Yellow
    "#BB8FCE",  # Purple
    "#85C1E9",  # Sky Blue
    "#F8B88B",  # Peach
    "#ABEBC6"   # Light Green
]


# Pydantic models
class DataUpdate(BaseModel):
    data: List[Dict[str, Any]]


class WarehouseConfig(BaseModel):
    latitude: float
    longitude: float



class ComputeResponse(BaseModel):
    status: str
    message: str


@app.get("/")
async def root():
    return {"message": "Vehicle Routing API is running"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload CSV file with delivery locations.
    Supports both address-based and coordinate-based formats.
    """
    global uploaded_data
    
    try:
        # Read file — support both CSV and XLSX
        contents = await file.read()
        filename = file.filename or ""
        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))
        
        # Validate required columns
        required_base_columns = ['id', 'parcel_weight', 'service_time', 'window_end']
        missing_columns = [col for col in required_base_columns if col not in df.columns]
        
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required columns: {', '.join(missing_columns)}"
            )
        
        # Check if geocoding is needed
        has_address = 'address' in df.columns
        has_coordinates = 'latitude' in df.columns and 'longitude' in df.columns
        
        if not has_address and not has_coordinates:
            raise HTTPException(
                status_code=400,
                detail="CSV must have either 'address' column OR 'latitude' and 'longitude' columns"
            )
        
        # GEOCODING: Convert addresses to coordinates
        if has_address and not has_coordinates:
            print("\n" + "="*60)
            print("GEOCODING ADDRESSES")
            print("="*60)
            
            addresses = df['address'].tolist()
            print(f"Total addresses to geocode: {len(addresses)}\n")
            
            # Batch geocode all addresses
            geocoded_results = await batch_geocode(addresses)
            
            # Add geocoded coordinates to dataframe
            df['latitude'] = [r.get('latitude') for r in geocoded_results]
            df['longitude'] = [r.get('longitude') for r in geocoded_results]
            df['formatted_address'] = [r.get('formatted_address', '') for r in geocoded_results]
            df['geocode_confidence'] = [r.get('confidence', 0.0) for r in geocoded_results]
            df['geocode_source'] = [r.get('source', 'none') for r in geocoded_results]
            
            # Check for failed geocodes
            failed = df[df['latitude'].isna()]
            if len(failed) > 0:
                failed_count = len(failed)
                total_count = len(addresses)
                success_rate = ((total_count - failed_count) / total_count) * 100
                
                failed_addresses = failed[['id', 'address']].to_dict(orient='records')
                print(f"\n⚠️  WARNING: {failed_count} addresses failed to geocode ({success_rate:.1f}% success rate)")
                
                # If more than 20% failed, reject the upload
                if success_rate < 80:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "geocoding_failed",
                            "message": f"{failed_count} addresses could not be geocoded ({success_rate:.1f}% success). Please fix addresses and retry.",
                            "failed_addresses": failed_addresses,
                            "total_failed": failed_count,
                            "total_addresses": total_count
                        }
                    )
                else:
                    # Allow upload but exclude failed addresses
                    print(f"✓ Proceeding with {total_count - failed_count} successfully geocoded addresses")
                    df = df.dropna(subset=['latitude', 'longitude'])
            
            print(f"\n✓ Successfully geocoded {len(df)} addresses!")
            print("="*60 + "\n")
        
        # Store in global variable
        uploaded_data = df
        
        
        # Convert window_end and compute window_start
        uploaded_data['window_end_minutes'] = uploaded_data['window_end'].apply(parse_window_end)
        uploaded_data['window_start'] = uploaded_data['window_end_minutes'].apply(get_shift_start)
        
        print(f"✓ Parsed window_end (HH:MM:SS → minutes) and auto-assigned window_start from shifts")
        
        # Prepare response data - exclude technical/geocoding columns
        # Users don't need to see: latitude, longitude, window_start, formatted_address, geocode_confidence, geocode_source
        # window_end is kept visible as it shows the requested delivery time
        # These are used internally by the VRP solver but not shown in UI
        exclude_columns = ['latitude', 'longitude', 'window_start', 'window_end_minutes', 'formatted_address', 'geocode_confidence', 'geocode_source']
        display_columns = [col for col in df.columns if col not in exclude_columns]
        display_data = df[display_columns].fillna('').to_dict(orient='records')
        
        return JSONResponse(content={
            "status": "success",
            "data": display_data,
            "columns": display_columns,
            "row_count": len(df),
            "geocoded": has_address and not has_coordinates,
            "message": f"Successfully uploaded {len(df)} records" + 
                      (f" (geocoded from addresses)" if (has_address and not has_coordinates) else "")
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.post("/api/update-data")
async def update_data(update: DataUpdate):
    """Update the uploaded data"""
    global uploaded_data
    
    try:
        print(f"Received update request with {len(update.data)} rows")
        
        # Convert updated data to DataFrame
        updated_df = pd.DataFrame(update.data)
        
        # Ensure 24-hour time is parsed to minutes
        if 'window_end' in updated_df.columns:
            updated_df['window_end_minutes'] = updated_df['window_end'].apply(parse_window_end)
        
        print(f"Updated data columns: {list(updated_df.columns)}")
        print(f"Original data columns: {list(uploaded_data.columns) if uploaded_data is not None else 'None'}")
        
        # Preserve internal columns (latitude, longitude, window_start, etc.) from original data
        # Only update user-editable columns
        if uploaded_data is not None and len(uploaded_data) > 0:
            # Columns that should be preserved from original data
            preserve_columns = ['latitude', 'longitude', 'window_start', 'window_end_minutes', 'formatted_address', 
                              'geocode_confidence', 'geocode_source']
            
            # Start with updated data
            merged_df = updated_df.copy()
            
            # Add back preserved columns from original data
            for col in preserve_columns:
                if col in uploaded_data.columns:
                    merged_df[col] = uploaded_data[col]
            
            uploaded_data = merged_df
        else:
            # If original data is None (e.g., after backend restart), 
            # the updated data should already contain all necessary columns
            # This happens when user uploads a file and the data is sent back
            uploaded_data = updated_df
            
            # Check if required columns are present
            required_cols = ['latitude', 'longitude']
            missing_cols = [col for col in required_cols if col not in uploaded_data.columns]
            if missing_cols:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Missing required columns: {missing_cols}. Please re-upload your file."
                )
        
        print(f"Successfully updated data: {len(uploaded_data)} rows, columns: {list(uploaded_data.columns)}")
        
        return JSONResponse(content={
            "status": "success",
            "message": "Data updated successfully",
            "row_count": len(uploaded_data)
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error updating data: {str(e)}")
        print(f"Error type: {type(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating data: {str(e)}")


@app.post("/api/warehouse")
async def update_warehouse(config: WarehouseConfig):
    """Update warehouse location"""
    global warehouse_config
    
    try:
        warehouse_config = {
            "latitude": config.latitude,
            "longitude": config.longitude
        }
        
        return JSONResponse(content={
            "status": "success",
            "message": "Warehouse location updated",
            "warehouse": warehouse_config
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating warehouse: {str(e)}")


@app.get("/api/warehouse")
async def get_warehouse():
    """Get current warehouse location"""
    return JSONResponse(content=warehouse_config)


@app.post("/api/compute", response_model=ComputeResponse)
async def compute_routes():
    """
    Trigger the vehicle routing optimization computation.
    Steps:
    1. Setup station_node_map table
    2. Insert uploaded data
    3. Randomize attributes (service time, time windows, weights)
    4. Calculate distance matrix via pgRouting
    5. Solve VRP using OR-Tools
    """
    global uploaded_data, warehouse_config
    
    if uploaded_data is None:
        raise HTTPException(status_code=400, detail="No data uploaded. Please upload a CSV file first.")
    
    try:
        print("\n" + "="*60)
        print("STARTING VRP COMPUTATION")
        print("="*60)
        print(f"Uploaded data shape: {uploaded_data.shape}")
        print(f"Uploaded data columns: {list(uploaded_data.columns)}")
        
        # Step 1: Setup table
        print("\n[Step 1/5] Setting up station_node_map table...")
        setup_station_node_map_table(conn)
        
        # Clear unassigned parcels table for fresh tracking
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE vector.unassigned_parcels")
        conn.commit()
        cur.close()
        
        print("✓ Table setup complete")
        
        # Step 2: Insert stations
        print("\n[Step 2/5] Inserting stations from dataframe...")
        # DEBUG PRINTS
        print(f"DEBUG: uploaded_data columns: {uploaded_data.columns.tolist()}")
        if len(uploaded_data) > 0:
            print(f"DEBUG: first row window_end: {uploaded_data.iloc[0].get('window_end')}")
            print(f"DEBUG: first row window_end_minutes: {uploaded_data.iloc[0].get('window_end_minutes')}")
        
        t_step2 = time.perf_counter()
        insert_stations_from_dataframe(conn, uploaded_data)
        print(f"✓ Stations inserted (took {time.perf_counter() - t_step2:.2f}s)")
        
        # Step 3: Randomize attributes (optional, can be removed if data is already complete)
        # randomize_station_attributes(conn)
        
        # Step 4: Calculate distance matrix
        print("\n[Step 3/5] Calculating distance matrix via pgRouting...")
        t_step3 = time.perf_counter()
        calculate_distance_matrix(conn, warehouse_config["longitude"], warehouse_config["latitude"])
        print(f"✓ Distance matrix calculated (took {time.perf_counter() - t_step3:.2f}s)")
        
        # Step 5: Solve VRP
        print("\n[Step 4/5] Solving VRP with OR-Tools...")
        t_step4 = time.perf_counter()
        vrp_result = await solve_vrp(warehouse_config["longitude"], warehouse_config["latitude"])
        
        # Save transient metadata for the results API
        global LAST_VRP_METADATA
        LAST_VRP_METADATA = {
            "weather_alerts": vrp_result.get("weather_alerts", []),
            "weather_rerouted": vrp_result.get("weather_rerouted", False),
            "rerouted_vehicles": vrp_result.get("rerouted_vehicles", [])
        }
        print(f"✓ VRP solved (took {time.perf_counter() - t_step4:.2f}s)")
        
        print("\n" + "="*60)
        print("VRP COMPUTATION COMPLETED SUCCESSFULLY")
        print("="*60 + "\n")
        
        return ComputeResponse(
            status="success",
            message="Route optimization completed successfully"
        )
        
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        print(f"\n❌ ERROR during computation: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        print(f"Traceback:\n{tb_str}")
        
        # Write to file so I can read it
        with open("traceback.txt", "w") as f:
            f.write(tb_str)
            
        raise HTTPException(status_code=500, detail=f"Error during computation: {str(e)}")


def get_all_results_data(conn):
    """Helper to fetch all routing results from database and format for frontend"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Fetch summary
        # Note: fetch_results_summary uses station_node_map and route_geometries
        summary_data = fetch_results_summary(conn)
        
        # Fetch all station status/arrival data — ordered by arrival_time for correct delivery sequence
        # IMPORTANT: Use dict-like row access (RealDictCursor)
        cur.execute("SELECT station_id, ST_X(geom) as lon, ST_Y(geom) as lat, vehicle_id, parcel_weight, arrival_time, delivery_status FROM vector.station_node_map ORDER BY vehicle_id, arrival_time")
        stations_data = cur.fetchall()
        
        # Fetch route geometries
        route_geojson = fetch_route_geometries_geojson(conn)
        
        # Fetch undelivered parcels
        cur.execute("SELECT station_id, latitude, longitude FROM vector.unassigned_parcels ORDER BY station_id")
        undelivered_data = cur.fetchall()
        
        # Read fleet config from DB (stays in sync with solver)
        fleet = get_fleet_vehicles(conn)
        fleet_by_id = {i + 1: v for i, v in enumerate(fleet)}
        
        vehicles = []
        parcels = []
        total_cost = 0
        
        for vehicle in summary_data["vehicles"]:
            vehicle_id = vehicle["vehicle_id"]
            
            # Filter stations for this vehicle
            v_stations = [
                {
                    "station_id": str(s['station_id']),
                    "lat": float(s['lat']),
                    "lon": float(s['lon']),
                    "arrival_time": s['arrival_time'] if s['arrival_time'] else "N/A",
                    "status": s['delivery_status'] if s['delivery_status'] else "UNKNOWN"
                }
                for s in stations_data if s['vehicle_id'] == vehicle_id
            ]
            
            if not v_stations:
                continue
                
            # For each assigned station, add to global parcels list for map
            for s in stations_data:
                if s['vehicle_id'] == vehicle_id:
                    parcels.append({
                        "station_id": str(s['station_id']),
                        "lat": float(s['lat']),
                        "lon": float(s['lon']),
                        "vehicle_id": vehicle_id,
                        "color": VEHICLE_COLORS[vehicle_id - 1] if vehicle_id <= len(VEHICLE_COLORS) else "#888888"
                    })
            
            dist_km = float(vehicle["total_km"])
            
            # Get fleet config for this vehicle from DB
            v_config = fleet_by_id.get(vehicle_id, {})
            v_cost_per_km = float(v_config.get('cost_per_km', 14))
            v_capacity = int(v_config.get('capacity_kg', 180))
            s_start = int(v_config.get('shift_start', 480))
            s_end = int(v_config.get('shift_end', 1080))
            
            v_cost = dist_km * v_cost_per_km
            total_cost += v_cost
            
            # Map geometry
            v_geometry = [f for f in route_geojson["features"] if f["properties"]["vehicle_id"] == vehicle_id]
            
            vehicles.append({
                "vehicle_id": vehicle_id,
                "total_distance": dist_km,
                "total_weight": int(vehicle["total_weight_kg"]),
                "total_deliveries": int(vehicle["parcel_count"]),
                "cost": round(v_cost, 2),
                "stations": v_stations,
                "route_geometry": v_geometry,
                "capacity": v_capacity,
                "utilization": round((int(vehicle["total_weight_kg"]) / v_capacity) * 100, 1) if v_capacity > 0 else 0,
                "work_duration": s_end - s_start,
                "color": VEHICLE_COLORS[vehicle_id - 1] if vehicle_id <= len(VEHICLE_COLORS) else "#888888",
                "clock_in": f"{s_start // 60:02d}:{s_start % 60:02d}",
                "clock_out": f"{s_end // 60:02d}:{s_end % 60:02d}"
            })
            
        return {
            "vehicles": vehicles,
            "summary": {
                "total_distance": float(summary_data["total_distance_km"]),
                "total_cost": round(total_cost, 2),
                "total_parcels": summary_data["total_deliveries"],
                "total_fleets": summary_data["total_vehicles"],
                "warehouse": {
                    "lat": warehouse_config["latitude"],
                    "lon": warehouse_config["longitude"],
                    "name": "Warehouse"
                }
            },
            "parcels": parcels,
            "undelivered_parcels": [
                {
                    "station_id": str(s['station_id']),
                    "lat": float(s['latitude']),
                    "lon": float(s['longitude'])
                }
                for s in undelivered_data
            ],
            "weather_alerts": LAST_VRP_METADATA.get("weather_alerts", []),
            "weather_rerouted": LAST_VRP_METADATA.get("weather_rerouted", False),
            "rerouted_vehicles": LAST_VRP_METADATA.get("rerouted_vehicles", [])
        }
    finally:
        cur.close()


@app.get("/api/results")
async def get_results():
    """
    Retrieve the computed VRP results including:
    - Vehicle routes with geometries
    - Summary statistics
    - Parcel assignments
    """
    try:
        # Fetch summary
        summary_data = fetch_results_summary(conn)
        
        if not summary_data:
            raise HTTPException(status_code=404, detail="No results found. Please run computation first.")
        
        # Fetch route geometries
        route_geojson = fetch_route_geometries_geojson(conn)
        
        # Fetch station assignments — ordered by arrival_time for correct delivery sequence
        cursor = conn.cursor()
        cursor.execute("""
            SELECT station_id, ST_X(geom) as longitude, ST_Y(geom) as latitude, vehicle_id, parcel_weight, 
                   arrival_time, delivery_status
            FROM vector.station_node_map
            WHERE vehicle_id IS NOT NULL
            ORDER BY vehicle_id, arrival_time
        """)
        stations_data = cursor.fetchall()
        
        # Fetch undelivered parcels
        cursor.execute("""
            SELECT station_id, ST_X(geom) as longitude, ST_Y(geom) as latitude
            FROM vector.station_node_map
            WHERE vehicle_id IS NULL
        """)
        undelivered_data = cursor.fetchall()
        cursor.close()
        
        # Build response
        vehicles = []
        parcels = []
        total_cost = 0
        
        # Read fleet config from DB (stays in sync with solver)
        fleet = get_fleet_vehicles(conn)
        fleet_by_id = {i + 1: v for i, v in enumerate(fleet)}
        
        
        for vehicle in summary_data["vehicles"]:
            vehicle_id = vehicle["vehicle_id"]
            
            # Get stations for this vehicle with arrival times and status
            vehicle_stations = [
                {
                    "station_id": str(s[0]),
                    "lat": float(s[2]),  # latitude is column 2
                    "lon": float(s[1]),  # longitude is column 1
                    "arrival_time": s[5] if len(s) > 5 and s[5] else "N/A",  # arrival_time
                    "status": s[6] if len(s) > 6 and s[6] else "UNKNOWN"      # delivery_status
                }
                for s in stations_data if s[3] == vehicle_id
            ]
            
            # CRITICAL FIX: Skip vehicles with no assigned parcels
            # This prevents showing empty vehicles with fake distance/cost/times
            if len(vehicle_stations) == 0:
                continue
            
            # Add to parcels list
            for s in stations_data:
                if s[3] == vehicle_id:
                    parcels.append({
                        "station_id": str(s[0]),
                        "lat": float(s[2]),  # latitude is column 2
                        "lon": float(s[1]),  # longitude is column 1
                        "vehicle_id": vehicle_id,
                        "color": VEHICLE_COLORS[vehicle_id - 1] if vehicle_id <= len(VEHICLE_COLORS) else "#888888"
                    })
            
            # Calculate cost from DB fleet config
            distance_km = float(vehicle["total_km"])
            
            v_config = fleet_by_id.get(vehicle_id, {})
            cost_per_km = float(v_config.get('cost_per_km', 14))
            v_capacity = int(v_config.get('capacity_kg', 180))
            shift_start = int(v_config.get('shift_start', 480))
            shift_end = int(v_config.get('shift_end', 1080))
            
            cost = distance_km * cost_per_km
            total_cost += cost
            
            # Get route geometry for this vehicle
            vehicle_routes = [
                r for r in route_geojson["features"] 
                if r["properties"]["vehicle_id"] == vehicle_id
            ]
            
            # Get shift times (minutes from midnight)
            clock_in = f"{shift_start // 60:02d}:{shift_start % 60:02d}"
            clock_out = f"{shift_end // 60:02d}:{shift_end % 60:02d}"
            work_mins = shift_end - shift_start
            
            vehicles.append({
                "vehicle_id": vehicle_id,
                "total_distance": float(vehicle["total_km"]),
                "total_weight": int(vehicle["total_weight_kg"]),
                "total_deliveries": int(vehicle["parcel_count"]),
                "cost": round(cost, 2),
                "stations": vehicle_stations,
                "route_geometry": vehicle_routes,
                "capacity": v_capacity,
                "utilization": round((int(vehicle["total_weight_kg"]) / v_capacity) * 100, 1) if v_capacity > 0 else 0,
                "work_duration": work_mins,
                "color": VEHICLE_COLORS[vehicle_id - 1] if vehicle_id <= len(VEHICLE_COLORS) else "#888888",
                "clock_in": clock_in,
                "clock_out": clock_out
            })
        
        # Build undelivered parcels list
        undelivered_parcels = [
            {
                "station_id": str(s[0]),
                "lat": float(s[2]),
                "lon": float(s[1])
            }
            for s in undelivered_data
        ]
        
        return JSONResponse(content={
            "vehicles": vehicles,
            "summary": {
                "total_distance": float(summary_data["total_distance_km"]),
                "total_cost": round(total_cost, 2),
                "total_parcels": summary_data["total_deliveries"],
                "total_fleets": summary_data["total_vehicles"],
                "warehouse": {
                    "lat": warehouse_config["latitude"],
                    "lon": warehouse_config["longitude"],
                    "name": "Warehouse"
                }
            },
            "parcels": parcels,
            "undelivered_parcels": undelivered_parcels,
            "weather_alerts": LAST_VRP_METADATA.get("weather_alerts", []),
            "weather_rerouted": LAST_VRP_METADATA.get("weather_rerouted", False),
            "rerouted_vehicles": LAST_VRP_METADATA.get("rerouted_vehicles", [])
        })
        
    except Exception as e:
        conn.rollback()  # Rollback failed transaction
        import traceback
        print(f"\n❌ ERROR retrieving results: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error retrieving results: {str(e)}")


@app.get("/api/download-report")
async def download_report():
    """
    Generate and download comprehensive delivery report as Excel file
    """
    try:
        from report_generator import generate_delivery_report
        
        # Generate report (returns bytes)
        excel_content = generate_delivery_report(conn)
        
        # Create streaming response
        return StreamingResponse(
            iter([excel_content]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=delivery_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")


@app.post("/api/refresh-traffic")
async def refresh_traffic():
    """Trigger a re-solve with live traffic data and return reroute info"""
    try:
        # 1. Re-run VRP with live traffic (solve_vrp creates & closes its own conn)
        solve_results = await solve_vrp(warehouse_config["longitude"], warehouse_config["latitude"])
        
        # 2. Fetch all results using a fresh DB connection
        result_conn = get_db_connection()
        try:
            data = get_all_results_data(result_conn)
        finally:
            result_conn.close()
        
        # 3. Inject reroute and weather info from the solve
        if "rerouted_vehicles" in solve_results:
            data["rerouted_vehicles"] = solve_results["rerouted_vehicles"]
        if "weather_alerts" in solve_results:
            data["weather_alerts"] = solve_results["weather_alerts"]
        if "weather_rerouted" in solve_results:
            data["weather_rerouted"] = solve_results["weather_rerouted"]
            
        return JSONResponse(content=data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────
# Fleet Management Endpoints
# ──────────────────────────────────────────

@app.get("/api/fleet")
async def get_fleet():
    """Get all fleet vehicles. Seeds defaults if table is empty."""
    try:
        conn = get_db_connection()
        vehicles = get_fleet_vehicles(conn)
        conn.close()
        return JSONResponse(content={"vehicles": vehicles})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/fleet")
async def update_fleet_vehicle(vehicle: Dict[str, Any]):
    """Create or update a fleet vehicle."""
    try:
        required = ["name", "capacity_kg", "cost_per_km", "shift_start", "shift_end"]
        for field in required:
            if field not in vehicle:
                raise HTTPException(status_code=400, detail=f"Missing field: {field}")
        conn = get_db_connection()
        result = upsert_fleet_vehicle(conn, vehicle)
        conn.close()
        return JSONResponse(content={"status": "success", "vehicle": result})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/fleet/{vehicle_id}")
async def remove_fleet_vehicle(vehicle_id: int):
    """Delete a fleet vehicle by id."""
    try:
        conn = get_db_connection()
        deleted = delete_fleet_vehicle(conn, vehicle_id)
        conn.close()
        if not deleted:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        return JSONResponse(content={"status": "success", "message": f"Vehicle {vehicle_id} deleted"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────
# Weather Endpoints
# ──────────────────────────────────────────

@app.get("/api/weather")
async def get_weather():
    """Get current weather conditions for all stations"""
    try:
        owm_key = os.getenv("OPENWEATHER_API_KEY", "")
        if not owm_key:
            return JSONResponse(content={"weather_alerts": [], "message": "OPENWEATHER_API_KEY not configured"})
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT station_id, ST_Y(geom) as latitude, ST_X(geom) as longitude FROM vector.station_node_map WHERE vehicle_id IS NOT NULL")
            stations = cur.fetchall()
        finally:
            cur.close()
            conn.close()
        
        if not stations:
            return JSONResponse(content={"weather_alerts": [], "message": "No stations found"})
        
        alerts = []
        for s in stations[:30]:  # Limit to 30 for API rate limits
            weather = weather_service.get_weather(float(s['latitude']), float(s['longitude']))
            if weather["severity"] != "none":
                alerts.append({
                    "station_id": str(s['station_id']),
                    "lat": float(s['latitude']),
                    "lon": float(s['longitude']),
                    "rain_mm": weather["rain_mm"],
                    "description": weather["description"],
                    "severity": weather["severity"],
                    "temp_c": weather["temp_c"],
                    "humidity": weather["humidity"],
                })
        
        return JSONResponse(content={
            "weather_alerts": alerts,
            "total_checked": len(stations[:30]),
            "affected_count": len(alerts),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ===== CHATBOT =====

# Store uploaded data summary for chatbot context
UPLOADED_DATA_SUMMARY = {}

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = None

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Chat with Gemini AI about the current delivery plan data."""
    try:
        # Get current results for context
        conn = get_db_connection()
        try:
            results_data = get_all_results_data(conn)
        finally:
            conn.close()
        
        # Send to Gemini with data context
        response = await chatbot_chat(
            message=req.message,
            results_data=results_data,
            history=req.history,
            uploaded_data_summary=UPLOADED_DATA_SUMMARY
        )
        
        return {"response": response}
    except Exception as e:
        print(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== AUTO RE-OPTIMIZATION =====

async def _auto_reoptimize_loop():
    """Background loop that re-optimizes routes every 10 minutes."""
    import asyncio
    from reoptimize_routes import reoptimize_routes
    
    while AUTO_REOPTIMIZE["enabled"]:
        await asyncio.sleep(AUTO_REOPTIMIZE["interval_seconds"])
        if not AUTO_REOPTIMIZE["enabled"]:
            break
        try:
            print(f"\n🔄 [Auto Re-optimize] Running scheduled re-optimization...")
            result = await reoptimize_routes(
                warehouse_lon=warehouse_config["longitude"],
                warehouse_lat=warehouse_config["latitude"],
            )
            AUTO_REOPTIMIZE["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            AUTO_REOPTIMIZE["last_rerouted"] = result.get("rerouted_vehicles", [])
            
            global LAST_VRP_METADATA
            if result.get("rerouted_vehicles"):
                LAST_VRP_METADATA["rerouted_vehicles"] = result["rerouted_vehicles"]
                print(f"  ⚡ Rerouted vehicles: {result['rerouted_vehicles']}")
            else:
                print(f"  ✓ No route changes needed")
        except Exception as e:
            print(f"  ❌ Auto re-optimize error: {e}")
    print("🛑 [Auto Re-optimize] Background loop stopped.")


@app.post("/api/reoptimize")
async def manual_reoptimize():
    """Manually trigger route re-optimization (keeps parcel assignments fixed)."""
    from reoptimize_routes import reoptimize_routes
    try:
        result = await reoptimize_routes(
            warehouse_lon=warehouse_config["longitude"],
            warehouse_lat=warehouse_config["latitude"],
        )
        AUTO_REOPTIMIZE["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        AUTO_REOPTIMIZE["last_rerouted"] = result.get("rerouted_vehicles", [])
        
        global LAST_VRP_METADATA
        if result.get("rerouted_vehicles"):
            LAST_VRP_METADATA["rerouted_vehicles"] = result["rerouted_vehicles"]
        
        return JSONResponse(content=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auto-reoptimize")
async def toggle_auto_reoptimize(body: dict):
    """Toggle automatic route re-optimization on/off."""
    import asyncio
    enabled = body.get("enabled", False)
    
    if enabled and not AUTO_REOPTIMIZE["enabled"]:
        AUTO_REOPTIMIZE["enabled"] = True
        AUTO_REOPTIMIZE["task"] = asyncio.create_task(_auto_reoptimize_loop())
        print("✅ Auto re-optimization ENABLED (every 10 minutes)")
    elif not enabled and AUTO_REOPTIMIZE["enabled"]:
        AUTO_REOPTIMIZE["enabled"] = False
        if AUTO_REOPTIMIZE["task"]:
            AUTO_REOPTIMIZE["task"].cancel()
            AUTO_REOPTIMIZE["task"] = None
        print("🛑 Auto re-optimization DISABLED")
    
    return JSONResponse(content={
        "enabled": AUTO_REOPTIMIZE["enabled"],
        "interval_seconds": AUTO_REOPTIMIZE["interval_seconds"],
        "last_run": AUTO_REOPTIMIZE["last_run"],
    })


@app.get("/api/auto-reoptimize/status")
async def get_auto_reoptimize_status():
    """Get current auto re-optimization status."""
    return JSONResponse(content={
        "enabled": AUTO_REOPTIMIZE["enabled"],
        "interval_seconds": AUTO_REOPTIMIZE["interval_seconds"],
        "last_run": AUTO_REOPTIMIZE["last_run"],
        "last_rerouted": AUTO_REOPTIMIZE["last_rerouted"],
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )