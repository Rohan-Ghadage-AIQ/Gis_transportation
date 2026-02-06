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
pgRouting calculates distances → OR-Tools optimizes routes → 
Backend fetches geometries → Frontend displays on map
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
│  │ - Endpoints  │  │ - PostGIS    │  │ - VRP Logic  │      │
│  │ - CORS       │  │ - pgRouting  │  │ - Constraints│      │
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
                              └──────────────────┘
                                     │
                                     ▼
                              ┌──────────────────┐
                              │ vrp_solver.py    │
                              │ OR-Tools VRP     │
                              │ Optimization     │
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
    # 1. Fetch distance matrix
    # 2. Create OR-Tools model
    # 3. Add capacity constraints
    # 4. Add time window constraints
    # 5. Solve optimization
    # 6. Update station_node_map with vehicle_id
```

#### Step 4: Generate Route Geometries
```python
# database.py - generate_route_geometries()
def generate_route_geometries(conn):
    # For each vehicle:
    #   1. Get ordered stations
    #   2. Use pgr_dijkstra for each segment
    #   3. Combine into MultiLineString
    #   4. Store in route_geometries table
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
    2. Calculate distance matrix
    3. Solve VRP
    4. Generate route geometries
    5. Return status
    """

@app.get("/api/results")
async def get_results():
    """
    1. Fetch vehicle assignments
    2. Fetch route geometries
    3. Calculate statistics
    4. Return complete results
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
    Each feature:
    - geometry: MultiLineString
    - properties: {vehicle_id, distance_km}
    """
```

#### 3. vrp_solver.py (OR-Tools VRP)

**Optimization Process:**

```python
def solve_vrp(conn):
    """
    Solve Vehicle Routing Problem
    
    Steps:
    1. Fetch distance matrix from database
    2. Create routing model
    3. Add constraints:
       - Vehicle capacity (118-348 kg)
       - Time windows (7 AM - 9 PM)
       - Service times (10 min per stop)
    4. Set objective: Minimize longest route
    5. Solve with first solution strategy
    6. Update database with assignments
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
    
    geometries = []
    for i in range(len(route) - 1):
        start = route[i]
        end = route[i + 1]
        
        # Get path from pgRouting
        path = pgr_dijkstra(start, end)
        
        # Get road geometries
        geom = get_road_geometries(path)
        geometries.append(geom)
    
    # Combine into MultiLineString
    route_geom = ST_Collect(geometries)
    
    # Store in database
    INSERT INTO route_geometries (vehicle_id, route_geom)
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
│ geom (LineString)   │  └─────────────────────┘
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ route_geometries    │
│ ─────────────────── │
│ id (PK)             │
│ vehicle_id          │
│ route_geom (MLS)    │
│ total_distance_km   │
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
- **Vehicles**: Configured for 8 vehicles
- **Computation Time**: 1-3 minutes for 50-100 stations
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

---

**For questions or clarifications, please refer to the main README.md or open an issue.**
