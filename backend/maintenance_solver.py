"""
Maintenance Team Planning — VRP Solver
Reuses OR-Tools / Google Route Optimization from the logistics module,
but reads from maintenance-specific tables and writes back to them.
"""
import os
import time as _time
from typing import Dict, Any, List

from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from database import (
    get_db_connection,
    get_warehouse_node,
    fetch_distance_matrix,
)
from maintenance_db import (
    fetch_maintenance_tasks,
    save_maintenance_route_geometries,
)


async def solve_maintenance_vrp(
    warehouse_lon: float,
    warehouse_lat: float,
    technicians: List[Dict[str, Any]],
    team_size: int = 3,
) -> Dict[str, Any]:
    """
    Solve the Maintenance Team Planning VRP.
    technicians: list of {"id", "name", "shift_start", "shift_end"}
    team_size: max number of technicians to use (configurable, default 3)
    """
    _t_total = _time.perf_counter()
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch tasks (same shape as station_data)
    tasks = fetch_maintenance_tasks(conn)
    if not tasks:
        conn.close()
        return {"success": False, "error": "No maintenance tasks found"}

    # Limit fleet to team_size
    fleet = technicians[:team_size]
    num_vehicles = len(fleet)

    # Depot
    depot_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    if not depot_node:
        conn.close()
        return {"success": False, "error": "Could not find office location node"}

    # Node structure
    LOADING_MINUTES = 5  # brief prep at office before heading out
    nodes_in_system = [depot_node] + [t['nearest_node_id'] for t in tasks]
    # "demand" for maintenance is 1 task per stop (capacity = max tasks a technician can do)
    # We use a generous capacity so OR-Tools focuses on time windows
    node_demands = [0] + [1 for _ in tasks]
    station_ids = [None] + [t['station_id'] for t in tasks]
    node_service_times = [LOADING_MINUTES] + [t['service_time'] for t in tasks]
    node_windows = [(0, 1440)] + [(t['window_start'], t['window_end']) for t in tasks]

    if None in nodes_in_system:
        null_indices = [i for i, n in enumerate(nodes_in_system) if n is None]
        raise ValueError(f"CRITICAL: {len(null_indices)} tasks have NULL nearest_node_id!")

    size = len(nodes_in_system)

    # Fetch distance matrix
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

    idx_to_node = {i: nodes_in_system[i] for i in range(size)}

    # Vehicle configuration from technician shifts
    vehicle_times = []
    for v in fleet:
        s, e = v['shift_start'], v['shift_end']
        if e < s:
            e += 1440
        vehicle_times.append((s, e))

    max_tasks_per_tech = max(20, len(tasks))  # generous capacity

    # Create routing model
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Time callback
    def time_callback(from_idx, to_idx):
        fn = manager.IndexToNode(from_idx)
        tn = manager.IndexToNode(to_idx)
        travel = dist_matrix[fn][tn] / 60
        if fn != tn:
            travel_min = max(1, round(travel))
        else:
            travel_min = 0
        return travel_min + node_service_times[fn]

    time_cb_idx = routing.RegisterTransitCallback(time_callback)

    max_vehicle_end = max(e for _, e in vehicle_times) if vehicle_times else 1440
    max_window_end = max(w[1] for w in node_windows) if node_windows else 1440
    absolute_max = max(max_vehicle_end + 120, max_window_end) + 60

    routing.AddDimension(time_cb_idx, 120, absolute_max, False, 'Time')
    time_dimension = routing.GetDimensionOrDie('Time')

    # Task time windows (soft)
    for i in range(1, size):
        index = manager.NodeToIndex(i)
        _, deadline = node_windows[i]
        time_dimension.CumulVar(index).SetRange(0, absolute_max)
        time_dimension.SetCumulVarSoftUpperBound(index, deadline, 100000)

    # Technician shift constraints
    for v in range(num_vehicles):
        start_avail, end_avail = vehicle_times[v]
        start_index = routing.Start(v)
        time_dimension.CumulVar(start_index).SetRange(start_avail, end_avail)
        end_index = routing.End(v)
        overtime_limit = min(end_avail + 60, absolute_max)
        overtime_limit = max(overtime_limit, start_avail)
        time_dimension.CumulVar(end_index).SetRange(start_avail, overtime_limit)
        time_dimension.SetCumulVarSoftUpperBound(end_index, end_avail, 50000)
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(start_index))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(end_index))
        routing.SetFixedCostOfVehicle(2000, v)

    # Drop penalty
    for i in range(1, size):
        routing.AddDisjunction([manager.NodeToIndex(i)], 1000000000)

    # Cost callback (uniform for technicians)
    def cost_callback(from_idx, to_idx):
        fn = manager.IndexToNode(from_idx)
        tn = manager.IndexToNode(to_idx)
        return dist_matrix[fn][tn]

    cost_cb_idx = routing.RegisterTransitCallback(cost_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(cost_cb_idx)

    # Demand / capacity
    def demand_cb(from_idx):
        return node_demands[manager.IndexToNode(from_idx)]

    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(demand_cb),
        0,
        [max_tasks_per_tech] * num_vehicles,
        True,
        'Capacity'
    )

    # Solve
    print(f"  ⏱ Maintenance model setup: {_time.perf_counter() - _t_total:.2f}s")
    _t_solver = _time.perf_counter()
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 10
    search_params.log_search = False

    solution = routing.SolveWithParameters(search_params)
    print(f"  ⏱ Maintenance solver: {_time.perf_counter() - _t_solver:.2f}s")

    if not solution:
        conn.close()
        return {"success": False, "error": "Solver could not find a solution for maintenance tasks"}

    def min_to_clock(minutes):
        h = int(minutes) // 60
        m = int(minutes) % 60
        if h >= 24:
            return f"{h-24:02d}:{m:02d} (+1 Day)"
        return f"{h:02d}:{m:02d}"

    # Prepare results
    cur.execute("""
        ALTER TABLE vector.maintenance_task_node_map ADD COLUMN IF NOT EXISTS technician_id INTEGER;
        ALTER TABLE vector.maintenance_task_node_map ADD COLUMN IF NOT EXISTS arrival_time TEXT;
        ALTER TABLE vector.maintenance_task_node_map ADD COLUMN IF NOT EXISTS task_status TEXT;
    """)
    cur.execute("UPDATE vector.maintenance_task_node_map SET technician_id = NULL, arrival_time = NULL, task_status = NULL;")

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
                status = "EARLY"
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
                    UPDATE vector.maintenance_task_node_map
                    SET technician_id = %s, arrival_time = %s, task_status = %s
                    WHERE task_id = %s
                """, (v_id + 1, min_to_clock(arrival_min), status, station_ids[node_idx]))

            index = solution.Value(routing.NextVar(index))

        time_var = time_dimension.CumulVar(index)
        return_min = solution.Min(time_var)
        route_nodes.append(depot_node)

        routes.append({
            "vehicle_id": v_id + 1,
            "technician_name": fleet[v_id]['name'],
            "route_nodes": route_nodes,
            "stops": route_stops,
            "start_time": min_to_clock(start_min),
            "end_time": min_to_clock(return_min),
            "num_tasks": len(route_stops),
        })

    # Save geometries
    _t_geom = _time.perf_counter()
    print(f"🛤️ Generating road geometries for {len(routes)} maintenance routes...")
    save_maintenance_route_geometries(conn, [{"vehicle_id": r["vehicle_id"], "route_nodes": r["route_nodes"]} for r in routes])
    print(f"✓ Maintenance geometries generated (took {_time.perf_counter() - _t_geom:.2f}s)")

    # Compute distances
    for route in routes:
        v_id = route["vehicle_id"]
        cur.execute("""
            SELECT COALESCE(SUM(ST_Length(geom::geography)) / 1000.0, 0)
            FROM vector.maintenance_route_geometries WHERE vehicle_id = %s
        """, (v_id,))
        route["distance_km"] = round(float(cur.fetchone()[0]), 2)
        del route["route_nodes"]

    conn.commit()

    # Record unassigned
    cur.execute("""
        INSERT INTO vector.maintenance_unassigned (task_id, reason, latitude, longitude, service_time)
        SELECT
            task_id,
            'Could not fit into any technician schedule (time window/shift constraints)',
            ST_Y(geom), ST_X(geom), service_time
        FROM vector.maintenance_task_node_map
        WHERE technician_id IS NULL
        ON CONFLICT (task_id) DO UPDATE SET reason = EXCLUDED.reason
    """)
    unassigned = cur.rowcount
    if unassigned > 0:
        print(f"\n⚠️  WARNING: {unassigned} maintenance tasks could not be assigned!")
    conn.commit()

    cur.close()
    conn.close()

    print(f"  ⏱ TOTAL solve_maintenance_vrp: {_time.perf_counter() - _t_total:.2f}s")

    return {
        "success": True,
        "routes": routes,
        "total_technicians_used": len(routes),
        "total_tasks_assigned": sum(len(r['stops']) for r in routes),
        "total_tasks_unassigned": unassigned,
    }
