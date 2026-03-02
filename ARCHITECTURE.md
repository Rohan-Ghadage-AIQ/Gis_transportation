# 🏗️ System Architecture & How It Works

This document explains the internal workings of the Vehicle Routing Optimization System for new developers.

## 📚 Table of Contents

- [System Overview](#system-overview)
- [Architecture Diagram](#architecture-diagram)
- [Data Flow](#data-flow)
- [Component Deep Dive](#component-deep-dive)
- [Optimization Process](#optimization-process)
- [Database Operations](#database-operations)
- [Frontend-Backend Communication](#frontend-backend-communication)
- [Key Algorithms](#key-algorithms)

## 🎯 System Overview

The Vehicle Routing Optimization System is a **three-tier architecture**:

1. **Frontend (React)**: User interface for data upload, editing, and visualization
2. **Backend (FastAPI)**: API server handling business logic and optimization
3. **Database (PostgreSQL + PostGIS + pgRouting)**: Spatial data storage and routing calculations

### High-Level Flow

```
User uploads CSV → Frontend parses → Backend stores in DB → 
pgRouting calculates distances → Google Route Optimization / OR-Tools optimizes routes → 
Weather + Traffic sync → Backend generates road geometries → Frontend displays on map
```

## 🗺️ Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         FRONTEND                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ UploadPage   │  │ ResultsPage  │  │  API Service │      │
│  │              │  │              │  │              │      │
│  │ - File Upload│  │ - MapView    │  │ - Axios      │      │
│  │ - Data Table │  │ - StatsPanel │  │ - Endpoints  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│         └──────────────────┴──────────────────┘              │
│                            │                                 │
│                    HTTP/JSON (Axios)                         │
└────────────────────────────┼────────────────────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────┐
│                         BACKEND                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   main.py    │  │ database.py  │  │vrp_solver.py │      │
│  │              │  │              │  │              │      │
│  │ - FastAPI    │  │ - PostgreSQL │  │ - OR-Tools   │      │
│  │ - Endpoints  │  │ - PostGIS    │  │ - Google VRP │      │
│  │ - CORS       │  │ - pgRouting  │  │ - Constraints│      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │google_solver │  │traffic_svc.py│  │weather_svc.py│      │
│  │              │  │              │  │              │      │
│  │ - OAuth2 SA  │  │ - Google API │  │ - OpenWeather│      │
│  │ - Fleet API  │  │ - TomTom API │  │ - Monsoon Sim│      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│         └──────────────────┴──────────────────┘              │
│                            │                                 │
│                      SQL Queries                             │
└────────────────────────────┼────────────────────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────┐
│                        DATABASE                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              PostgreSQL + PostGIS + pgRouting        │   │
│  │                                                      │   │
│  │  Tables:                                             │   │
│  │  - vector.station_node_map    (delivery points)     │   │
│  │  - vector.road_maharashtra    (road network)        │   │
│  │  - vector.distance_matrix     (distances)           │   │
│  │  - vector.route_geometries    (route paths)         │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 🔄 Data Flow

### 1. Upload Phase

```
┌─────────┐     CSV/Excel      ┌──────────┐
│  User   │ ─────────────────> │ Frontend │
└─────────┘                     └──────────┘
                                     │
                                     │ FormData
                                     ▼
                              ┌──────────┐
                              │ Backend  │
                              │ /upload  │
                              └──────────┘
                                     │
                                     │ pandas.read_csv()
                                     ▼
                              ┌──────────┐
                              │ DataFrame│
                              └──────────┘
                                     │
                                     │ to_dict('records')
                                     ▼
                              ┌──────────┐
                              │  JSON    │ ──> Return to Frontend
                              └──────────┘
```

**Code Flow:**

1. **Frontend** (`UploadPage.tsx`):
   ```typescript
   const response = await apiService.uploadFile(selectedFile);
   setUploadedData(response.data);
   setColumns(response.columns);
   ```

2. **Backend** (`main.py`):
   ```python
   @app.post("/api/upload")
   async def upload_file(file: UploadFile):
       df = pd.read_csv(io.BytesIO(content))
       return {
           "data": df.to_dict(orient='records'),
           "columns": df.columns.tolist()
       }
   ```

### 2. Computation Phase

```
┌─────────┐   Click "Compute"   ┌──────────┐
│  User   │ ─────────────────> │ Frontend │
└─────────┘                     └──────────┘
                                     │
                                     │ POST /api/compute
                                     ▼
                              ┌──────────────────┐
                              │ Backend          │
                              │ 1. Insert to DB  │
                              └──────────────────┘
                                     │
                                     ▼
                              ┌──────────────────┐
                              │ database.py      │
                              │ - Setup stations │
                              │ - Snap to roads  │
                              │ - Add warehouse  │
                              └──────────────────┘
                                     │
                                     ▼
                               ┌──────────────────┐
                               │ pgRouting        │
                               │ Calculate        │
                               │ Distance Matrix  │
                               │ (with live_cost) │
                               └──────────────────┘
                                      │
                                      ▼
                                ┌──────────────────┐
                                │ Traffic + Weather│
                                │ Google Routes API│
                                │ Weather Simulatn │
                                └──────────────────┘
                                      │
                                      ▼
                                ┌──────────────────┐
                                │ vrp_solver.py    │
                                │ Google Route Opt │
                                │ (OR-Tools fback) │
                               └──────────────────┘
                                     │
                                     ▼
                              ┌──────────────────┐
                              │ Update DB        │
                              │ - vehicle_id     │
                              │ - route_order    │
                              └──────────────────┘
                                     │
                                     ▼
                              ┌──────────────────┐
                              │ Generate Routes  │
                              │ (pgRouting)      │
                              └──────────────────┘
```

**Detailed Steps:**

#### Step 1: Insert Stations to Database
```python
# database.py - setup_station_node_map()
def setup_station_node_map(conn, data):
    # 1. Clear existing data
    # 2. Insert stations with geometries
    # 3. Find nearest road nodes
    # 4. Randomize weights, service times, time windows
```

#### Step 2: Calculate Distance Matrix
```python
# database.py - calculate_distance_matrix()
def calculate_distance_matrix(conn):
    # Uses pgRouting's pgr_dijkstra
    # Calculates shortest path between all station pairs
    # Stores in vector.distance_matrix
```

#### Step 3: Solve VRP
```python
# vrp_solver.py - solve_vrp()
def solve_vrp(conn):
    # 1. Fetch distance matrix (Values are in travel SECONDS)
    # 2. Create OR-Tools model
    # 3. Fetch Dynamic Fleet Config (shifts, capacities, costs) from vector.fleet_vehicles
    # 4. Add capacity constraints (per vehicle)
    # 5. Add time window constraints (travel_time = matrix_value / 60)
    # 6. Solve optimization
    # 7. Update station_node_map with vehicle_id
```

**Travel Time Logic Fix**:
Previously, the solver treated distance matrix values as meters and divided by 666. However, pgRouting calculates `cost_s` (seconds). The system now correctly divides by 60 to convert **seconds to minutes**, ensuring 100% accurate schedules.

**Temporal Normalization (Cross-Midnight Shifts)**:
For shifts starting one day and ending the next (e.g., Vehicle 10: 08:00 AM to 01:04 AM), the solver normalizes the `end_time` by adding 1440 minutes (24 hours). This prevents the "End < Start" error and ensures OR-Tools correctly schedules late-night deliveries.

**Dynamic Configuration**:
The system no longer uses hardcoded vehicle lists. Both the **VRP Solver** and the **Results API** (`/api/results`) fetch the current fleet state from the database. This ensures that any changes made to vehicle shifts or capacities in the UI are immediately reflected in the next optimization.

**Result Metadata Persistence**:
Since weather alerts and "Rerouted" flags are transient (not stored in the DB station/route tables), they are captured in a global `LAST_VRP_METADATA` store in `main.py` during computation. The `/api/results` endpoint combines DB data with this metadata to provide the full dashboard view.

#### Step 4: Generate Route Geometries
```python
# database.py - save_route_geometry()
def save_route_geometry(conn, vehicle_id, route_nodes):
    # For each vehicle, saves per-stop-pair segments:
    #   1. Each stop-pair gets its own geometry row
    #   2. Each row includes segment_index and avg_traffic_factor
    #   3. Traffic factor = AVG(road_maharashtra.traffic_factor) along segment
    #   4. Enables per-segment color-coding on the map
```

### 3. Results Phase

```
┌─────────┐  Navigate to Results  ┌──────────┐
│  User   │ ───────────────────> │ Frontend │
└─────────┘                       └──────────┘
                                       │
                                       │ GET /api/results
                                       ▼
                                ┌──────────────┐
                                │ Backend      │
                                │ Fetch:       │
                                │ - Vehicles   │
                                │ - Stations   │
                                │ - Geometries │
                                │ - Summary    │
                                └──────────────┘
                                       │
                                       │ JSON Response
                                       ▼
                                ┌──────────────┐
                                │ Frontend     │
                                │ - MapView    │
                                │ - StatsPanel │
                                └──────────────┘
```

## 🔍 Component Deep Dive

### Frontend Components

#### 1. UploadPage.tsx

**Purpose**: Handle file upload and data editing

**Key Functions:**
```typescript
handleFileSelection(file) {
  // 1. Validate file type
  // 2. Call API to upload
  // 3. Store data in state
  // 4. Display in table
}

handleCellEdit(rowIndex, column, value) {
  // Update data in state
  // Changes will be sent on compute
}

handleCompute() {
  // 1. Send updated data to backend
  // 2. Trigger computation
  // 3. Navigate to results
}
```

**State Management:**
- `file`: Uploaded file object
- `uploadedData`: Array of delivery records
- `columns`: Column names from CSV
- `isLoading`: Loading state
- `error`: Error messages

#### 2. ResultsPage.tsx

**Purpose**: Display optimization results

**Key Functions:**
```typescript
useEffect(() => {
  fetchResults(); // On component mount
}, []);

async function fetchResults() {
  const results = await apiService.getResults();
  setResults(results);
}
```

**Layout:**
```
┌────────────────────────────────────────┐
│           Results Page                 │
├──────────────┬─────────────────────────┤
│              │                         │
│ StatsPanel   │      MapView            │
│ (33%)        │      (67%)              │
│              │                         │
│ - Summary    │  - Routes               │
│ - Vehicles   │  - Markers              │
│ - Undelivered│  - Legend               │
│              │                         │
└──────────────┴─────────────────────────┘
```

#### 3. MapView.tsx

**Purpose**: Render interactive map with routes

**Initialization:**
```typescript
useEffect(() => {
  // 1. Initialize MapTiler map
  const map = new maptilersdk.Map({
    container: mapContainer.current,
    center: [warehouse.lon, warehouse.lat],
    zoom: 10
  });

  // 2. On map load:
  map.on('load', () => {
    // Add warehouse marker
    // Add vehicle routes
    // Add station markers
  });
}, []);
```

**Route Rendering:**
```typescript
// For each vehicle:
vehicle.route_geometry.forEach((feature, idx) => {
  // Add GeoJSON source
  map.addSource(`route-${vehicle_id}-${idx}`, {
    type: 'geojson',
    data: feature  // MultiLineString from database
  });

  // Add line layer
  map.addLayer({
    id: `route-${vehicle_id}-${idx}`,
    type: 'line',
    paint: {
      'line-color': vehicle.color,
      'line-width': 5,
      'line-opacity': 0.95
    }
  });

  // Add direction arrows
  map.addLayer({
    id: `route-arrows-${vehicle_id}-${idx}`,
    type: 'symbol',
    layout: {
      'symbol-placement': 'line',
      'icon-image': 'arrow'
    }
  });
});
```

#### 4. StatsPanel.tsx

**Purpose**: Display statistics and vehicle details

**Structure:**
```typescript
<div>
  {/* Summary Cards */}
  <SummaryCard title="Total Distance" value={summary.total_distance} />
  <SummaryCard title="Total Cost" value={summary.total_cost} />
  
  {/* Vehicle Breakdown */}
  {vehicles.map(vehicle => (
    <details>
      <summary>Vehicle {vehicle.vehicle_id}</summary>
      <VehicleDetails vehicle={vehicle} />
    </details>
  ))}
  
  {/* Undelivered Parcels */}
  {undelivered_parcels.length > 0 && (
    <UndeliveredSection parcels={undelivered_parcels} />
  )}
</div>
```

### Backend Components

#### 1. main.py (FastAPI Application)

**Endpoints:**

```python
@app.post("/api/upload")
async def upload_file(file: UploadFile):
    """
    1. Read file (CSV/Excel)
    2. Parse with pandas
    3. Validate columns
    4. Return JSON data
    """

@app.post("/api/update-data")
async def update_data(data: List[dict]):
    """
    1. Receive edited data
    2. Update global DataFrame
    3. Return success
    """

@app.post("/api/compute")
async def compute_routes():
    """
    1. Insert data to database
    2. Calculate distance matrix (with live_cost from traffic)
    3. Sync Google/TomTom traffic + weather simulation for delivery zones
    4. Solve VRP (Google Route Optimization or OR-Tools fallback)
    5. Reset stale assignments, apply Google's vehicle-to-parcel mapping
    6. Generate per-segment route geometries with traffic factors
    7. Return status
    """

@app.get("/api/results")
async def get_results():
    """
    1. Fetch vehicle assignments
    2. Fetch per-segment route geometries with traffic colors
    3. Calculate statistics (distance, weight, utilization per vehicle)
    4. Return complete results with weather alerts
    """

@app.post("/api/refresh-traffic")
async def refresh_traffic():
    """
    1. Re-query Google Routes API / weather simulation for live data
    2. Update road_maharashtra.traffic_factor + live_cost_s
    3. Re-generate route geometries with updated traffic colors
    4. Detect rerouted vehicles
    5. Return updated results + reroute info
    """
```

#### 2. database.py (PostgreSQL Operations)

**Key Functions:**

```python
def setup_station_node_map(conn, data):
    """
    Setup delivery stations in database
    
    Steps:
    1. Clear existing data
    2. Insert stations with Point geometries
    3. Find nearest road network nodes
    4. Randomize parcel weights (10-30 kg)
    5. Randomize service times (10 min)
    6. Randomize time windows (0-900 min)
    """

def calculate_distance_matrix(conn):
    """
    Calculate distances between all stations
    
    Uses: pgr_dijkstra(road_network, start, end)
    Cost column: COALESCE(live_cost_s, cost_s)  -- prefers traffic-adjusted cost
    Stores: distance_matrix table
    Format: (from_id, to_id, distance_km, duration_min)
    """

def generate_route_geometries(conn):
    """
    Generate actual road paths for routes
    
    For each vehicle:
    1. Get ordered stations (by route_order)
    2. Add warehouse at start and end
    3. For each segment:
       - Run pgr_dijkstra
       - Get road geometries
       - Combine into MultiLineString
    4. Store in route_geometries table
    """

def fetch_route_geometries_geojson(conn):
    """
    Fetch routes as GeoJSON for frontend
    
    Returns: GeoJSON FeatureCollection
    Each feature (one per stop-pair segment):
    - geometry: MultiLineString
    - properties: {vehicle_id, segment_index, traffic_factor, traffic_color}
    
    Traffic colors:
    - #22C55E (green)  — free flow (≤1.1×)
    - #EAB308 (yellow) — light (1.1×–1.5×)
    - #F97316 (orange) — moderate (1.5×–2.0×)
    - #DC2626 (red)    — heavy (>2.0×)
    """
```

#### 3. vrp_solver.py (Multi-Solver VRP)

**Optimization Process:**

```python
def solve_vrp(conn):
    """
    Solve Vehicle Routing Problem
    
    Steps:
    1. Fetch distance matrix from database
    2. Reset traffic factors to baseline
    3. Parallel sync: Google Routes API traffic + Weather simulation
    4. Batch update road costs: traffic_factor + live_cost_s
    5. If USE_GOOGLE_OPTIMIZATION=true:
       a. Build Google Route Optimization request (OAuth2 Service Account)
       b. Delivery-only mode (loadDemands enforces total weight ≤ capacity)
       c. Parse response, map shipments to vehicles
       d. Reset stale station assignments, apply Google's mapping
    6. Else (OR-Tools fallback):
       a. Create routing model with constraints
       b. Vehicle capacity, time windows, service times
       c. Solve with first solution strategy
    7. Generate road geometries with avg_traffic_factor per segment
    """
```

**OR-Tools Model:**

```python
# Create routing index manager
manager = pywrapcp.RoutingIndexManager(
    num_locations,
    num_vehicles,
    depot_index
)

# Create routing model
routing = pywrapcp.RoutingModel(manager)

# Distance callback
def distance_callback(from_index, to_index):
    from_node = manager.IndexToNode(from_index)
    to_node = manager.IndexToNode(to_index)
    return distance_matrix[from_node][to_node]

# Add distance dimension
routing.AddDimension(
    distance_callback,
    slack_max=0,
    capacity=max_distance,
    fix_start_cumul_to_zero=True,
    name='Distance'
)

# Add capacity constraint
def demand_callback(from_index):
    node = manager.IndexToNode(from_index)
    return demands[node]

routing.AddDimensionWithVehicleCapacity(
    demand_callback,
    slack_max=0,
    vehicle_capacities=[175, 261, 348, ...],
    fix_start_cumul_to_zero=True,
    name='Capacity'
)

# Add time window constraint
routing.AddDimension(
    time_callback,
    slack_max=30,
    capacity=max_time,
    fix_start_cumul_to_zero=False,
    name='Time'
)

# Solve
solution = routing.SolveWithParameters(search_parameters)
```

## 🧮 Key Algorithms

### 1. Distance Calculation (pgRouting)

**Algorithm**: Dijkstra's shortest path

```sql
SELECT 
    pgr_dijkstra(
        'SELECT id, source, target, cost FROM vector.road_maharashtra',
        start_node,
        end_node,
        directed := false
    )
```

**How it works:**
1. Builds graph from road network
2. Finds shortest path between two nodes
3. Returns sequence of edges and total cost
4. Cost = distance in kilometers

### 2. VRP Optimization (OR-Tools)

**Algorithm**: Constraint Programming with Local Search

**Objective Function:**
```
Minimize: max(distance of all vehicle routes)
```

**Constraints:**
1. **Capacity**: Sum of parcel weights ≤ vehicle capacity
2. **Time Windows**: Arrival time within [window_start, window_end]
3. **Service Time**: Time spent at each location
4. **Vehicle Availability**: Clock-in to clock-out time

**Search Strategy:**
- First solution: PATH_CHEAPEST_ARC
- Local search: Guided local search
- Time limit: 30 seconds

### 3. Route Geometry Generation

**Process:**
```python
for each vehicle:
    route = [warehouse] + ordered_stations + [warehouse]
    
    for i in range(len(route) - 1):
        start = route[i]
        end = route[i + 1]
        
        # Get path from pgRouting (uses live_cost_s if available)
        path = pgr_dijkstra(start, end)
        
        # Get road geometries + average traffic factor
        geom = get_road_geometries(path)
        avg_tf = AVG(road.traffic_factor for road in path)
        
        # Store as individual segment row
        INSERT INTO route_geometries
            (vehicle_id, segment_index, geom, avg_traffic_factor)
        VALUES (v_id, i, geom, avg_tf)
```

## 🗄️ Database Operations

### Table Relationships

```
┌─────────────────────┐
│ station_node_map    │
│ ─────────────────── │
│ station_id (PK)     │
│ nearest_node_id (FK)│──┐
│ vehicle_id          │  │
│ geom (Point)        │  │
│ parcel_weight       │  │
│ service_time        │  │
│ window_start        │  │
│ window_end          │  │
└─────────────────────┘  │
                         │
                         ▼
┌─────────────────────┐  ┌─────────────────────┐
│ road_maharashtra    │  │ distance_matrix     │
│ ─────────────────── │  │ ─────────────────── │
│ id (PK)             │  │ from_station_id     │
│ source (Node)       │  │ to_station_id       │
│ target (Node)       │  │ distance_km         │
│ cost (Distance)     │  │ duration_min        │
│ traffic_factor      │  └─────────────────────┘
│ live_cost_s         │
│ geom (LineString)   │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ route_geometries    │
│ ─────────────────── │
│ vehicle_id          │
│ segment_index       │
│ geom (Geometry)     │
│ avg_traffic_factor  │
└─────────────────────┘
```

### Query Examples

**Insert Station:**
```sql
INSERT INTO vector.station_node_map (station_id, geom)
VALUES (12345, ST_SetSRID(ST_MakePoint(72.8777, 19.0760), 4326));
```

**Find Nearest Road Node:**
```sql
UPDATE vector.station_node_map s
SET nearest_node_id = (
    SELECT id
    FROM vector.road_maharashtra_vertices_pgr v
    ORDER BY v.the_geom <-> s.geom
    LIMIT 1
);
```

**Calculate Distance:**
```sql
INSERT INTO vector.distance_matrix
SELECT 
    a.station_id AS from_id,
    b.station_id AS to_id,
    SUM(r.cost) AS distance_km
FROM vector.station_node_map a
CROSS JOIN vector.station_node_map b
JOIN pgr_dijkstra(
    'SELECT id, source, target, cost FROM vector.road_maharashtra',
    a.nearest_node_id,
    b.nearest_node_id,
    false
) AS route ON true
JOIN vector.road_maharashtra r ON route.edge = r.id
GROUP BY a.station_id, b.station_id;
```

## 🔗 Frontend-Backend Communication

### API Request Flow

```typescript
// Frontend: api.ts
export const apiService = {
  async uploadFile(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await axios.post('/api/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    
    return response.data;
  }
};
```

```python
# Backend: main.py
@app.post("/api/upload")
async def upload_file(file: UploadFile):
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content))
    
    return JSONResponse({
        "data": df.to_dict(orient='records'),
        "columns": df.columns.tolist()
    })
```

### Data Formats

**Upload Response:**
```json
{
  "status": "success",
  "data": [
    {
      "id": 12345,
      "latitude": 19.0760,
      "longitude": 72.8777,
      "parcel_weight": 25,
      "service_time": 10,
      "window_start": 0,
      "window_end": 480
    }
  ],
  "columns": ["id", "latitude", "longitude", ...],
  "row_count": 50
}
```

**Results Response:**
```json
{
  "vehicles": [
    {
      "vehicle_id": 1,
      "stations": [...],
      "route_geometry": [
        {
          "type": "Feature",
          "geometry": {
            "type": "MultiLineString",
            "coordinates": [[[lon, lat], ...]]
          },
          "properties": {
            "vehicle_id": 1,
            "distance_km": 71.88
          }
        }
      ],
      "total_distance": 71.88,
      "total_cost": 1078.2,
      "clock_in": "09:00 AM",
      "clock_out": "11:23 AM"
    }
  ],
  "summary": {...},
  "parcels": [...],
  "undelivered_parcels": [...]
}
```

## 🎯 Performance Considerations

### Optimization Strategies

1. **Distance Matrix Caching**: Precomputed and stored in database
2. **Spatial Indexing**: PostGIS GIST indexes on geometry columns
3. **Connection Pooling**: Reuse database connections
4. **Lazy Loading**: Routes loaded only when needed
5. **Frontend Caching**: Results stored in React state

### Scalability Limits

- **Stations**: Tested up to 100 delivery points
- **Vehicles**: Configured for 10 vehicles
- **Computation Time**: ~40s for 50-100 stations (with traffic sync)
- **Map Performance**: Smooth rendering up to 500 route segments

## 🐛 Common Issues & Solutions

### Issue 1: Routes Not Displaying

**Cause**: Route geometries not generated
**Solution**: Check `vector.route_geometries` table has data

### Issue 2: Slow Computation

**Cause**: Large distance matrix calculation
**Solution**: Add spatial indexes, limit search radius

### Issue 3: Undelivered Parcels

**Cause**: Capacity or time window constraints too tight
**Solution**: Adjust vehicle capacities or time windows

## 📚 Further Reading

- [OR-Tools VRP Documentation](https://developers.google.com/optimization/routing)
- [pgRouting Manual](https://docs.pgrouting.org/)
- [PostGIS Reference](https://postgis.net/docs/)
- [MapTiler SDK Docs](https://docs.maptiler.com/sdk-js/)

## 🌍 Geocoding System

### Overview

The system includes automatic geocoding to convert addresses to coordinates using **Ola Maps API** (primary, `api.olamaps.io`) with **Nominatim** (OpenStreetMap) as fallback.

### Geocoding Workflow

```
CSV with addresses → Backend detects 'address' column → 
Check geocode cache → Ola Maps API (parallel, 5 concurrent) →
Nominatim fallback (serialized, 1 req/sec) → Coordinates added → Cache results
```

### Implementation Details

**File**: `backend/geocoding.py`

```python
# Ola Maps API (rebranded from olakrutrim.com → olamaps.io)
OLA_MAPS_GEOCODE_URL = "https://api.olamaps.io/places/v1/geocode"

async def geocode_address_krutrim_async(address, client):
    """GET request with api_key param + Origin header (domain whitelisting)"""
    response = await client.get(
        OLA_MAPS_GEOCODE_URL,
        params={"address": address, "language": "en", "api_key": KRUTRIM_API_KEY},
        headers={"Origin": "http://localhost:5173"}  # Required for domain whitelisting
    )
    # Response: geocodingResults[].geometry.location.{lat, lng}

async def batch_geocode(addresses):
    """
    1. Check cache (geocode_cache.py)
    2. Test Krutrim with first address — skip if unreachable
    3. If Krutrim OK: parallel geocode (5 concurrent)
    4. If Krutrim down: serialize via Nominatim (1 req/sec with asyncio.Lock)
    5. Cache all successful results
    """
```

### API Configuration

```env
KRUTRIM_API_KEY=your_ola_maps_api_key    # From maps.olakrutrim.com
USE_KRUTRIM_GEOCODING=true                # Set false to use Nominatim only
```

### Geocoding Metadata

The system stores additional geocoding information:
- `formatted_address`: Standardized address from geocoder
- `geocode_confidence`: Confidence score (0-1)
- `geocode_source`: Source of geocoding (`"krutrim"` or `"nominatim"`)


## 🤖 Gemini AI Chatbot

### Overview

The Results page includes an AI-powered analytics chatbot that answers questions **only from the system's delivery data**. It uses **Google Gemini 2.5 Flash** via the `google.genai` SDK.

### Architecture

```
ResultsPage (ChatWidget.tsx)
  │  User types question
  │  POST /api/chat { message, history[] }
  ▼
main.py → /api/chat endpoint
  │  Fetches current results from DB (get_all_results_data)
  ▼
chatbot_service.py
  │  1. build_data_context() — converts results into structured text:
  │     • Delivery plan summary (vehicles, distance, cost)
  │     • Per-vehicle table (distance, weight, utilization, stops, shift)
  │     • Delivery status per vehicle (ON_TIME, LATE, IN_BUFFER)
  │     • Undelivered parcels with coordinates
  │     • Weather alerts (heavy/moderate/clear)
  │  2. Constructs system prompt with grounding rules:
  │     "Answer ONLY from the data provided. Do NOT use external knowledge."
  │  3. Sends to Gemini with conversation history (last 10 messages)
  ▼
Google Gemini API (gemini-2.5-flash)
  │  Temperature: 0.3 (factual), max_output_tokens: 1024
  ▼
Response returned to ChatWidget → rendered in chat panel
```

### Implementation Files

| File | Purpose |
|------|---------|
| `backend/chatbot_service.py` | Gemini API client, data context builder, system prompt |
| `backend/main.py` (`/api/chat`) | Chat endpoint — fetches results, calls chatbot service |
| `frontend/src/components/ChatWidget.tsx` | Chat UI — violet/royal theme, Gemini icon, suggestion chips |
| `frontend/src/services/api.ts` (`chat()`) | Frontend API method for chat |

### API Configuration

```env
GEMINI_API_KEY=your_gemini_api_key    # From https://aistudio.google.com/
```

### Example Questions

- "Summarize today's delivery plan"
- "Which vehicle has the longest route?"
- "Any late deliveries?"
- "Compare Vehicle 3 and Vehicle 9"
- "Weather impact on routes?"


## 📊 Excel Report Generation

### Overview

The system generates formatted Excel reports with delivery details, vehicle assignments, and color-coded delivery status.

### Report Structure

**File**: `backend/report_generator.py`

The report includes:
1. **Header Row**: Blue background with white bold text
2. **Data Columns**:
   - Vehicle ID, Shift Start/End
   - Total Distance (km), Total Weight (kg)
   - Parcel ID, Parcel Weight, Service Time
   - Window End, Arrival Time
   - Delivery Status, On-Time Status

3. **Color Coding**:
   - 🟢 Green: ON_TIME deliveries
   - 🔴 Red: LATE deliveries
   - 🟡 Yellow: IN_BUFFER (within 15min grace period)

### Report Generation Flow

```
User clicks "Download Report" → 
Backend queries station_node_map → 
Calculate vehicle totals → 
Create Excel workbook with openpyxl → 
Apply formatting and styles → 
Return .xlsx file to user
```

### Key Features

- **Professional Formatting**: Styled headers, borders, alignment
- **Auto Column Widths**: Optimized for readability
- **Status Color Coding**: Visual indicators for delivery performance
- **Vehicle Grouping**: All deliveries grouped by vehicle
- **Comprehensive Data**: Includes all relevant delivery and vehicle information

## 🆕Feature Additions

### 1. 🎯 Selective Route Visibility

**Feature**: Interactive checkboxes to show/hide individual vehicle routes on the map.

**Location**: Results Page → Map Legend (top-right corner)

**How to Use**:
1. Navigate to Results page after computing routes
2. Look at the legend in the top-right corner of the map
3. Click checkboxes next to vehicle names to toggle visibility
4. Use "Show All" / "Hide All" buttons for bulk control

**Benefits**:
- Compare specific routes side-by-side
- Reduce visual clutter when analyzing individual vehicles
- Better route analysis and presentation

**Technical Implementation**:

#### Frontend (`MapView.tsx`)
```typescript
// State for visibility control
const [visibleVehicles, setVisibleVehicles] = useState<Set<number>>(
    new Set(results.vehicles.map(v => v.vehicle_id))
);

// Toggle function
const toggleVehicleVisibility = (vehicleId: number) => {
    setVisibleVehicles(prev => {
        const newSet = new Set(prev);
        if (newSet.has(vehicleId)) {
            newSet.delete(vehicleId);
        } else {
            newSet.add(vehicleId);
        }
        return newSet;
    });
};

// Visibility control effect
useEffect(() => {
    results.vehicles.forEach((vehicle) => {
        const isVisible = visibleVehicles.has(vehicle.vehicle_id);
        const visibility = isVisible ? 'visible' : 'none';

        // Control route layers
        vehicle.route_geometry?.forEach((_, idx) => {
            map.current?.setLayoutProperty(
                `route-${vehicle.vehicle_id}-${idx}`,
                'visibility',
                visibility
            );
        });
        
        // Control markers
        const markers = markersRef.current.get(vehicle.vehicle_id) || [];
        markers.forEach(marker => {
            marker.getElement().style.display = isVisible ? 'block' : 'none';
        });
    });
}, [visibleVehicles, results.vehicles]);
```

**Key Features**:
- Checkboxes in legend for each vehicle
- "Show All" / "Hide All" buttons
- Synchronized route and marker visibility
- Efficient Set-based state management
- MapTiler SDK's `setLayoutProperty` for layer control
- Direct DOM manipulation for marker display

---

### 3. Live Traffic Integration (Multi-Source)

**Feature**: Real-time traffic congestion data from multiple sources adjusts road costs before VRP solving. Routes are optimized using live travel times, not just static map distances.

**Location**: Backend `traffic_service.py` + `weather_service.py` + `vrp_solver.py` + `database.py`

**Traffic Data Sources**:

| Source | Method | Authentication | Status |
|--------|--------|----------------|--------|
| Google Routes API | `duration / staticDuration` | OAuth2 Service Account | Requires API enablement |
| TomTom Flow API | `freeFlowSpeed / currentSpeed` | API Key | Requires API key |
| Weather Simulation | Monsoon penalty factors (3×–10×) | None (local) | Always available |

**How It Works**:
1. Before solving VRP, `reset_traffic_factors()` clears all road costs to baseline
2. **Traffic sync** (parallel):
   - Google Routes API: Compares `duration` (with traffic) vs `staticDuration` (no traffic) via OAuth2
   - Weather simulation: Deterministic monsoon simulation (~40% of stations get rain)
3. `batch_update_traffic_factors()` applies all updates to nearby roads in a single spatial join
4. pgRouting uses `COALESCE(live_cost_s, cost_s)` — prefers traffic-adjusted cost
5. Route geometries store `avg_traffic_factor` per segment for color visualization

**Traffic Factor Interpretation**:
- `1.0` — Road is at free flow speed (no congestion)
- `1.5` — Road is 50% slower than normal (weather: moderate rain)
- `3.0` — Heavy penalty (weather: moderate rainfall zone)
- `10.0` — Severe penalty (weather: heavy rainfall / waterlogging risk)

**API Configuration**:
```env
# Traffic source toggle
TRAFFIC_SOURCE=google              # 'google' or 'tomtom'
GOOGLE_SERVICE_ACCOUNT_JSON=sa.json  # OAuth2 for Google Routes API
TOMTOM_API_KEY=                      # Optional: TomTom API key

# Weather simulation
WEATHER_SIMULATE_RAIN=true           # Simulate monsoon at ~40% of stations
OPENWEATHER_API_KEY=xxx              # Real weather data (when simulation is off)
```

**Technical Implementation**:

#### traffic_service.py — Multi-Source Router
```python
class GoogleTrafficService:
    """Uses Google Routes API (Compute Routes) with OAuth2 Service Account"""
    def get_traffic_factor_async(self, lat, lon, client) -> float:
        """Compare duration vs staticDuration via OAuth2 Bearer token"""

class TomTomTrafficService:
    """Uses TomTom Flow Segment Data API v4 with API key"""
    def get_traffic_factor_async(self, lat, lon, client) -> float:
        """Query freeFlowSpeed / currentSpeed (≥1.0)"""

class MultiSourceTrafficService:
    """Routes requests to Google or TomTom based on TRAFFIC_SOURCE env"""
```

#### weather_service.py — Monsoon Simulation
```python
class OpenWeatherService:
    def _simulate_monsoon(self, lat, lon) -> dict:
        """Deterministic rain simulation: ~15% heavy, ~25% moderate, ~60% clear"""
    
    def get_weather_async(self, lat, lon, client) -> dict:
        """Returns penalty_factor (1.0, 3.0, or 10.0) based on rain severity"""
```

#### database.py — Batch Road Cost Updates
```python
def batch_update_traffic_factors(conn, updates: list):
    """
    Single batch spatial join to update traffic_factor + live_cost_s
    for all roads near given (lat, lon, factor, radius) tuples.
    Replaces individual per-station calls (254x faster).
    """

def reset_traffic_factors(conn):
    """Reset all roads to factor=1.0, live_cost_s=NULL"""
```

---

### 4. 🗺️ Live Traffic Visualization on Map

**Feature**: Vehicle route segments are color-coded by real-time congestion level.

**Location**: Map legend (top-right), with ON/OFF toggle

**Color Coding**:
| Color | Level | Traffic Factor |
|-------|-------|----------------|
| 🟢 Green  | Free Flow | ≤ 1.1× |
| 🟡 Yellow | Light     | 1.1×–1.5× |
| 🟠 Orange | Moderate  | 1.5×–2.0× |
| 🔴 Red    | Heavy     | > 2.0× |

**How It Works**:
1. **Backend**: `save_route_geometry()` saves each stop-pair as a separate row with `avg_traffic_factor`
2. **Backend**: `fetch_route_geometries_geojson()` maps factor → color and includes `traffic_color` in GeoJSON properties
3. **Frontend**: `MapView.tsx` reads `traffic_color` per segment and sets `line-color` accordingly
4. When traffic factor = 1.0 (free flow), segments stay in vehicle's assigned color
5. Congested segments (factor > 1.5) render thicker (7px vs 5px) for emphasis

**Toggle**: Users can switch traffic colors ON/OFF in the map legend panel

---

### 5. Realistic Arrival Times

**Feature**: Vehicles account for warehouse loading time and accurate travel time rounding.

**Problem Solved**: Previously, a vehicle starting at 07:00 could show a parcel arriving at exactly 07:00 — implying instant loading and teleportation.

**Fixes Applied** (in `vrp_solver.py`):

1. **Warehouse Loading Time** — `WAREHOUSE_LOADING_MINUTES = 10`
   - Added as the depot's service time
   - Vehicles spend 10 minutes loading parcels before departing

2. **Travel Time Rounding** — `max(1, round(travel_time))`
   - Short trips (e.g. 400m) used to truncate to 0 minutes via `int()`
   - Now correctly rounds and enforces minimum 1-minute travel between nodes

**Result**: First delivery is always ≥ 11 minutes after vehicle start time (10 min loading + ≥ 1 min travel).

### 2. Unassigned Parcels Reporting

**Feature**: Dedicated Excel sheet showing parcels that couldn't be assigned to any vehicle, with detailed reasons.

**Location**: Excel Report → "Unassigned Parcels" Sheet (2nd tab)

**Tracked Reasons**:
1. **"Could not snap to road network - no valid road node found"**
   - Parcel location is too far from any road
   - No valid road node in the main network component
   
2. **"Could not fit into any vehicle route (capacity/time/distance constraints)"**
   - VRP solver couldn't assign the parcel
   - Exceeded vehicle capacity, time windows, or distance limits

**Excel Sheet Format**:
- **Red Header** (#E74C3C) - alerts user to issues
- **Columns**: Parcel ID, Reason, Latitude, Longitude, Weight (kg), Window End
- **Wide Reason Column** (60 chars) - full text visible
- **Text Wrapping** - long reasons readable
- **Left-aligned reason** - easier to read

**Data Flow**:

```
┌─────────────────────────────────────────────────────────────┐
│                   UNASSIGNED PARCELS FLOW                    │
└─────────────────────────────────────────────────────────────┘

1. STATION INSERTION (database.py)
   ↓
   Check for NULL nearest_node_id
   ↓
   If found → INSERT INTO unassigned_parcels
   Reason: "Could not snap to road network"

2. VRP SOLVING (vrp_solver.py)
   ↓
   Solve optimization
   ↓
   Check for NULL vehicle_id
   ↓
   If found → INSERT INTO unassigned_parcels
   Reason: "Could not fit into any vehicle route"

3. REPORT GENERATION (report_generator.py)
   ↓
   Query unassigned_parcels table
   ↓
   If rows exist → Create "Unassigned Parcels" sheet
   ↓
   Apply red theme and formatting
```

**Technical Implementation**:

#### Database Schema (`database.py`)
```sql
CREATE TABLE vector.unassigned_parcels (
    station_id VARCHAR PRIMARY KEY,
    reason VARCHAR NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    parcel_weight INTEGER,
    window_end INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Tracking NULL Nodes (`database.py`)
```python
# In fetch_station_data()
if null_count > 0:
    cur.execute("""
        INSERT INTO vector.unassigned_parcels 
        (station_id, reason, latitude, longitude, parcel_weight, window_end)
        SELECT 
            station_id,
            'Could not snap to road network - no valid road node found',
            ST_Y(geom) as latitude,
            ST_X(geom) as longitude,
            parcel_weight,
            window_end
        FROM vector.station_node_map
        WHERE nearest_node_id IS NULL
        ON CONFLICT (station_id) DO UPDATE SET reason = EXCLUDED.reason
    """)
```

#### Tracking VRP Drops (`vrp_solver.py`)
```python
# After VRP solving
cur.execute("""
    INSERT INTO vector.unassigned_parcels 
    (station_id, reason, latitude, longitude, parcel_weight, window_end)
    SELECT 
        station_id,
        'Could not fit into any vehicle route (capacity/time/distance constraints)',
        ST_Y(geom) as latitude,
        ST_X(geom) as longitude,
        parcel_weight,
        window_end
    FROM vector.station_node_map
    WHERE vehicle_id IS NULL
    ON CONFLICT (station_id) DO UPDATE SET reason = EXCLUDED.reason
""")
```

#### Report Generation (`report_generator.py`)
```python
# Query unassigned parcels
cursor.execute("""
    SELECT station_id, reason, latitude, longitude, parcel_weight, window_end
    FROM vector.unassigned_parcels
    ORDER BY station_id
""")
unassigned = cursor.fetchall()

# Create sheet if unassigned parcels exist
if unassigned:
    ws_unassigned = wb.create_sheet("Unassigned Parcels")
    
    # Red header theme
    unassigned_header_fill = PatternFill(
        start_color="E74C3C", 
        end_color="E74C3C", 
        fill_type="solid"
    )
    
    # Wide reason column (60 chars)
    ws_unassigned.column_dimensions['B'].width = 60
    
    # Left-align reason with text wrapping
    cell.alignment = Alignment(
        horizontal="left", 
        vertical="center", 
        wrap_text=True
    )
```

#### Lifecycle Management (`main.py`)
```python
@app.on_event("startup")
async def startup_event():
    # Initialize tables on server start
    setup_station_node_map_table(conn)

# In compute_routes()
cur.execute("TRUNCATE TABLE vector.unassigned_parcels")  # Clear on new computation
```

**Database Schema Updates**:

**New Table**: `vector.unassigned_parcels`
- Primary Key: `station_id`
- Indexed: `created_at` (for potential cleanup)
- Cleared: On each new computation

**Modified Table**: `vector.station_node_map`
- Added: `arrival_time TEXT`
- Added: `delivery_status TEXT`

**Testing Guide**:

*Selective Route Visibility*:
1. Run computation with multiple vehicles
2. Navigate to Results page
3. Test individual checkboxes
4. Test "Show All" / "Hide All" buttons
5. Verify routes and markers toggle together

*Unassigned Parcels*:
1. Upload CSV with parcels in remote locations
2. Run computation
3. Download Excel report
4. Check for "Unassigned Parcels" sheet (2nd tab)
5. Verify reasons are descriptive and accurate

**Benefits**:

*For Users*:
- **Better Visibility**: Control which routes to view on map
- **Transparency**: Know exactly why parcels weren't assigned
- **Actionable Insights**: Address location or constraint issues
- **Professional Reports**: Clear documentation of issues

*For Developers*:
- **Clean Architecture**: Separation of concerns
- **Extensible**: Easy to add more unassignment reasons
- **Well-Documented**: Clear code comments and structure
- **Maintainable**: Centralized tracking in dedicated table

## 🐛 Recent Bug Fixes

### Fixed Issues (February 2026)

1. **SQL Syntax Errors**: Fixed f-string interpolation in warehouse node queries
2. **Function Parameter Mismatches**: Corrected calculate_distance_matrix and solve_vrp function calls
3. **Column Name Mismatches**: Updated SQL queries to use PostGIS geometry extraction (ST_X, ST_Y)
4. **Data Structure Mismatches**: Aligned backend field names with frontend expectations (cost vs total_cost)
5. **TypeScript Type Errors**: Updated VehicleRoute interface to match backend response
6. **Report Generation**: Fixed non-existent table references in report queries
7. **Route Geometry Display**: Corrected field name from 'routes' to 'route_geometry'
8. **Parcel Marker Display**: Fixed array indices for coordinate extraction
9. **Batch Traffic Update**: Replaced 86 individual `ST_DWithin(geography)` calls with a single batch spatial join using `&&` operator, reducing traffic sync from 234s to 0.9s (254x faster). See [BUGFIX.md](file:///c:/Users/91832/Desktop/AIQ/GisTransportation4/BUGFIX.md).

## ⚡ Performance

The VRP computation pipeline has been optimized from **~286s to ~42s** (6.8x faster) for 56 parcels and 10 vehicles. Key optimizations include batch spatial updates, parallel API calls, spatial filtering, and solver tuning. Full details in [ARCHITECTURE_PERFORMANCE_SECTION.md](file:///c:/Users/91832/Desktop/AIQ/GisTransportation4/ARCHITECTURE_PERFORMANCE_SECTION.md) and [BUGFIX.md](file:///c:/Users/91832/Desktop/AIQ/GisTransportation4/BUGFIX.md).

---

**For questions or clarifications, please refer to the main README.md or open an issue.**
