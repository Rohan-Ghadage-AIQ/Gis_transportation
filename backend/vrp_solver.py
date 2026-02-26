import os
from typing import Dict, Any, List
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from traffic_service import traffic_service
from weather_service import weather_service
from database import (
    get_db_connection,
    get_warehouse_node,
    fetch_station_data,
    fetch_distance_matrix,
    save_route_geometry,
    update_road_traffic_factor,
    batch_update_traffic_factors,
    reset_traffic_factors,
    get_current_route_states
)


async def solve_vrp(warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725) -> Dict[str, Any]:
    """
    Solve the Vehicle Routing Problem with time windows and capacity constraints.
    Returns a dictionary with solution details including routes, costs, and statistics.
    Includes 'rerouted_vehicles' if traffic caused changes.
    """
    import asyncio
    import httpx
    import time as _time
    _t_total = _time.perf_counter()
    conn = get_db_connection()
    # 0. Capture current state for delta detection
    old_states = get_current_route_states(conn)
    
    cur = conn.cursor()
    
    # Fetch station data
    stations = fetch_station_data(conn)
    
    if not stations:
        conn.close()
        return {"success": False, "error": "No station data found"}
    
    # --- PARALLEL TRAFFIC & WEATHER UPDATE ---
    tomtom_key = os.getenv("TOMTOM_API_KEY", "")
    owm_key = os.getenv("OPENWEATHER_API_KEY", "")
    google_maps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    google_sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    weather_alerts = []
    
    # Run sync if ANY api source is available (traffic or weather)
    if tomtom_key or owm_key or google_maps_key or google_sa_json:
        _t_sync = _time.perf_counter()
        print(f"🚦 Syncing live data for {len(stations)} stations...")
        reset_traffic_factors(conn)
        print(f"  ⏱ Traffic reset: {_time.perf_counter() - _t_sync:.2f}s")
        
        _t_api = _time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Prepare traffic tasks (limit to first 30 to avoid excessive API costs/limits)
            traffic_tasks = []
            
            if tomtom_key or google_maps_key or google_sa_json:
                for s in stations[:30]:
                    traffic_tasks.append(traffic_service.get_station_traffic_factor_async(
                        s['latitude'], s['longitude'], client
                    ))
            
            # 2. Prepare weather tasks
            # Runs when OWM key is present (real data) OR simulation is enabled
            weather_tasks = []
            simulate_rain = os.getenv("WEATHER_SIMULATE_RAIN", "").lower() in ("true", "1", "yes")
            if owm_key or simulate_rain:
                for s in stations:
                    weather_tasks.append(weather_service.get_weather_async(
                        s['latitude'], s['longitude'], client
                    ))
            
            # Run all in parallel
            traffic_results = await asyncio.gather(*traffic_tasks, return_exceptions=True) if traffic_tasks else []
            weather_results = await asyncio.gather(*weather_tasks, return_exceptions=True) if weather_tasks else []
        print(f"  ⏱ API fetch: {_time.perf_counter() - _t_api:.2f}s")
        
        _t_apply = _time.perf_counter()
        # 3. Collect ALL traffic & weather updates into ONE batch
        all_updates = []
        
        for i, factor in enumerate(traffic_results):
            if isinstance(factor, Exception):
                continue
            if factor != 1.0:
                s = stations[i]
                all_updates.append((s['latitude'], s['longitude'], factor, 1.5))
        
        for i, weather in enumerate(weather_results):
            if isinstance(weather, Exception):
                continue
            if weather["severity"] != "none":
                s = stations[i]
                all_updates.append((s['latitude'], s['longitude'], weather["penalty_factor"], 2.0))
                
                weather_alerts.append({
                    "station_id": str(s['station_id']),
                    "lat": s['latitude'], "lon": s['longitude'],
                    "rain_mm": weather["rain_mm"], "description": weather["description"],
                    "severity": weather["severity"], "temp_c": weather["temp_c"],
                    "humidity": weather["humidity"]
                })
        
        # ONE single batch DB update instead of 86 individual calls
        traffic_updates = sum(1 for i, f in enumerate(traffic_results) if not isinstance(f, Exception) and f != 1.0)
        weather_updates = len(all_updates) - traffic_updates
        print(f"  📊 Applying {len(all_updates)} updates ({traffic_updates} traffic, {weather_updates} weather) in 1 batch...")
        batch_update_traffic_factors(conn, all_updates)
        conn.commit()
        
        # Verify updates were applied
        cur_check = conn.cursor()
        cur_check.execute("SELECT COUNT(*) FROM vector.road_maharashtra WHERE traffic_factor > 1.0")
        affected_roads = cur_check.fetchone()[0]
        cur_check.close()
        print(f"  🔍 Roads with traffic_factor > 1.0: {affected_roads}")
        
        print(f"  ⏱ DB apply: {_time.perf_counter() - _t_apply:.2f}s")
        print(f"✓ Parallel sync complete: {len(traffic_results)} traffic, {len(weather_results)} weather (total {_time.perf_counter() - _t_sync:.2f}s).")
    else:
        print("ℹ️ API keys missing — skipping live data sync.")
    # ---------------------------

    # --- GOOGLE OPTIMIZATION TOGGLE ---
    use_google = os.getenv("USE_GOOGLE_OPTIMIZATION", "false").lower() in ("true", "1", "yes")
    
    if use_google:
        from google_solver import solve_google_vrp
        from database import get_fleet_vehicles
        
        print("\n🚀 Using GOOGLE ROUTE OPTIMIZATION...")
        fleet = get_fleet_vehicles(conn)
        
        # We need to map stations to a list with lat/lon for the Google solver
        google_stations = []
        for s in stations:
            google_stations.append({
                "station_id": s["station_id"],
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "parcel_weight": s["parcel_weight"],
                "service_time": s["service_time"],
                "window_start": s["window_start"],
                "window_end": s["window_end"]
            })
            
        google_result = await solve_google_vrp(
            google_stations,
            fleet,
            warehouse_lon,
            warehouse_lat
        )
        
        if google_result.get("success"):
            # Update result with weather/traffic info
            google_result["weather_alerts"] = weather_alerts
            google_result["weather_rerouted"] = len(weather_alerts) > 0
            google_result["rerouted_vehicles"] = []
            
            # --- Post-processing: Generate route geometries for map display ---
            from database import save_all_route_geometries
            import time as _time
            _t_geom = _time.perf_counter()
            
            # Build station_id -> node_id mapping (handle type: Google labels are strings)
            station_to_node = {}
            for s in stations:
                station_to_node[str(s["station_id"])] = s["nearest_node_id"]
            
            depot_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
            
            # Collect ALL route geometries for batch save
            all_routes_data = []
            cur = conn.cursor()
            
            # RESET all station assignments first (clear stale data from previous runs)
            cur.execute("UPDATE vector.station_node_map SET vehicle_id = NULL, arrival_time = NULL, delivery_status = NULL")
            
            for route in google_result["routes"]:
                route_nodes = [depot_node]
                for stop in route["stops"]:
                    sid = str(stop["station_id"])
                    node_id = station_to_node.get(sid)
                    if node_id:
                        route_nodes.append(node_id)
                    else:
                        print(f"  ⚠️ No node found for station_id={sid}")
                route_nodes.append(depot_node)
                
                all_routes_data.append({
                    "vehicle_id": route["vehicle_id"],
                    "route_nodes": route_nodes
                })
                
                # Update station_node_map for visualization
                for stop in route["stops"]:
                    cur.execute("""
                        UPDATE vector.station_node_map 
                        SET vehicle_id = %s, arrival_time = %s, delivery_status = %s
                        WHERE station_id = %s
                    """, (route["vehicle_id"], stop["arrival_time"], stop["status"], stop["station_id"]))
            
            # Single batch call to save ALL route geometries (avoids TRUNCATE per route)
            print(f"🛤️ Generating road geometries for {len(all_routes_data)} Google routes...")
            save_all_route_geometries(conn, all_routes_data)
            print(f"✓ Geometries generated (took {_time.perf_counter() - _t_geom:.2f}s)")
            
            conn.commit()
            conn.close()
            return google_result
        else:
            print(f"❌ Google Optimization failed: {google_result.get('error')}. Falling back to OR-Tools.")
    
    # ---------------------------


    # Get depot (warehouse) node
    depot_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    
    if not depot_node:
        conn.close()
        return {"success": False, "error": "Could not find warehouse node"}
    
    # Build node mappings
    # Warehouse loading time: vehicles spend 10 minutes at depot loading parcels
    WAREHOUSE_LOADING_MINUTES = 10
    nodes_in_system = [depot_node] + [s['nearest_node_id'] for s in stations]
    node_demands = [0] + [s['parcel_weight'] for s in stations]
    station_ids = [None] + [s['station_id'] for s in stations]
    node_service_times = [WAREHOUSE_LOADING_MINUTES] + [s['service_time'] for s in stations]
    node_windows = [(0, 1440)] + [(s['window_start'], s['window_end']) for s in stations]
    
    # CRITICAL VALIDATION: Ensure no NULL nodes in system
    if None in nodes_in_system:
        null_indices = [i for i, node in enumerate(nodes_in_system) if node is None]
        null_stations = [station_ids[i] for i in null_indices if i > 0]
        raise ValueError(
            f"CRITICAL ERROR: {len(null_indices)} parcels have NULL nearest_node_id!\n"
            f"Stations: {null_stations[:5]}...\n"
            f"These parcels could not be snapped to the road network. Check database."
        )
    
    size = len(nodes_in_system)
    
    # Fetch distance matrix (keyed by road node IDs)
    unique_nodes = list(set(nodes_in_system))
    dist_dict = fetch_distance_matrix(conn, unique_nodes)
    
    # Build 2D distance matrix by STATION INDEX (not road node)
    # This correctly handles multiple stations sharing the same road node
    dist_matrix = [[1000000] * size for _ in range(size)]
    for i in range(size):
        dist_matrix[i][i] = 0
    for i in range(size):
        for j in range(size):
            if i == j:
                continue
            road_node_i = nodes_in_system[i]
            road_node_j = nodes_in_system[j]
            if road_node_i == road_node_j:
                dist_matrix[i][j] = 0
            elif (road_node_i, road_node_j) in dist_dict:
                dist_matrix[i][j] = int(float(dist_dict[(road_node_i, road_node_j)]))
    
    # idx_to_node mapping (for route geometry saving)
    idx_to_node = {i: nodes_in_system[i] for i in range(size)}
    
    # Vehicle configuration — read from database (user-configurable fleet)
    from database import get_fleet_vehicles
    fleet = get_fleet_vehicles(conn)
    num_vehicles = len(fleet)
    vehicle_capacities = [v['capacity_kg'] for v in fleet]
    vehicle_costs_per_km = [float(v['cost_per_km']) for v in fleet]
    
    # Normalize vehicle shifts (handle cross-midnight cases)
    vehicle_times = []
    for v in fleet:
        start = v['shift_start']
        end = v['shift_end']
        # If end is numerically smaller than start, it means the shift crosses midnight
        # e.g. 20:00 (1200) to 01:00 (60). Next day 01:00 is 1440+60=1500.
        if end < start:
            end += 1440
        vehicle_times.append((start, end))
    
    # Create routing model
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    
    # Time callback
    def time_callback(from_idx, to_idx):
        from_node = manager.IndexToNode(from_idx)
        to_node = manager.IndexToNode(to_idx)
        # dist_matrix values are in SECONDS (from pgRouting cost_s column)
        travel_time = dist_matrix[from_node][to_node] / 60  # seconds → minutes
        # Use round() instead of int() to avoid truncating short trips to 0.
        # Enforce minimum 1 minute travel between any two DIFFERENT nodes.
        if from_node != to_node:
            travel_minutes = max(1, round(travel_time))
        else:
            travel_minutes = 0
        return travel_minutes + node_service_times[from_node]
    
    time_callback_index = routing.RegisterTransitCallback(time_callback)
    
    # Time dimension - absolute max must cover ALL time values (windows + shifts + overtime)
    # We use normalized vehicle_times to ensure shifts spanning midnight are included
    max_vehicle_end = max(end for _, end in vehicle_times) if vehicle_times else 1440
    max_window_end = max(w[1] for w in node_windows) if node_windows else 1440
    max_vehicle_start = max(start for start, _ in vehicle_times) if vehicle_times else 0
    
    absolute_max = max(max_vehicle_end + 120, max_window_end, max_vehicle_start) + 60
    routing.AddDimension(
        time_callback_index,
        120,           # slack — allow waiting up to 2 hours
        absolute_max,  # Absolute max across all time values
        False,
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')
    
    # Apply time windows
    # Parcel deadlines are SOFT constraints — late delivery preferred over dropping
    for i in range(1, size):
        index = manager.NodeToIndex(i)
        ws, deadline = node_windows[i]
        # Hard range: allow delivery anytime within the overall shift window
        time_dimension.CumulVar(index).SetRange(0, absolute_max)
        # Soft penalty: strongly prefer delivery before the parcel's deadline
        time_dimension.SetCumulVarSoftUpperBound(index, deadline, 100000)
    
    # Vehicle-specific time constraints
    for v in range(num_vehicles):
        start_avail, end_avail = vehicle_times[v]
        # (Normalization already handled above)
        
        start_index = routing.Start(v)
        # Hard: vehicle starts within its shift window (allow some flexibility)
        time_dimension.CumulVar(start_index).SetRange(start_avail, end_avail)
        end_index = routing.End(v)
        # Hard: vehicle must return by shift end + 60 min overtime buffer
        overtime_limit = min(end_avail + 60, absolute_max)
        # Safety: ensure lower bound <= upper bound for SetRange
        overtime_limit = max(overtime_limit, start_avail)
        time_dimension.CumulVar(end_index).SetRange(start_avail, overtime_limit)
        # Soft: penalize going past actual shift end
        time_dimension.SetCumulVarSoftUpperBound(end_index, end_avail, 50000)
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(start_index))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(end_index))
        # Low fixed cost to encourage using ALL vehicles
        routing.SetFixedCostOfVehicle(2000, v)
    
    # EXTREMELY HIGH penalty for dropping parcels — effectively infinite
    for i in range(1, size):
        routing.AddDisjunction([manager.NodeToIndex(i)], 1000000000)
    
    # Cost callback per vehicle
    def create_cost_callback(v_idx):
        def cost_callback(from_idx, to_idx):
            from_node = manager.IndexToNode(from_idx)
            to_node = manager.IndexToNode(to_idx)
            distance_meters = dist_matrix[from_node][to_node]
            cost_per_meter = (vehicle_costs_per_km[v_idx] / 1000.0)
            return int(distance_meters * cost_per_meter * 100)
        return cost_callback
    
    for v_id in range(num_vehicles):
        cost_cb = create_cost_callback(v_id)
        cost_cb_index = routing.RegisterTransitCallback(cost_cb)
        routing.SetArcCostEvaluatorOfVehicle(cost_cb_index, v_id)
    
    # Demand callback
    def demand_cb(from_idx):
        return node_demands[manager.IndexToNode(from_idx)]
    
    # Capacity dimension - slightly relaxed hard limit to ensure assignment
    # but with heavy soft penalty after actual capacity
    relaxed_capacities = [max(500, c * 2) for c in vehicle_capacities]
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(demand_cb),
        0,
        relaxed_capacities,
        True,
        'Capacity'
    )
    
    capacity_dimension = routing.GetDimensionOrDie('Capacity')
    for i in range(num_vehicles):
        index = routing.End(i)
        # Heavy penalty for exceeding original capacity
        capacity_dimension.SetCumulVarSoftUpperBound(index, vehicle_capacities[i], 1000000)
    
    # Solve with optimized parameters
    print(f"  ⏱ Model setup: {_time.perf_counter() - _t_total:.2f}s")
    _t_solver = _time.perf_counter()
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 10
    search_params.log_search = False
    
    solution = routing.SolveWithParameters(search_params)
    print(f"  ⏱ Solver: {_time.perf_counter() - _t_solver:.2f}s")
    
    if not solution:
        conn.close()
        return {"success": False, "error": "Solver could not find a solution"}
    
    # Helper function for time formatting
    def min_to_clock(minutes):
        """Convert minutes from midnight to 24-hour HH:MM format"""
        hours = int(minutes) // 60
        mins = int(minutes) % 60
        if hours >= 24:
            return f"{hours - 24:02d}:{mins:02d} (+1 Day)"
        return f"{hours:02d}:{mins:02d}"
    
    # Prepare results tables
    cur.execute("CREATE TABLE IF NOT EXISTS vector.route_geometries (vehicle_id integer, geom geometry);")
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS vehicle_id integer;")
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS arrival_time text;")
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS delivery_status text;")
    cur.execute("UPDATE vector.station_node_map SET vehicle_id = NULL, arrival_time = NULL, delivery_status = NULL;")
    
    routes = []
    
    for v_id in range(num_vehicles):
        index = routing.Start(v_id)
        if routing.IsEnd(solution.Value(routing.NextVar(index))):
            continue
        
        route_nodes = []
        route_stops = []
        start_min = solution.Min(time_dimension.CumulVar(index))
        
        while not routing.IsEnd(index):
            node_idx = manager.IndexToNode(index)
            node_id = idx_to_node[node_idx]
            route_nodes.append(node_id)
            
            deadline = node_windows[node_idx][1]
            arrival_min = solution.Min(time_dimension.CumulVar(index))
            
            if arrival_min <= (deadline - 60):
                status = "IN_BUFFER"
            elif arrival_min <= deadline:
                status = "ON TIME"
            else:
                status = "LATE"
            
            if node_id != depot_node:
                route_stops.append({
                    "station_id": station_ids[node_idx],
                    "arrival_time": min_to_clock(arrival_min),
                    "status": status
                })
                
                cur.execute("""
                    UPDATE vector.station_node_map 
                    SET vehicle_id = %s,
                        arrival_time = %s,
                        delivery_status = %s
                    WHERE station_id = %s
                """, (v_id + 1, min_to_clock(arrival_min), status, station_ids[node_idx]))
            
            index = solution.Value(routing.NextVar(index))
        
        # Return to depot
        time_var = time_dimension.CumulVar(index)
        return_min = solution.Min(time_var)
        
        total_weight = solution.Min(capacity_dimension.CumulVar(index))
        max_cap = vehicle_capacities[v_id]
        utilization = (total_weight / max_cap) * 100
        
        actual_work_time = return_min - start_min
        _, end_avail = vehicle_times[v_id]
        overtime = max(0, return_min - end_avail)
        
        route_nodes.append(depot_node)
        
        routes.append({
            "vehicle_id": v_id + 1,
            "route_nodes": route_nodes, # Keep for batch geometry
            "stops": route_stops,
            "start_time": min_to_clock(start_min),
            "end_time": min_to_clock(return_min),
            "total_weight": total_weight,
            "max_cap": max_cap,
            "utilization": round(utilization, 1),
            "work_duration_mins": actual_work_time,
            "overtime_mins": overtime
        })
    
    # --- Step 5: Batch Save Geometries ---
    from database import save_all_route_geometries
    _t_post = _time.perf_counter()
    print(f"🛤️ Generating road geometries for {len(routes)} routes...")
    _t_geom = _time.perf_counter()
    save_all_route_geometries(conn, [{"vehicle_id": r["vehicle_id"], "route_nodes": r["route_nodes"]} for r in routes])
    print(f"✓ Geometries generated (took {_time.perf_counter() - _t_geom:.2f}s)")

    for route in routes:
        v_id = route["vehicle_id"]
        # Calculate route distance from saved geometry (real road km)
        cur.execute("""
            SELECT COALESCE(SUM(ST_Length(geom::geography)) / 1000.0, 0)
            FROM vector.route_geometries WHERE vehicle_id = %s
        """, (v_id,))
        route_distance_km = float(cur.fetchone()[0])
        
        # vehicle_costs_per_km is indexed by v_id-1
        cost_per_km = vehicle_costs_per_km[v_id - 1]
        op_cost = route_distance_km * cost_per_km
        
        route["distance_km"] = round(route_distance_km, 2)
        route["cost"] = round(op_cost, 2)
        # Clean up internal data before returning
        del route["route_nodes"]
        
        # Print for log visibility
        v_start_clock = route["start_time"]
        v_end = vehicle_times[v_id - 1][1]
        v_end_clock = min_to_clock(v_end)
        for stop in route["stops"]:
            print(f"  ✅ V{v_id} [{v_start_clock}-{v_end_clock}] → "
                  f"Parcel {stop['station_id']} arrives {stop['arrival_time']} ({stop['status']})")
    print(f"  ⏱ Post-processing: {_time.perf_counter() - _t_post:.2f}s")
    print(f"  ⏱ TOTAL solve_vrp: {_time.perf_counter() - _t_total:.2f}s")

    conn.commit()
    
    # ========================================
    # RECORD UNASSIGNED PARCELS
    # ========================================
    cur.execute("""
        INSERT INTO vector.unassigned_parcels (station_id, reason, latitude, longitude, parcel_weight, window_end)
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
    unassigned_count = cur.rowcount
    if unassigned_count > 0:
        print(f"\n⚠️  WARNING: {unassigned_count} parcels could not be assigned to any vehicle!")
    conn.commit()
    
    cur.close()
    conn.close()
    
    # --- REROUTE DETECTION ---
    rerouted_vehicles = []
    reroute_reason = "traffic"
    if len(weather_alerts) > 0:
        reroute_reason = "weather"
    
    for route in routes:
        v_id = int(route["vehicle_id"])
        new_seq = [stop["station_id"] for stop in route["stops"]]
        old_seq = old_states.get(v_id, [])
        
        if old_seq and new_seq != old_seq:
            rerouted_vehicles.append(v_id)
            if reroute_reason == "weather":
                print(f"⛈️  Vehicle {v_id} REROUTED due to weather conditions.")
            else:
                print(f"🔄 Vehicle {v_id} REROUTED due to updated traffic conditions.")

    return {
        "success": True,
        "routes": routes,
        "total_vehicles_used": len(routes),
        "total_deliveries": sum(len(r['stops']) for r in routes),
        "rerouted_vehicles": rerouted_vehicles,
        "weather_alerts": weather_alerts,
        "weather_rerouted": len(weather_alerts) > 0 and len(rerouted_vehicles) > 0,
    }
