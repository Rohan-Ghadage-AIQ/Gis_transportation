from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import pandas as pd
import io
import os
from dotenv import load_dotenv
import json

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

# Load environment variables
load_dotenv()

app = FastAPI(title="Vehicle Routing API", version="1.0.0")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
uploaded_data: Optional[pd.DataFrame] = None
warehouse_config: Dict[str, float] = {
    "latitude": 19.0725,
    "longitude": 72.8724
}

# Vehicle colors for map visualization
VEHICLE_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A",
    "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E2"
]


# Pydantic Models
class HealthResponse(BaseModel):
    status: str
    message: str


class WarehouseConfig(BaseModel):
    latitude: float
    longitude: float


class ComputeResponse(BaseModel):
    status: str
    message: str


# API Endpoints
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        message="Vehicle Routing API is running"
    )


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload CSV or Excel file containing delivery data.
    Expected columns: id, latitude, longitude
    Optional columns: parcel_weight, service_time, window_start, window_end
    """
    global uploaded_data
    
    try:
        # Read file content
        content = await file.read()
        
        # Determine file type and parse
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        elif file.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid file format. Please upload CSV or Excel file."
            )
        
        # Validate required columns
        required_columns = ['id', 'latitude', 'longitude']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required columns: {', '.join(missing_columns)}"
            )
        
        # Store the dataframe globally
        uploaded_data = df
        
        # Convert to JSON for frontend
        data_json = df.to_dict(orient='records')
        columns = df.columns.tolist()
        
        return JSONResponse(content={
            "status": "success",
            "message": f"File '{file.filename}' uploaded successfully",
            "data": data_json,
            "columns": columns,
            "row_count": len(df)
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.post("/api/update-data")
async def update_data(data: List[Dict[str, Any]]):
    """
    Update the uploaded data with edited values from frontend.
    """
    global uploaded_data
    
    try:
        if uploaded_data is None:
            raise HTTPException(status_code=400, detail="No data uploaded yet")
        
        # Convert the updated data back to DataFrame
        uploaded_data = pd.DataFrame(data)
        
        return JSONResponse(content={
            "status": "success",
            "message": "Data updated successfully",
            "row_count": len(uploaded_data)
        })
        
    except Exception as e:
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
    5. Run VRP solver with OR-Tools
    6. Save route geometries to database
    """
    global uploaded_data
    
    try:
        if uploaded_data is None:
            raise HTTPException(status_code=400, detail="No data uploaded yet")
        
        conn = get_db_connection()
        
        # Step 1: Setup table
        setup_station_node_map_table(conn)
        
        # Step 2: Insert stations
        insert_stations_from_dataframe(
            conn, 
            uploaded_data,
            warehouse_config["longitude"],
            warehouse_config["latitude"]
        )
        
        # Step 3: Randomize attributes
        randomize_station_attributes(conn)
        
        # Step 4: Calculate distance matrix
        calculate_distance_matrix(
            conn,
            warehouse_config["longitude"],
            warehouse_config["latitude"]
        )
        
        conn.close()
        
        # Step 5: Run VRP solver
        solver_result = solve_vrp(
            warehouse_config["longitude"],
            warehouse_config["latitude"]
        )
        
        if not solver_result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=solver_result.get("error", "Solver failed")
            )
        
        return ComputeResponse(
            status="success",
            message=f"Route optimization completed. {solver_result['total_vehicles_used']} vehicles used for {solver_result['total_deliveries']} deliveries."
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during computation: {str(e)}")


@app.get("/api/results")
async def get_results():
    """
    Get the computed route results including vehicle routes, parcels, and statistics.
    Returns GeoJSON route geometries with actual road paths.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Fetch route geometries as GeoJSON
        route_geojson = fetch_route_geometries_geojson(conn)
        
        # Fetch results summary
        summary_data = fetch_results_summary(conn)
        
        # Fetch station assignments with details
        cur.execute("""
            SELECT station_id, nearest_node_id, parcel_weight, vehicle_id,
                   ST_X(geom) as longitude, ST_Y(geom) as latitude,
                   arrival_time, delivery_status
            FROM vector.station_node_map
            WHERE vehicle_id IS NOT NULL
            ORDER BY vehicle_id, station_id
        """)
        stations_data = cur.fetchall()
        
        # Get undelivered parcels (stations without vehicle assignment) BEFORE closing connection
        cur.execute("""
            SELECT station_id, ST_X(geom) as longitude, ST_Y(geom) as latitude
            FROM vector.station_node_map
            WHERE vehicle_id IS NULL
        """)
        undelivered_data = cur.fetchall()
        
        conn.close()
        
        # Build vehicles array with complete data
        vehicles = []
        parcels = []
        total_cost = 0
        
        # Vehicle clock-in times (matching vrp_solver.py)
        vehicle_times = [
            ("09:00 AM", 540),  # V1: 9 AM - 6 PM
            ("09:00 AM", 540),  # V2: 9 AM - 6 PM
            ("07:00 AM", 360),  # V3: 7 AM - 3 PM
            ("07:00 AM", 540),  # V4: 7 AM - 6 PM
            ("09:00 AM", 480),  # V5: 9 AM - 5 PM
            ("08:00 AM", 600),  # V6: 8 AM - 6 PM
            ("08:00 AM", 720),  # V7: 8 AM - 9 PM
            ("07:00 AM", 660)   # V8: 7 AM - 8 PM
        ]
        
        # Vehicle costs per km
        vehicle_costs_per_km = [15, 20, 25, 12, 15, 12, 10, 10]
        
        # Vehicle capacities
        vehicle_capacities = [175, 261, 348, 156, 178, 142, 118, 125]
        
        for vehicle in summary_data["vehicles"]:
            vehicle_id = vehicle["vehicle_id"]
            
            # Get stations for this vehicle with arrival times and status
            vehicle_stations = [
                {
                    "station_id": str(s[0]),
                    "lat": float(s[5]),
                    "lon": float(s[4]),
                    "arrival_time": s[6] if len(s) > 6 and s[6] else "N/A",  # arrival_time from DB
                    "status": s[7] if len(s) > 7 and s[7] else "UNKNOWN"      # delivery_status from DB
                }
                for s in stations_data if s[3] == vehicle_id
            ]
            
            # Add to parcels list
            for s in stations_data:
                if s[3] == vehicle_id:
                    parcels.append({
                        "station_id": str(s[0]),
                        "lat": float(s[5]),
                        "lon": float(s[4]),
                        "vehicle_id": vehicle_id,
                        "color": VEHICLE_COLORS[vehicle_id - 1] if vehicle_id <= len(VEHICLE_COLORS) else "#888888"
                    })
            
            # Calculate cost
            distance_km = float(vehicle["total_km"])
            cost = distance_km * vehicle_costs_per_km[vehicle_id - 1]
            total_cost += cost
            
            # Get route geometry for this vehicle
            vehicle_routes = [
                f for f in route_geojson["features"] 
                if f["properties"]["vehicle_id"] == vehicle_id
            ]
            
            # Build vehicle object
            clock_in, max_duration = vehicle_times[vehicle_id - 1]
            
            # Calculate clock-out time
            work_mins = int(distance_km * 2)  # Rough estimate: 2 mins per km
            clock_in_mins = int(clock_in.split(":")[0]) * 60 + int(clock_in.split(":")[1].split()[0])
            if "PM" in clock_in and "12" not in clock_in:
                clock_in_mins += 720
            
            clock_out_mins = clock_in_mins + work_mins
            clock_out_hours = (clock_out_mins // 60) % 24
            clock_out_min = clock_out_mins % 60
            am_pm = "AM" if clock_out_hours < 12 else "PM"
            display_hour = clock_out_hours if clock_out_hours <= 12 else clock_out_hours - 12
            if display_hour == 0:
                display_hour = 12
            clock_out = f"{display_hour:02d}:{clock_out_min:02d} {am_pm}"
            
            vehicles.append({
                "vehicle_id": vehicle_id,
                "stations": vehicle_stations,
                "route_geometry": vehicle_routes,
                "total_distance": distance_km,
                "total_cost": cost,
                "weight_carried": int(vehicle["total_weight_kg"]),
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
        raise HTTPException(status_code=500, detail=f"Error retrieving results: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )

