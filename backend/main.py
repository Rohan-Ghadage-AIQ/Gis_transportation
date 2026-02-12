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
from datetime import datetime

# Import database and solver modules
from database import (
    get_db_connection,
    setup_station_node_map_table,
    insert_stations_from_dataframe,
    randomize_station_attributes,
    calculate_distance_matrix,
    fetch_route_geometries_geojson,
    fetch_results_summary
)
from vrp_solver import solve_vrp
from geocoding import batch_geocode

load_dotenv()

app = FastAPI()

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

# Database connection
conn = get_db_connection()

# Global variables
uploaded_data = None
warehouse_config = {
    "latitude": 19.0760,  # Mumbai default
    "longitude": 72.8777
}

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
        # Read CSV file
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
        # Validate required columns
        required_base_columns = ['id', 'parcel_weight', 'service_time']
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
            geocoded_results = batch_geocode(addresses)
            
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
        
        # Prepare response data - exclude technical/geocoding columns
        # Users don't need to see: latitude, longitude, window_start, formatted_address, geocode_confidence, geocode_source
        # window_end is kept visible as it shows the requested delivery time
        # These are used internally by the VRP solver but not shown in UI
        exclude_columns = ['latitude', 'longitude', 'window_start', 'formatted_address', 'geocode_confidence', 'geocode_source']
        display_columns = [col for col in df.columns if col not in exclude_columns]
        display_data = df[display_columns].to_dict(orient='records')
        
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
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.post("/api/update-data")
async def update_data(update: DataUpdate):
    """Update the uploaded data"""
    global uploaded_data
    
    try:
        print(f"Received update request with {len(update.data)} rows")
        
        # Convert updated data to DataFrame
        updated_df = pd.DataFrame(update.data)
        
        print(f"Updated data columns: {list(updated_df.columns)}")
        print(f"Original data columns: {list(uploaded_data.columns) if uploaded_data is not None else 'None'}")
        
        # Preserve internal columns (latitude, longitude, window_start, etc.) from original data
        # Only update user-editable columns
        if uploaded_data is not None and len(uploaded_data) > 0:
            # Columns that should be preserved from original data
            preserve_columns = ['latitude', 'longitude', 'window_start', 'formatted_address', 
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
        print("✓ Table setup complete")
        
        # Step 2: Insert stations
        print("\n[Step 2/5] Inserting stations from dataframe...")
        insert_stations_from_dataframe(conn, uploaded_data)
        print("✓ Stations inserted")
        
        # Step 3: Randomize attributes (optional, can be removed if data is already complete)
        # randomize_station_attributes(conn)
        
        # Step 4: Calculate distance matrix
        print("\n[Step 3/5] Calculating distance matrix via pgRouting...")
        calculate_distance_matrix(conn, warehouse_config["longitude"], warehouse_config["latitude"])
        print("✓ Distance matrix calculated")
        
        # Step 5: Solve VRP
        print("\n[Step 4/5] Solving VRP with OR-Tools...")
        solve_vrp(warehouse_config["longitude"], warehouse_config["latitude"])
        print("✓ VRP solved")
        
        print("\n" + "="*60)
        print("VRP COMPUTATION COMPLETED SUCCESSFULLY")
        print("="*60 + "\n")
        
        return ComputeResponse(
            status="success",
            message="Route optimization completed successfully"
        )
        
    except Exception as e:
        print(f"\n❌ ERROR during computation: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        print(f"Traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error during computation: {str(e)}")


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
        
        # Fetch station assignments
        cursor = conn.cursor()
        cursor.execute("""
            SELECT station_id, ST_X(geom) as longitude, ST_Y(geom) as latitude, vehicle_id, parcel_weight, 
                   arrival_time, delivery_status
            FROM vector.station_node_map
            WHERE vehicle_id IS NOT NULL
            ORDER BY vehicle_id, station_id
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
        
        # Vehicle shift times (10 vehicles)
        vehicle_shifts = [
            ("06:00 AM", 720),  # V1: 6 AM - 6 PM
            ("07:00 AM", 840),  # V2: 7 AM - 9 PM
            ("06:00 AM", 780),  # V3: 6 AM - 8 PM
            ("08:00 AM", 720),  # V4: 8 AM - 8 PM
            ("07:00 AM", 720),  # V5: 7 AM - 7 PM
            ("06:00 AM", 660),  # V6: 6 AM - 6 PM
            ("08:00 AM", 840),  # V7: 8 AM - 9 PM
            ("07:00 AM", 780),  # V8: 7 AM - 8 PM
            ("07:00 AM", 720),  # V9: 7 AM - 7 PM
            ("08:00 AM", 780)   # V10: 8 AM - 8 PM
        ]
        
        # Vehicle costs per km (10 vehicles)
        vehicle_costs_per_km = [15, 20, 25, 12, 15, 12, 10, 10, 12, 14]
        
        # Vehicle capacities (10 vehicles)
        vehicle_capacities = [175, 261, 348, 156, 178, 142, 118, 125, 200, 180]
        
        
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
            
            # Calculate cost
            distance_km = float(vehicle["total_km"])
            cost = distance_km * vehicle_costs_per_km[vehicle_id - 1]
            total_cost += cost
            
            # Get route geometry for this vehicle
            vehicle_routes = [
                r for r in route_geojson["features"] 
                if r["properties"]["vehicle_id"] == vehicle_id
            ]
            
            # Get shift times
            clock_in, work_mins = vehicle_shifts[vehicle_id - 1]
            
            # Calculate clock out time
            clock_in_hour = int(clock_in.split(":")[0])
            clock_in_min = int(clock_in.split(":")[1].split()[0])
            clock_in_period = clock_in.split()[1]
            
            # Convert to 24-hour
            if clock_in_period == "PM" and clock_in_hour != 12:
                clock_in_hour += 12
            elif clock_in_period == "AM" and clock_in_hour == 12:
                clock_in_hour = 0
            
            total_mins = clock_in_hour * 60 + clock_in_min + work_mins
            clock_out_hour = (total_mins // 60) % 24
            clock_out_min = total_mins % 60
            clock_out_period = "AM" if clock_out_hour < 12 else "PM"
            display_hour = clock_out_hour if clock_out_hour <= 12 else clock_out_hour - 12
            if display_hour == 0:
                display_hour = 12
            clock_out = f"{display_hour:02d}:{clock_out_min:02d} {clock_out_period}"
            
            vehicles.append({
                "vehicle_id": vehicle_id,
                "total_distance": float(vehicle["total_km"]),
                "total_weight": int(vehicle["total_weight_kg"]),
                "total_deliveries": int(vehicle["parcel_count"]),  # Use parcel_count from DB
                "cost": round(cost, 2),
                "stations": vehicle_stations,
                "route_geometry": vehicle_routes,  # Changed from 'routes' to match frontend
                "capacity": vehicle_capacities[vehicle_id - 1],
                "utilization": round((int(vehicle["total_weight_kg"]) / vehicle_capacities[vehicle_id - 1]) * 100, 1),
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
            "undelivered_parcels": undelivered_parcels
        })
        
    except Exception as e:
        conn.rollback()  # Rollback failed transaction
        print(f"\n❌ ERROR retrieving results: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        print(f"Traceback:\n{traceback.format_exc()}")
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )
