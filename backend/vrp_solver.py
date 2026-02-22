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
    reset_traffic_factors,
    get_current_route_states
)


def solve_vrp(warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725) -> Dict[str, Any]:
    """
    Solve the Vehicle Routing Problem with time windows and capacity constraints.
    Returns a dictionary with solution details including routes, costs, and statistics.
    Includes 'rerouted_vehicles' if traffic caused changes.
    """
    conn = get_db_connection()
    # 0. Capture current state for delta detection
    old_states = get_current_route_states(conn)
    
    cur = conn.cursor()
    
    # Fetch station data
    stations = fetch_station_data(conn)
    
    if not stations:
        conn.close()
        return {"success": False, "error": "No station data found"}
    
    # --- LIVE TRAFFIC UPDATE via TomTom ---
    tomtom_key = os.getenv("TOMTOM_API_KEY", "")
    if tomtom_key:
        # Reset all traffic factors to 1.0 before fresh sync
        reset_traffic_factors(conn)
        print("🚦 Syncing live traffic from TomTom...")
        print("   ┌─────────┬──────────────────────┬─────────┬──────────────────┐")
        print("   │ Station │ Location             │ Factor  │ Status           │")
        print("   ├─────────┼──────────────────────┼─────────┼──────────────────┤")
        tried = 0
        updated = 0
        try:
            # Sample up to 15 stations to stay within API limits
            for s in stations[:15]:
                tried += 1
                factor = traffic_service.get_station_traffic_factor(
                    s['latitude'], s['longitude']
                )
                if factor != 1.0:
                    update_road_traffic_factor(
                        conn, s['latitude'], s['longitude'], factor, radius_km=1.5
                    )
                    updated += 1
                    # Show severity
                    if factor >= 2.0:
                        severity = "🔴 HEAVY"
                    elif factor >= 1.5:
                        severity = "🟠 MODERATE"
                    elif factor >= 1.2:
                        severity = "🟡 LIGHT"
                    else:
                        severity = "🟢 FREE FLOW"
                    print(f"   │ {s['station_id']:>7} │ {s['latitude']:>9.4f},{s['longitude']:>9.4f} │ {factor:>6.2f}x │ {severity:<16} │")
                else:
                    print(f"   │ {s['station_id']:>7} │ {s['latitude']:>9.4f},{s['longitude']:>9.4f} │  1.00x │ 🟢 FREE FLOW     │")
            print("   └─────────┴──────────────────────┴─────────┴──────────────────┘")
            print(f"   ✅ Live traffic sync complete — {updated}/{tried} zones have congestion.")
        except Exception as e:
            print(f"⚠️ Traffic sync failed, using static costs: {e}")
    else:
        print("ℹ️ TOMTOM_API_KEY not set — using static road costs.")
    # ---------------------------

    # --- LIVE WEATHER CHECK via OpenWeatherMap ---
    weather_alerts = []
    owm_key = os.getenv("OPENWEATHER_API_KEY", "")
    if owm_key:
        print("\n🌦️  Checking live weather from OpenWeatherMap...")
        print("   ┌─────────┬──────────────────────┬──────────┬──────────┬──────────────────┐")
        print("   │ Station │ Location             │ Rain mm/h│ Penalty  │ Severity         │")
        print("   ├─────────┼──────────────────────┼──────────┼──────────┼──────────────────┤")
        weather_tried = 0
        weather_affected = 0
        try:
            # Check weather for all stations (OpenWeatherMap free tier: 60 calls/min)
            for s in stations[:30]:
                weather_tried += 1
                weather = weather_service.get_weather(s['latitude'], s['longitude'])

                if weather["severity"] != "none":
                    weather_affected += 1
                    # Apply weather penalty to road segments near this station
                    # This stacks with any traffic penalties already applied
                    update_road_traffic_factor(
                        conn, s['latitude'], s['longitude'],
                        weather["penalty_factor"], radius_km=2.0
                    )

                    severity_icon = "🔴 HEAVY" if weather["severity"] == "heavy" else "🟠 MODERATE"
                    print(f"   │ {s['station_id']:>7} │ {s['latitude']:>9.4f},{s['longitude']:>9.4f} │ {weather['rain_mm']:>7.1f} │ {weather['penalty_factor']:>7.1f}x │ {severity_icon:<16} │")

                    # Collect alert for frontend
                    weather_alerts.append({
                        "station_id": str(s['station_id']),
                        "lat": s['latitude'],
                        "lon": s['longitude'],
                        "rain_mm": weather["rain_mm"],
                        "description": weather["description"],
                        "severity": weather["severity"],
                        "temp_c": weather["temp_c"],
                        "humidity": weather["humidity"],
                    })
                else:
                    print(f"   │ {s['station_id']:>7} │ {s['latitude']:>9.4f},{s['longitude']:>9.4f} │     0.0 │    1.0x │ ☀️ CLEAR          │")

            print("   └─────────┴──────────────────────┴──────────┴──────────┴──────────────────┘")
            if weather_affected > 0:
                print(f"   ⛈️  Weather alert: {weather_affected}/{weather_tried} stations affected by rain!")
                print(f"   🔄 Routes will be adjusted to avoid waterlogging zones.")
            else:
                print(f"   ☀️  Weather check complete — no rainfall detected at any station.")
        except Exception as e:
            print(f"⚠️ Weather sync failed, proceeding without weather penalties: {e}")
    else:
        print("ℹ️ OPENWEATHER_API_KEY not set — skipping weather check.")
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
    
    # VERY HIGH penalty for dropping parcels — makes it virtually impossible
    for i in range(1, size):
        routing.AddDisjunction([manager.NodeToIndex(i)], 10000000)
    
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
    
    # Capacity dimension
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(demand_cb),
        0,
        vehicle_capacities,
        True,
        'Capacity'
    )
    
    capacity_dimension = routing.GetDimensionOrDie('Capacity')
    for i in range(num_vehicles):
        index = routing.End(i)
        capacity_dimension.SetCumulVarSoftUpperBound(index, 300, 500)
    
    # Solve with optimized parameters
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 60
    search_params.solution_limit = 200
    search_params.lns_time_limit.seconds = 5
    search_params.log_search = False
    
    solution = routing.SolveWithParameters(search_params)
    
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
        
        if len(route_nodes) > 2:
            save_route_geometry(conn, v_id + 1, route_nodes)
        
        # Calculate route distance from saved geometry (real road km)
        # dist_matrix contains seconds, NOT meters — so we use ST_Length instead
        cur.execute("""
            SELECT COALESCE(SUM(ST_Length(geom::geography)) / 1000.0, 0)
            FROM vector.route_geometries WHERE vehicle_id = %s
        """, (v_id + 1,))
        route_distance_km = float(cur.fetchone()[0])
        
        total_op_cost = route_distance_km * vehicle_costs_per_km[v_id]
        
        routes.append({
            "vehicle_id": v_id + 1,
            "stops": route_stops,
            "start_time": min_to_clock(start_min),
            "end_time": min_to_clock(return_min),
            "distance_km": round(route_distance_km, 2),
            "cost": round(total_op_cost, 2),
            "weight_kg": total_weight,
            "capacity_kg": max_cap,
            "utilization": round(utilization, 1),
            "work_duration_mins": actual_work_time,
            "overtime_mins": overtime
        })
    
    # ========================================
    # POST-SOLUTION VALIDATION
    # ========================================
    for route in routes:
        v_id = route["vehicle_id"]
        v_start, v_end = vehicle_times[v_id - 1]
        v_start_clock = min_to_clock(v_start)
        v_end_clock = min_to_clock(v_end)
        for stop in route["stops"]:
            arrival_str = stop["arrival_time"]
            print(f"  ✅ V{v_id} [{v_start_clock}-{v_end_clock}] → "
                  f"Parcel {stop['station_id']} arrives {arrival_str} ({stop['status']})")
    
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
