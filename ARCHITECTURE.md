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

## 🌍 Geocoding System

### Overview

The system includes automatic geocoding to convert addresses to coordinates using Nominatim (OpenStreetMap's geocoding service).

### Geocoding Workflow

```
CSV with addresses → Backend detects 'address' column → 
Nominatim API calls → Coordinates added → Data stored with metadata
```

### Implementation Details

**File**: `backend/main.py`

```python
def geocode_addresses(df):
    """Geocode addresses using Nominatim"""
    for idx, row in df.iterrows():
        if pd.isna(row.get('latitude')) or pd.isna(row.get('longitude')):
            address = row.get('address', '')
            # Call Nominatim API
            coords = geocode_address(address)
            df.at[idx, 'latitude'] = coords['lat']
            df.at[idx, 'longitude'] = coords['lon']
            df.at[idx, 'geocode_confidence'] = coords['confidence']
    return df
```

### Geocoding Metadata

The system stores additional geocoding information:
- `formatted_address`: Standardized address from geocoder
- `geocode_confidence`: Confidence score (0-1)
- `geocode_source`: Source of geocoding (e.g., "nominatim")

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

### 2. 📊 Unassigned Parcels Reporting

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

---

**For questions or clarifications, please refer to the main README.md or open an issue.**
