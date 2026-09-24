# =============================================================================
# EXECUTABLE SPECIFICATION — GIS Transportation & Vehicle Routing Optimization
# =============================================================================
# Convert to Jupyter Notebook cells by splitting at the "# %% [markdown]" markers.
# Dependencies: pip install geopandas shapely ortools psycopg2-binary pandas numpy httpx

# %% [markdown]
# # GIS Transportation & Vehicle Routing Optimization — Executable Specification
#
# ---

# %% [markdown]
# ## 1. Executive Summary
#
# **Problem Statement:**
# Logistics operations managing delivery fleets across large metropolitan regions
# (e.g., Maharashtra, India) face a daily challenge: *How do you assign 50–100+ parcels
# across a fleet of 10 heterogeneous vehicles, minimize total distance and cost, respect
# each vehicle's weight capacity and driver shift windows, and adapt in real-time to
# monsoon flooding and traffic congestion — all while using actual road networks, not
# straight-line approximations?*
#
# Currently, most fleet operators rely on manual route planning or basic distance-matrix
# tools that ignore real road topology, live traffic, and weather hazards. This leads to
# sub-optimal routes, missed delivery windows, excessive fuel costs, and dangerous
# exposure to waterlogged roads during monsoon season.
#
# **Goal:**
# Build an automated, spatially-aware Vehicle Routing Optimization system that:
#
# 1. **Solves the Capacitated VRP with Time Windows (CVRPTW)** using real road
#    distances from a PostGIS/pgRouting network — never straight-line approximations.
# 2. **Integrates live traffic congestion** (Google Routes API / TomTom) to penalize
#    slow road segments and re-route vehicles dynamically.
# 3. **Incorporates real-time or simulated monsoon weather** (OpenWeatherMap / IMD
#    thresholds) to avoid waterlogged roads with 3×–10× cost penalties.
# 4. **Supports dual optimization engines**: Google Route Optimization API (OAuth2)
#    as primary, OR-Tools as local fallback — ensuring resilience.
# 5. **Auto-reoptimizes** stop ordering every 10 minutes based on fresh traffic data,
#    keeping parcel-to-vehicle assignments fixed.
# 6. **Geocodes** delivery addresses via Ola Maps API with Nominatim/OSM fallback.
# 7. **Visualizes** results on an interactive map with color-coded routes and
#    per-segment traffic overlays (🟢🟡🟠🔴).
#
# The system transforms raw CSV/Excel delivery manifests into optimized, traffic-aware
# routes with real road geometries, costs, schedules, and downloadable reports.

# %% [markdown]
# ## 2. Data Provenance
#
# ### 2.1 Road Network (PostGIS + pgRouting)
# - **Source:** OpenStreetMap (Maharashtra extract)
# - **Table:** `vector.road_maharashtra` (~843K road segments)
# - **Schema:** `gid`, `source`, `target`, `cost_s` (seconds), `reverse_cost_s`,
#   `geom` (LineString SRID 4326), `traffic_factor`, `live_cost_s`, `last_traffic_update`
# - **Extensions:** PostGIS 3.x, pgRouting 3.x
# - **Spatial Index:** GiST on `geom`, B-tree on `source`/`target`
#
# ### 2.2 Pre-computed Node Table
# - **Table:** `vector.main_road_nodes` — Persistent table of all nodes belonging to
#   the largest connected component (component 11) of the road graph.
# - **Purpose:** Eliminates repeated `pgr_connectedComponents` calls during station snapping.
# - **Index:** GiST on `geom` for fast nearest-node KNN queries.
#
# ### 2.3 Traffic APIs
# - **Google Routes API:** `https://routes.googleapis.com/directions/v2:computeRoutes`
#   — OAuth2 Service Account authentication. Compares `duration` vs `staticDuration`.
# - **TomTom Flow Segment API v4:** `https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json`
#   — API key authentication. Returns `currentSpeed` / `freeFlowSpeed`.
# - **Toggle:** `TRAFFIC_SOURCE=google|tomtom` in `.env`
#
# ### 2.4 Weather API
# - **OpenWeatherMap Current Weather:** `https://api.openweathermap.org/data/2.5/weather`
# - **IMD Rainfall Thresholds:** Light < 2.5 mm/hr, Moderate 2.5–7.5 mm/hr, Heavy ≥ 7.5 mm/hr
# - **Simulation Mode:** `WEATHER_SIMULATE_RAIN=true` — deterministic monsoon using
#   coordinate-seeded hash (~15% heavy, ~25% moderate, ~60% clear)
#
# ### 2.5 Geocoding APIs
# - **Primary:** Ola Maps API — `https://api.olamaps.io/places/v1/geocode`
# - **Fallback:** Nominatim/OSM — `https://nominatim.openstreetmap.org/search`
#   (rate-limited to 1 req/sec)
# - **Cache:** Local JSON file (`geocode_cache.json`) for deduplication
#
# ### 2.6 Optimization APIs
# - **Google Route Optimization (Fleet Routing):**
#   `https://routeoptimization.googleapis.com/v1/projects/{project_id}:optimizeTours`
#   — OAuth2 Service Account, delivery-only mode
# - **OR-Tools (Local):** `ortools==9.11.4210` — SAVINGS heuristic + Guided Local Search

# %% [markdown]
# ## 3. Spatial Methodology
#
# This section details the pure mathematical and spatial logic powering the system.
# **This is the core deliverable for the backend engineering team.**
#
# ---
#
# ### 3.1 Station Snapping (Address → Road Node)
#
# Every delivery address must be "snapped" to the nearest node on the road network
# graph so that pgRouting can compute real road distances.
#
# **Algorithm:**
# 1. Upload CSV with columns: `id`, `latitude`, `longitude` (+ optional `parcel_weight`,
#    `service_time`, `window_start`, `window_end`).
# 2. If addresses (no coordinates), geocode via Ola Maps → Nominatim fallback.
# 3. For each point $(lat_i, lon_i)$, find the nearest node in `vector.main_road_nodes`:
#
# $$node_i = \arg\min_{n \in \text{main\_road\_nodes}} \; d_{KNN}(n.\text{geom}, \; \text{ST\_Point}(lon_i, lat_i))$$
#
# Uses PostGIS KNN operator `<->` with GiST index — $O(\log N)$ per lookup.
#
# 4. Batch insert all stations via temp table + single spatial JOIN (not N individual queries).
#
# ---
#
# ### 3.2 Distance Matrix Calculation (pgRouting Dijkstra)
#
# The VRP solver requires an $N \times N$ distance matrix where $N$ = (1 warehouse + $S$ stations).
#
# **Algorithm:**
# 1. Collect all unique road node IDs: $\{depot\_node\} \cup \{node_1, node_2, \ldots, node_S\}$
# 2. Compute bounding box of all station geometries: `ST_Extent(geom)`
# 3. Run `pgr_dijkstraCost` with **spatial filtering** — only load road segments
#    within `ST_Expand(bbox, 0.3°)` (~33 km buffer):
#
# $$D(i, j) = \text{pgr\_dijkstraCost}(i, j) \quad \text{[in seconds, using } \texttt{COALESCE(live\_cost\_s, cost\_s)}\text{]}$$
#
# 4. Store results in `vector.distance_matrix (start_vid, end_vid, agg_cost)`.
#
# **Critical:** `live_cost_s = cost_s × traffic_factor` — so traffic penalties propagate
# directly into Dijkstra's edge weights.
#
# ---
#
# ### 3.3 Traffic Factor Calculation
#
# Traffic congestion is expressed as a dimensionless multiplicative factor applied to
# road travel times.
#
# **Google Routes API:**
# $$\text{traffic\_factor} = \frac{\text{duration (with traffic)}}{\text{staticDuration (free-flow)}}$$
#
# **TomTom Flow API:**
# $$\text{traffic\_factor} = \frac{\text{freeFlowSpeed}}{\text{currentSpeed}}$$
#
# **Bounds:** $\text{traffic\_factor} \in [0.8, 10.0]$
#
# | Factor Range | Congestion Level | Map Color |
# |---|---|---|
# | ≤ 1.1 | Free flow | 🟢 Green |
# | 1.1 – 1.5 | Light | 🟡 Yellow |
# | 1.5 – 2.0 | Moderate | 🟠 Orange |
# | > 2.0 | Heavy | 🔴 Red |
#
# **Spatial Application:**
# Traffic factors are applied to all road segments within a radius of each station
# using a spatial batch join:
#
# $$\forall \; r \in \text{roads} : r.\text{geom} \;\cap\; \text{ST\_Expand}(station_i, radius) \neq \emptyset \implies r.\text{live\_cost\_s} = r.\text{cost\_s} \times \max(f_i)$$
#
# Radius: ~1.5 km (0.015°). Uses temp table + GiST index join in ONE query.
#
# ---
#
# ### 3.4 Weather Penalty Logic (IMD Classification)
#
# Rainfall intensity is classified per India Meteorological Department (IMD) standards:
#
# | Severity | Rain (mm/hr) | Road Penalty Factor | Effect |
# |---|---|---|---|
# | None | < 2.5 | 1.0× | No change |
# | Moderate | 2.5 – 7.5 | 3.0× | pgRouting prefers alternate roads |
# | Heavy | ≥ 7.5 | 10.0× | pgRouting strongly avoids these roads |
#
# **Simulation Mode Seed:**
# $$\text{seed} = \lfloor |lat \times 10000| \times |lon \times 100| \rfloor \mod 100$$
# - seed < 15 → Heavy rain
# - 15 ≤ seed < 40 → Moderate rain
# - seed ≥ 40 → Clear
#
# ---
#
# ### 3.5 VRP Formulation (CVRPTW)
#
# The Capacitated Vehicle Routing Problem with Time Windows is formulated as:
#
# **Objective:**
# $$\min \sum_{v=1}^{V} \sum_{(i,j) \in \text{route}_v} c_v \cdot D(i,j)$$
#
# where $c_v$ = cost per km for vehicle $v$, $D(i,j)$ = road distance in km.
#
# **Subject to:**
#
# 1. **Capacity:** $\sum_{i \in \text{route}_v} w_i \leq C_v \quad \forall v$
#    (with soft upper bound penalty = 1,000,000 per kg over)
#
# 2. **Time Windows:** $a_i \leq t_i \leq b_i \quad \forall i$
#    (soft upper bound penalty = 100,000 per minute late)
#
# 3. **Shift Constraints:** $S_v^{start} \leq t_v^{depart} \leq S_v^{end}$
#    (overtime buffer = 60 min, penalty = 50,000 per minute)
#
# 4. **Cross-midnight shifts:** If $S_v^{end} < S_v^{start}$, then
#    $S_v^{end} \leftarrow S_v^{end} + 1440$
#
# 5. **Service time:** Each stop adds $s_i$ minutes (default 10 min).
#    Warehouse loading adds 10 min fixed buffer.
#
# 6. **Drop penalty:** 1,000,000,000 per undelivered parcel (effectively infinite).
#
# **Travel time conversion:**
# $$t_{ij} = \max\left(1, \; \text{round}\left(\frac{D_{ij}^{seconds}}{60}\right)\right) + s_i$$
#
# **OR-Tools Configuration:**
# - First Solution: `SAVINGS` heuristic
# - Metaheuristic: `GUIDED_LOCAL_SEARCH`
# - Time limit: 10 seconds
# - Slack (waiting): up to 120 minutes
#
# ---
#
# ### 3.6 Google Route Optimization (Delivery-Only Mode)
#
# When `USE_GOOGLE_OPTIMIZATION=true`, the system uses Google's Fleet Routing API.
#
# **Critical Design Decision — Delivery-Only Mode:**
# Shipments use `deliveries` (not `pickups`) with `loadDemands.weight`. This ensures:
# - Total assigned weight per vehicle never exceeds `loadLimits.weight.maxLoad`
# - Vehicle utilization ≤ 100%
#
# Previously, pickup+delivery mode allowed Google to exploit time-based load curves
# where max load at any point < capacity, even though total weight > capacity.
#
# ---
#
# ### 3.7 Route Geometry Generation (pgRouting → GeoJSON)
#
# After VRP solution, actual road geometries are generated for map display:
#
# 1. For each vehicle's ordered stop sequence: $[depot, s_1, s_2, \ldots, s_k, depot]$
# 2. For each consecutive pair $(s_i, s_{i+1})$, run `pgr_dijkstra` with spatial filter.
# 3. JOIN result edges with `vector.road_maharashtra` to get LineString geometries.
# 4. `ST_Collect` + `ST_Multi` to merge into per-segment MultiLineString.
# 5. Record `avg_traffic_factor` per segment for color-coded visualization.
#
# **Batch optimization:** Global bounding box computed once, all vehicles processed
# with `LATERAL JOIN` — 8 queries instead of 56.
#
# ---
#
# ### 3.8 Auto Re-optimization (TSP per Vehicle)
#
# Every 10 minutes, the system re-orders stops within each vehicle:
#
# 1. Read current vehicle→parcel assignments from DB (fixed).
# 2. Refresh traffic data (new API calls).
# 3. For each vehicle with ≥2 stops, solve a mini-TSP using OR-Tools or Google.
# 4. Compare new order vs old order → flag rerouted vehicles.
# 5. Regenerate road geometries with fresh traffic colors.
#
# **Key constraint:** Parcel-to-vehicle assignments are NEVER changed.
# Only the stop ordering within each vehicle is re-optimized.
#
# ---
#
# ### 3.9 Road Distance Calculation (Real km)
#
# Route distances are calculated from saved geometries using PostGIS geography:
#
# $$\text{distance\_km}_v = \frac{\sum_{s \in \text{segments}_v} \text{ST\_Length}(s.\text{geom}::geography)}{1000}$$
#
# **Operational cost:**
# $$\text{cost}_v = \text{distance\_km}_v \times c_v$$

# =============================================================================
# EXECUTABLE SPECIFICATION — Part 2: Prototype Code & Tech Handoff (Sections 4–5)
# =============================================================================

# %% [markdown]
# ## 4. Prototype Code
#
# Each section below is a self-contained proof-of-concept that validates
# the spatial methodology from Section 3. These are NOT production code.

# %% [markdown]
# ### 4.1 — Station Snapping: Address → Nearest Road Node
#
# **What this does:** Demonstrates snapping a delivery coordinate to the
# nearest node on the road network using PostGIS KNN operator.

# %%
import psycopg2
from psycopg2.extras import RealDictCursor

# --- Configuration (replace with your actual DB credentials) ---
DB_CONFIG = {
    "dbname": "your_db",
    "user": "your_user",
    "password": "your_password",
    "host": "localhost",
    "port": "5432"
}

def snap_to_road_node(lat: float, lon: float, conn) -> dict:
    """Snap a lat/lon to the nearest road network node using KNN."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT node_id,
               ST_X(geom) AS node_lon,
               ST_Y(geom) AS node_lat,
               ST_Distance(geom::geography, ST_SetSRID(ST_Point(%s, %s), 4326)::geography) AS dist_meters
        FROM vector.main_road_nodes
        ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 4326)
        LIMIT 1;
    """, (lon, lat, lon, lat))
    result = dict(cur.fetchone())
    cur.close()
    return result

# --- Example ---
# sample_station = {"lat": 19.0760, "lon": 72.8777}  # Mumbai CST
# conn = psycopg2.connect(**DB_CONFIG)
# snapped = snap_to_road_node(sample_station["lat"], sample_station["lon"], conn)
# print(f"Input:   ({sample_station['lat']}, {sample_station['lon']})")
# print(f"Snapped: ({snapped['node_lat']:.6f}, {snapped['node_lon']:.6f})")
# print(f"Distance: {snapped['dist_meters']:.1f} m")
# conn.close()

# %% [markdown]
# ### 4.2 — Distance Matrix via pgRouting (Spatial-Filtered Dijkstra)
#
# **What this does:** Calculates the shortest-path cost (in seconds) between
# all pairs of nodes using Dijkstra's algorithm on the real road network,
# with a spatial bounding box filter to avoid loading all 843K roads.

# %%
def calculate_pairwise_distance(conn, node_ids: list) -> dict:
    """Calculate all-pairs shortest path cost using pgr_dijkstraCost with spatial filter."""
    cur = conn.cursor()

    # Get bounding box of nodes
    cur.execute("""
        SELECT ST_Extent(geom)
        FROM vector.main_road_nodes
        WHERE node_id = ANY(%s)
    """, (node_ids,))
    extent = cur.fetchone()[0]

    # Run Dijkstra with spatial filter (0.3 degree buffer ~33km)
    cur.execute("""
        SELECT start_vid, end_vid, agg_cost
        FROM pgr_dijkstraCost(
            format('SELECT gid AS id, source, target, COALESCE(live_cost_s, cost_s) AS cost
                    FROM vector.road_maharashtra
                    WHERE geom && ST_Expand(ST_SetSRID(%%L::box2d::geometry, 4326), 0.3)', %s),
            %s::bigint[],
            %s::bigint[],
            directed := false
        )
    """, (extent, node_ids, node_ids))

    dist_dict = {}
    for row in cur.fetchall():
        dist_dict[(int(row[0]), int(row[1]))] = float(row[2])

    cur.close()
    return dist_dict

# --- Example ---
# conn = psycopg2.connect(**DB_CONFIG)
# sample_nodes = [123456, 234567, 345678]  # Replace with real node IDs
# distances = calculate_pairwise_distance(conn, sample_nodes)
# for (a, b), cost_s in sorted(distances.items()):
#     print(f"  Node {a} → {b}: {cost_s:.0f}s ({cost_s/60:.1f} min)")
# conn.close()

# %% [markdown]
# ### 4.3 — Traffic Factor Calculation (Google Routes API)
#
# **What this does:** Queries Google Routes API to compare live travel time
# vs static (free-flow) travel time for a short probe route near a station.

# %%
import httpx
import asyncio

async def get_traffic_factor_google(lat: float, lon: float, access_token: str) -> float:
    """
    Estimate congestion factor using Google Routes API.
    Strategy: Compare duration (with traffic) vs staticDuration (free-flow).
    Factor = duration / staticDuration
    """
    ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    # Create a short probe trip (~500m north)
    body = {
        "origin": {"location": {"latLng": {"latitude": lat, "longitude": lon}}},
        "destination": {"location": {"latLng": {"latitude": lat + 0.005, "longitude": lon}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE"
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "X-Goog-FieldMask": "routes.duration,routes.staticDuration"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(ROUTES_URL, json=body, headers=headers, timeout=8)

    if response.status_code == 200:
        routes = response.json().get("routes", [])
        if routes:
            duration = float(routes[0].get("duration", "0s").rstrip("s"))
            static = float(routes[0].get("staticDuration", "0s").rstrip("s"))
            if static > 0:
                factor = round(min(max(duration / static, 0.8), 10.0), 3)
                return factor
    return 1.0

# --- Example ---
# factor = asyncio.run(get_traffic_factor_google(19.076, 72.877, "your_oauth2_token"))
# print(f"Traffic factor at Mumbai CST: {factor}x")

# %% [markdown]
# ### 4.4 — Weather Penalty Classification (IMD Thresholds)
#
# **What this does:** Classifies rainfall intensity using India Meteorological
# Department standards and returns the appropriate road penalty factor.

# %%
def classify_weather_penalty(rain_mm_per_hr: float) -> dict:
    """
    Classify rainfall and return penalty factor per IMD thresholds.
    - Light:    < 2.5 mm/hr  → 1.0x (no penalty)
    - Moderate: 2.5–7.5 mm/hr → 3.0x (roads slow)
    - Heavy:    ≥ 7.5 mm/hr  → 10.0x (waterlogging risk)
    """
    RAIN_LIGHT = 2.5
    RAIN_MODERATE = 7.5

    if rain_mm_per_hr >= RAIN_MODERATE:
        return {"severity": "heavy", "penalty_factor": 10.0,
                "description": f"Heavy Rain ({rain_mm_per_hr:.1f} mm/hr)"}
    elif rain_mm_per_hr >= RAIN_LIGHT:
        return {"severity": "moderate", "penalty_factor": 3.0,
                "description": f"Moderate Rain ({rain_mm_per_hr:.1f} mm/hr)"}
    else:
        return {"severity": "none", "penalty_factor": 1.0,
                "description": "Clear / Light"}

# --- Test ---
test_cases = [0.5, 3.2, 8.5, 15.0]
for rain in test_cases:
    result = classify_weather_penalty(rain)
    print(f"  Rain={rain:5.1f} mm/hr → {result['severity']:>8s} | "
          f"Penalty={result['penalty_factor']:4.1f}x | {result['description']}")

# %% [markdown]
# ### 4.5 — Monsoon Simulation (Deterministic Seeding)
#
# **What this does:** Simulates monsoon weather for testing by using a
# coordinate-based hash so the same station always gets the same weather.

# %%
import random

def simulate_monsoon(lat: float, lon: float) -> dict:
    """Deterministic monsoon simulation using coordinate-seeded hash."""
    seed = int(abs(lat * 10000) * abs(lon * 100)) % 100

    if seed < 15:       # ~15% heavy rain
        rain_mm = round(random.uniform(8.0, 18.0), 1)
        return {"severity": "heavy", "penalty_factor": 10.0, "rain_mm": rain_mm}
    elif seed < 40:     # ~25% moderate rain
        rain_mm = round(random.uniform(3.0, 7.0), 1)
        return {"severity": "moderate", "penalty_factor": 3.0, "rain_mm": rain_mm}
    else:               # ~60% clear
        return {"severity": "none", "penalty_factor": 1.0, "rain_mm": 0.0}

# --- Validate distribution over sample coordinates ---
heavy = moderate = clear = 0
for i in range(100):
    lat = 18.5 + (i * 0.01)
    lon = 72.5 + (i * 0.005)
    r = simulate_monsoon(lat, lon)
    if r["severity"] == "heavy": heavy += 1
    elif r["severity"] == "moderate": moderate += 1
    else: clear += 1
print(f"Distribution over 100 points: Heavy={heavy}%, Moderate={moderate}%, Clear={clear}%")

# %% [markdown]
# ### 4.6 — VRP Solver (Minimal OR-Tools Proof-of-Concept)
#
# **What this does:** Demonstrates the core OR-Tools CVRPTW formulation
# with capacity constraints, time windows, and shift limits using a
# small synthetic dataset.

# %%
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

def solve_mini_vrp():
    """Minimal VRP with 5 deliveries, 2 vehicles, capacity + time windows."""
    # Synthetic distance matrix (seconds)
    dist_matrix = [
        [0,   600,  900,  1200, 800,  1500],  # Depot
        [600,  0,    400,  700,  500,  1000],  # Station 1
        [900,  400,  0,    300,  600,  800],   # Station 2
        [1200, 700,  300,  0,    900,  500],   # Station 3
        [800,  500,  600,  900,  0,    700],   # Station 4
        [1500, 1000, 800,  500,  700,  0],     # Station 5
    ]
    demands      = [0, 20, 15, 25, 10, 30]       # kg per station
    service_times = [10, 10, 10, 10, 10, 10]       # minutes
    time_windows  = [(0, 1440), (420, 720), (420, 600), (480, 900), (420, 780), (540, 1020)]
    capacities    = [60, 50]                        # kg per vehicle
    shifts        = [(420, 1080), (480, 1020)]      # minutes from midnight

    size = len(dist_matrix)
    num_vehicles = 2

    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Time callback
    def time_cb(from_idx, to_idx):
        f, t = manager.IndexToNode(from_idx), manager.IndexToNode(to_idx)
        travel_min = max(1, round(dist_matrix[f][t] / 60)) if f != t else 0
        return travel_min + service_times[f]

    transit_cb = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(transit_cb, 120, 1500, False, 'Time')
    time_dim = routing.GetDimensionOrDie('Time')

    # Time windows
    for i in range(1, size):
        idx = manager.NodeToIndex(i)
        time_dim.CumulVar(idx).SetRange(0, 1500)
        time_dim.SetCumulVarSoftUpperBound(idx, time_windows[i][1], 100000)

    # Vehicle shifts
    for v in range(num_vehicles):
        s, e = shifts[v]
        time_dim.CumulVar(routing.Start(v)).SetRange(s, e)
        time_dim.CumulVar(routing.End(v)).SetRange(s, e + 60)

    # Capacity
    def demand_cb(idx):
        return demands[manager.IndexToNode(idx)]
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(demand_cb), 0, capacities, True, 'Cap')

    # Drop penalty
    for i in range(1, size):
        routing.AddDisjunction([manager.NodeToIndex(i)], 1_000_000_000)

    # Cost
    cost_cb = routing.RegisterTransitCallback(
        lambda f, t: dist_matrix[manager.IndexToNode(f)][manager.IndexToNode(t)])
    routing.SetArcCostEvaluatorOfAllVehicles(cost_cb)

    # Solve
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = 5

    solution = routing.SolveWithParameters(params)
    if not solution:
        print("No solution found!")
        return

    print("=== Mini VRP Solution ===")
    for v in range(num_vehicles):
        idx = routing.Start(v)
        route = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            t = solution.Min(time_dim.CumulVar(idx))
            route.append(f"S{node}@{t//60:02d}:{t%60:02d}")
            idx = solution.Value(routing.NextVar(idx))
        t_end = solution.Min(time_dim.CumulVar(idx))
        route.append(f"Depot@{t_end//60:02d}:{t_end%60:02d}")
        load = solution.Min(routing.GetDimensionOrDie('Cap').CumulVar(idx))
        print(f"  Vehicle {v+1} [{capacities[v]}kg]: {' → '.join(route)} | Load={load}kg")

solve_mini_vrp()

# %% [markdown]
# ### 4.7 — Batch Traffic Update (Spatial Join)
#
# **What this does:** Demonstrates the spatial batch join that applies
# traffic factors to road segments near multiple stations in ONE query
# instead of N individual updates.

# %%
def batch_traffic_update_sql(updates: list) -> str:
    """
    Generate the SQL for batch updating traffic factors.
    updates: List of (lat, lon, factor, radius_km)
    Returns the SQL string (for review, not execution).
    """
    sql = """
    -- 1. Create temp table with update points
    CREATE TEMP TABLE _tmp_traffic_updates (
        lat DOUBLE PRECISION, lon DOUBLE PRECISION,
        factor REAL, radius_deg DOUBLE PRECISION
    );

    -- 2. Insert all points (radius_km * 0.01 ≈ degrees at ~19°N)
    INSERT INTO _tmp_traffic_updates VALUES
    """
    values = []
    for lat, lon, factor, radius_km in updates:
        values.append(f"    ({lat}, {lon}, {factor}, {radius_km * 0.01})")
    sql += ",\n".join(values) + ";\n\n"

    sql += """
    -- 3. Add geometry column + spatial index
    ALTER TABLE _tmp_traffic_updates ADD COLUMN geom geometry(Point, 4326);
    UPDATE _tmp_traffic_updates SET geom = ST_SetSRID(ST_Point(lon, lat), 4326);
    CREATE INDEX ON _tmp_traffic_updates USING GIST (geom);

    -- 4. Single spatial join: update roads near ANY traffic point
    UPDATE vector.road_maharashtra r
    SET traffic_factor = t.max_factor,
        live_cost_s = r.cost_s * t.max_factor
    FROM (
        SELECT r2.gid, MAX(u.factor) as max_factor
        FROM vector.road_maharashtra r2
        JOIN _tmp_traffic_updates u ON r2.geom && ST_Expand(u.geom, u.radius_deg)
        GROUP BY r2.gid
    ) t
    WHERE r.gid = t.gid;
    """
    return sql

# --- Example ---
sample_updates = [
    (19.076, 72.877, 1.8, 1.5),  # Mumbai CST - moderate congestion
    (19.120, 72.850, 3.2, 2.0),  # Andheri - heavy congestion
    (19.000, 72.840, 1.0, 1.5),  # Colaba - free flow
]
print(batch_traffic_update_sql(sample_updates))

# %% [markdown]
# ### 4.8 — Route Geometry as GeoJSON
#
# **What this does:** Demonstrates converting route geometries from PostGIS
# into GeoJSON features with traffic-colored properties.

# %%
import json

def traffic_factor_to_color(factor: float) -> str:
    """Map traffic factor to hex color for visualization."""
    if factor >= 2.0:  return "#DC2626"   # Red - heavy
    if factor >= 1.5:  return "#F97316"   # Orange - moderate
    if factor >= 1.1:  return "#EAB308"   # Yellow - light
    return "#22C55E"                       # Green - free flow

# Simulated segment data
segments = [
    {"vehicle_id": 1, "segment_index": 0, "traffic_factor": 1.0},
    {"vehicle_id": 1, "segment_index": 1, "traffic_factor": 1.3},
    {"vehicle_id": 1, "segment_index": 2, "traffic_factor": 2.1},
    {"vehicle_id": 1, "segment_index": 3, "traffic_factor": 1.7},
]

geojson = {"type": "FeatureCollection", "features": []}
for seg in segments:
    tf = seg["traffic_factor"]
    geojson["features"].append({
        "type": "Feature",
        "properties": {
            "vehicle_id": seg["vehicle_id"],
            "segment_index": seg["segment_index"],
            "traffic_factor": round(tf, 2),
            "traffic_color": traffic_factor_to_color(tf)
        },
        "geometry": {"type": "MultiLineString", "coordinates": []}  # Placeholder
    })

print(json.dumps(geojson, indent=2))

# %% [markdown]
# ---
# ## 5. Tech Handoff
#
# ---

# %% [markdown]
# # GIS Transportation & Vehicle Routing: Core Logic Requirements
#
# **Purpose:** This document outlines the pure spatial formulas, data inputs,
# optimization constraints, and API contracts required to build the Vehicle
# Routing pipeline. It is entirely agnostic of the underlying codebase.
# Developers should use these specifications as the singular source of truth.
#
# ---
#
# ### 1. System Inputs
#
# The system must accept the following core inputs to begin an optimization:
#
# - **Delivery Manifest:** CSV/Excel file with columns:
#   `id`, `latitude`, `longitude` (required); `parcel_weight` (kg, default 20),
#   `service_time` (min, default 10), `window_start` (min from midnight, default 420),
#   `window_end` (min from midnight, default 600) — all optional.
# - **Warehouse Location:** `(latitude, longitude)` — Default: Mumbai (19.0725, 72.8724)
# - **Fleet Configuration:** Array of vehicle objects, each with:
#   `name`, `capacity_kg`, `cost_per_km`, `shift_start` (min), `shift_end` (min)
# - **Road Network:** PostgreSQL database with PostGIS + pgRouting containing
#   `vector.road_maharashtra` and `vector.main_road_nodes` tables.
#
# ---
#
# ### 2. Telemetry Sources & Formulas
#
# #### 2.1 Traffic Congestion Factor
# | Source | Formula | Auth |
# |---|---|---|
# | Google Routes API | `duration / staticDuration` | OAuth2 Service Account |
# | TomTom Flow API | `freeFlowSpeed / currentSpeed` | API Key |
#
# Bounds: `[0.8, 10.0]`. Default: `1.0` (free flow).
#
# #### 2.2 Weather Severity & Road Penalty
# | Severity | Rainfall (mm/hr) | Penalty Factor |
# |---|---|---|
# | None | < 2.5 | 1.0× |
# | Moderate | 2.5 – 7.5 | 3.0× |
# | Heavy | ≥ 7.5 | 10.0× |
#
# Source: OpenWeatherMap API or deterministic simulation.
#
# #### 2.3 Road Cost Adjustment
# ```
# live_cost_s = cost_s × max(traffic_factor, weather_penalty_factor)
# ```
# Applied via spatial batch join within radius of each station.
#
# ---
#
# ### 3. Optimization Constraints
#
# | Constraint | Type | Value |
# |---|---|---|
# | Vehicle Capacity | Hard (soft penalty) | `capacity_kg` per vehicle, penalty 1M/kg |
# | Time Windows | Soft upper bound | `window_end` per parcel, penalty 100K/min |
# | Shift Duration | Soft upper bound | `shift_end` + 60min overtime, penalty 50K/min |
# | Drop Penalty | Quasi-hard | 1,000,000,000 per undelivered parcel |
# | Warehouse Loading | Fixed | 10 minutes at depot before departure |
# | Min Travel Time | Floor | 1 minute between any two different nodes |
# | Cross-Midnight | Auto-normalize | If `shift_end < shift_start`, add 1440 |
#
# ---
#
# ### 4. Default Fleet Configuration (10 Vehicles)
#
# | Vehicle | Capacity (kg) | Cost/km (₹) | Shift Start | Shift End |
# |---|---|---|---|---|
# | Vehicle 1 | 175 | 15 | 09:00 | 18:00 |
# | Vehicle 2 | 261 | 20 | 09:00 | 18:00 |
# | Vehicle 3 | 348 | 25 | 07:00 | 15:00 |
# | Vehicle 4 | 156 | 12 | 07:00 | 18:00 |
# | Vehicle 5 | 178 | 15 | 09:00 | 17:00 |
# | Vehicle 6 | 142 | 12 | 08:00 | 18:00 |
# | Vehicle 7 | 118 | 10 | 08:00 | 21:00 |
# | Vehicle 8 | 125 | 10 | 07:00 | 20:00 |
# | Vehicle 9 | 200 | 12 | 07:00 | 19:00 |
# | Vehicle 10 | 180 | 14 | 08:00 | 20:00 |
#
# ---
#
# ### 5. Geocoding Pipeline
#
# ```
# Input Address → Cache Check → Ola Maps API → Nominatim Fallback → (lat, lon)
# ```
#
# - Ola Maps: Parallel batch (5 concurrent)
# - Nominatim: Sequential (1 req/sec rate limit)
# - Cache: JSON file, keyed by raw address string
# - Validation: India bounds (6.5°–35.5°N, 68°–97.5°E)
#
# ---
#
# ### 6. Expected System Output
#
# The system must output a structured JSON response (no local file saves).
#
# #### 6.1 Route Results Payload
# ```json
# {
#   "vehicles": [
#     {
#       "vehicle_id": 1,
#       "stations": [
#         {"station_id": "P001", "arrival_time": "09:42", "status": "ON TIME"}
#       ],
#       "route_geometry": {"type": "FeatureCollection", "features": [
#         {"properties": {"vehicle_id": 1, "segment_index": 0,
#                         "traffic_factor": 1.3, "traffic_color": "#EAB308"},
#          "geometry": {"type": "MultiLineString", "coordinates": [...]}}
#       ]},
#       "total_distance": 71.88,
#       "total_cost": 1078.2,
#       "weight_carried": 174,
#       "capacity": 175,
#       "utilization": 99.4,
#       "work_duration": 143,
#       "color": "#FF6B6B",
#       "clock_in": "09:00",
#       "clock_out": "11:23"
#     }
#   ],
#   "summary": {
#     "total_distance": 676.21,
#     "total_cost": 9723.30,
#     "total_parcels": 53,
#     "total_fleets": 8
#   },
#   "undelivered_parcels": [
#     {"station_id": "P054", "reason": "Capacity/time constraints",
#      "latitude": 19.05, "longitude": 72.88, "parcel_weight": 30}
#   ],
#   "weather_alerts": [
#     {"station_id": "P012", "lat": 19.12, "lon": 72.85,
#      "rain_mm": 9.3, "severity": "heavy",
#      "description": "Heavy Rain (9.3 mm/hr)"}
#   ],
#   "rerouted_vehicles": [3, 7]
# }
# ```
#
# #### 6.2 Delivery Status Values
# | Status | Condition |
# |---|---|
# | `IN_BUFFER` | Arrival ≤ deadline − 60 min |
# | `ON TIME` | deadline − 60 < arrival ≤ deadline |
# | `LATE` | Arrival > deadline |
#
# #### 6.3 API Endpoints
# | Method | Endpoint | Purpose |
# |---|---|---|
# | POST | `/api/upload` | Upload CSV/Excel delivery data |
# | POST | `/api/compute` | Trigger route optimization |
# | GET | `/api/results` | Retrieve optimized routes |
# | POST | `/api/refresh-traffic` | Re-query traffic + regenerate routes |
# | POST | `/api/reoptimize` | Re-order stops (fixed assignments) |
# | POST | `/api/auto-reoptimize` | Toggle auto re-optimization ON/OFF |
# | GET | `/api/download-report` | Download Excel report |
#
# ---
#
# ### 7. Database Schema (Required Tables)
#
# | Table | Purpose |
# |---|---|
# | `vector.road_maharashtra` | Road network (~843K segments) with traffic columns |
# | `vector.main_road_nodes` | Pre-computed connected component nodes with GiST index |
# | `vector.station_node_map` | Uploaded delivery stations snapped to road nodes |
# | `vector.distance_matrix` | Pre-computed N×N shortest path costs |
# | `vector.route_geometries` | Per-segment route geometries with traffic factors |
# | `vector.fleet_vehicles` | Configurable fleet (capacity, cost, shifts) |
# | `vector.unassigned_parcels` | Parcels that couldn't be assigned |
#
# ---
#
# ### 8. Performance Benchmarks
#
# | Component | Target | Actual |
# |---|---|---|
# | Station Snapping (50 stations) | < 2s | ~1s |
# | Distance Matrix (50 nodes) | < 20s | ~15s |
# | VRP Solver (50 parcels, 10 vehicles) | < 15s | ~10s |
# | Route Geometry (8 routes) | < 5s | ~3s |
# | Traffic + Weather Sync | < 10s | ~5s |
# | **Total Pipeline** | **< 60s** | **~39s** |
