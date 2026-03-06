"""
Auto Route Re-optimization Module
==================================
Re-optimizes the ORDER of stops within each vehicle's route based on
fresh traffic data, WITHOUT changing which parcels are assigned to which vehicle.

Supports both OR-Tools (local TSP) and Google Route Optimization paths.
"""
import os
import asyncio
import time as _time
import httpx
from typing import Dict, Any, List

from database import (
    get_db_connection,
    get_warehouse_node,
    fetch_station_data,
    fetch_distance_matrix,
    save_all_route_geometries,
    reset_traffic_factors,
    batch_update_traffic_factors,
    get_current_route_states,
    get_fleet_vehicles,
)
from traffic_service import traffic_service


async def reoptimize_routes(
    warehouse_lon: float = 72.8724,
    warehouse_lat: float = 19.0725,
) -> Dict[str, Any]:
    """
    Re-optimize stop ordering within each vehicle, keeping parcel assignments fixed.
    
    1. Read current vehicle→parcel assignments from DB
    2. Fetch fresh traffic and update road weights
    3. Re-order stops per vehicle (TSP) using OR-Tools or Google
    4. Save updated geometries and arrival times
    5. Return rerouted vehicle list
    """
    _t0 = _time.perf_counter()
    conn = get_db_connection()

    # ── 1. Read current assignments ──
    old_states = get_current_route_states(conn)  # {vehicle_id: [station_ids]}
    if not old_states:
        conn.close()
        return {"success": False, "error": "No existing routes to re-optimize"}

    stations = fetch_station_data(conn)
    if not stations:
        conn.close()
        return {"success": False, "error": "No station data found"}

    # Build lookup: station_id → station dict
    station_map = {str(s["station_id"]): s for s in stations}

    # ── 2. Refresh traffic data ──
    tomtom_key = os.getenv("TOMTOM_API_KEY", "")
    google_maps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    google_sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

    if tomtom_key or google_maps_key or google_sa_json:
        print("🔄 [Re-optimize] Refreshing traffic data...")
        reset_traffic_factors(conn)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Only fetch traffic for stations that are assigned
            assigned_stations = [s for s in stations if str(s["station_id"]) in 
                                 {sid for sids in old_states.values() for sid in sids}]
            traffic_tasks = []
            for s in assigned_stations[:30]:
                traffic_tasks.append(
                    traffic_service.get_station_traffic_factor_async(
                        s["latitude"], s["longitude"], client
                    )
                )
            traffic_results = await asyncio.gather(*traffic_tasks, return_exceptions=True)

        all_updates = []
        for i, factor in enumerate(traffic_results):
            if isinstance(factor, Exception) or factor == 1.0:
                continue
            s = assigned_stations[i]
            all_updates.append((s["latitude"], s["longitude"], factor, 1.5))

        if all_updates:
            batch_update_traffic_factors(conn, all_updates)
            conn.commit()
            print(f"  📊 Applied {len(all_updates)} traffic updates")
    else:
        print("ℹ️ [Re-optimize] No traffic API keys — skipping traffic refresh")

    # ── 3. Decide solver ──
    use_google = os.getenv("USE_GOOGLE_OPTIMIZATION", "false").lower() in ("true", "1", "yes")

    if use_google:
        result = await _reoptimize_google(conn, old_states, station_map, warehouse_lon, warehouse_lat)
    else:
        result = await _reoptimize_ortools(conn, old_states, station_map, warehouse_lon, warehouse_lat)

    elapsed = _time.perf_counter() - _t0
    print(f"✓ [Re-optimize] Complete in {elapsed:.2f}s")

    conn.close()
    return result


async def _reoptimize_ortools(
    conn, old_states, station_map, warehouse_lon, warehouse_lat
) -> Dict[str, Any]:
    """Re-order stops within each vehicle using OR-Tools TSP."""
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp

    depot_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    if not depot_node:
        return {"success": False, "error": "Could not find warehouse node"}

    fleet = get_fleet_vehicles(conn)
    fleet_map = {v["id"]: v for v in fleet}

    rerouted_vehicles = []
    all_routes_data = []
    cur = conn.cursor()

    # Prepare results tables
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS vehicle_id integer;")
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS arrival_time text;")
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS delivery_status text;")

    def min_to_clock(minutes):
        hours = int(minutes) // 60
        mins = int(minutes) % 60
        if hours >= 24:
            return f"{hours - 24:02d}:{mins:02d} (+1 Day)"
        return f"{hours:02d}:{mins:02d}"

    for v_id, station_ids in old_states.items():
        if len(station_ids) < 2:
            # Only 1 stop — no reordering possible, just regenerate geometry
            if len(station_ids) == 1:
                s = station_map.get(str(station_ids[0]))
                if s and s.get("nearest_node_id"):
                    all_routes_data.append({
                        "vehicle_id": v_id,
                        "route_nodes": [depot_node, s["nearest_node_id"], depot_node]
                    })
            continue

        # Build nodes for this vehicle's stops
        vehicle_stations = []
        for sid in station_ids:
            s = station_map.get(str(sid))
            if s and s.get("nearest_node_id"):
                vehicle_stations.append(s)

        if len(vehicle_stations) < 2:
            continue

        # Build mini distance matrix: depot + vehicle_stations
        nodes_in_system = [depot_node] + [s["nearest_node_id"] for s in vehicle_stations]
        size = len(nodes_in_system)

        unique_nodes = list(set(nodes_in_system))
        dist_dict = fetch_distance_matrix(conn, unique_nodes)

        dist_matrix = [[1000000] * size for _ in range(size)]
        for i in range(size):
            dist_matrix[i][i] = 0
        for i in range(size):
            for j in range(size):
                if i == j:
                    continue
                ni, nj = nodes_in_system[i], nodes_in_system[j]
                if ni == nj:
                    dist_matrix[i][j] = 0
                elif (ni, nj) in dist_dict:
                    dist_matrix[i][j] = int(float(dist_dict[(ni, nj)]))

        # Solve TSP for this vehicle (single vehicle, all stops)
        manager = pywrapcp.RoutingIndexManager(size, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def time_callback(from_idx, to_idx):
            f = manager.IndexToNode(from_idx)
            t = manager.IndexToNode(to_idx)
            return dist_matrix[f][t] // 60  # seconds → minutes

        transit_cb = routing.RegisterTransitCallback(time_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

        # Vehicle shift constraints
        v_config = fleet_map.get(v_id)
        if v_config:
            shift_start = v_config["shift_start"]
            shift_end = v_config["shift_end"]
            if shift_end < shift_start:
                shift_end += 1440
            max_time = shift_end - shift_start + 120  # allow overtime buffer
        else:
            max_time = 1440

        routing.AddDimension(transit_cb, 60, max_time, True, "Time")

        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_params.time_limit.seconds = 3

        solution = routing.SolveWithParameters(search_params)

        if not solution:
            print(f"  ⚠️ [Re-optimize] OR-Tools could not solve TSP for Vehicle {v_id}, keeping current order")
            # Keep existing order — just regenerate geometry
            route_nodes = [depot_node]
            for s in vehicle_stations:
                route_nodes.append(s["nearest_node_id"])
            route_nodes.append(depot_node)
            all_routes_data.append({"vehicle_id": v_id, "route_nodes": route_nodes})
            continue

        # Extract new order
        new_order = []
        route_nodes = [depot_node]
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node_idx = manager.IndexToNode(index)
            if node_idx > 0:  # skip depot
                new_order.append(str(vehicle_stations[node_idx - 1]["station_id"]))
                route_nodes.append(nodes_in_system[node_idx])
            index = solution.Value(routing.NextVar(index))
        route_nodes.append(depot_node)

        all_routes_data.append({"vehicle_id": v_id, "route_nodes": route_nodes})

        # Check if order changed
        old_order = [str(sid) for sid in station_ids]
        if new_order != old_order:
            rerouted_vehicles.append(v_id)
            print(f"  🔄 Vehicle {v_id}: {old_order} → {new_order}")

        # Update arrival times in DB
        v_config = fleet_map.get(v_id)
        start_min = v_config["shift_start"] if v_config else 420
        cumulative_min = start_min

        for i, sid in enumerate(new_order):
            s = station_map.get(sid)
            if not s:
                continue
            # Estimate travel time from distance matrix
            if i == 0:
                from_node = depot_node
            else:
                prev_s = station_map.get(new_order[i - 1])
                from_node = prev_s["nearest_node_id"] if prev_s else depot_node

            to_node = s["nearest_node_id"]
            travel_s = dist_dict.get((from_node, to_node), 0)
            cumulative_min += int(float(travel_s)) // 60 + s.get("service_time", 10)

            deadline = s.get("window_end", 1440)
            if cumulative_min <= (deadline - 60):
                status = "IN_BUFFER"
            elif cumulative_min <= deadline:
                status = "ON TIME"
            else:
                status = "LATE"

            cur.execute("""
                UPDATE vector.station_node_map 
                SET arrival_time = %s, delivery_status = %s
                WHERE station_id = %s
            """, (min_to_clock(cumulative_min), status, sid))

    # ── Save geometries ──
    if all_routes_data:
        print(f"🛤️ [Re-optimize] Generating road geometries for {len(all_routes_data)} routes...")
        save_all_route_geometries(conn, all_routes_data)

    conn.commit()
    cur.close()

    return {
        "success": True,
        "rerouted_vehicles": rerouted_vehicles,
        "total_reoptimized": len(old_states),
    }


async def _reoptimize_google(
    conn, old_states, station_map, warehouse_lon, warehouse_lat
) -> Dict[str, Any]:
    """Re-order stops within each vehicle using Google Route Optimization."""
    from google_solver import solve_google_vrp
    from database import save_all_route_geometries

    fleet = get_fleet_vehicles(conn)
    depot_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)

    rerouted_vehicles = []
    all_routes_data = []
    cur = conn.cursor()

    # For Google, we solve one vehicle at a time with its fixed set of parcels
    for v_id, station_ids in old_states.items():
        vehicle_stations = []
        for sid in station_ids:
            s = station_map.get(str(sid))
            if s:
                vehicle_stations.append({
                    "station_id": s["station_id"],
                    "latitude": s["latitude"],
                    "longitude": s["longitude"],
                    "parcel_weight": s["parcel_weight"],
                    "service_time": s.get("service_time", 10),
                    "window_start": s.get("window_start", 0),
                    "window_end": s.get("window_end", 1440),
                })

        if len(vehicle_stations) < 2:
            # Single stop — just regenerate geometry
            if vehicle_stations:
                s = station_map.get(str(station_ids[0]))
                if s and s.get("nearest_node_id") and depot_node:
                    all_routes_data.append({
                        "vehicle_id": v_id,
                        "route_nodes": [depot_node, s["nearest_node_id"], depot_node]
                    })
            continue

        # Call Google with SINGLE vehicle + its parcels
        # Get the fleet config for this vehicle
        v_config = fleet[v_id - 1] if v_id <= len(fleet) else fleet[0]

        google_result = await solve_google_vrp(
            vehicle_stations, [v_config], warehouse_lon, warehouse_lat
        )

        if not google_result.get("success"):
            print(f"  ⚠️ [Re-optimize] Google failed for Vehicle {v_id}: {google_result.get('error')}")
            continue

        # Extract new order from Google result
        for route in google_result.get("routes", []):
            new_order = [str(stop["station_id"]) for stop in route.get("stops", [])]
            old_order = [str(sid) for sid in station_ids]

            if new_order != old_order:
                rerouted_vehicles.append(v_id)
                print(f"  🔄 Vehicle {v_id}: {old_order} → {new_order}")

            # Build route nodes for geometry
            station_to_node = {str(s["station_id"]): s["nearest_node_id"]
                               for s in [station_map.get(str(sid)) for sid in station_ids]
                               if s and s.get("nearest_node_id")}

            route_nodes = [depot_node]
            for stop in route.get("stops", []):
                node_id = station_to_node.get(str(stop["station_id"]))
                if node_id:
                    route_nodes.append(node_id)
            route_nodes.append(depot_node)

            all_routes_data.append({"vehicle_id": v_id, "route_nodes": route_nodes})

            # Update arrival times in DB
            for stop in route.get("stops", []):
                cur.execute("""
                    UPDATE vector.station_node_map 
                    SET arrival_time = %s, delivery_status = %s
                    WHERE station_id = %s
                """, (stop["arrival_time"], stop["status"], stop["station_id"]))

    # ── Save geometries ──
    if all_routes_data:
        print(f"🛤️ [Re-optimize] Generating road geometries for {len(all_routes_data)} routes...")
        save_all_route_geometries(conn, all_routes_data)

    conn.commit()
    cur.close()

    return {
        "success": True,
        "rerouted_vehicles": rerouted_vehicles,
        "total_reoptimized": len(old_states),
    }
