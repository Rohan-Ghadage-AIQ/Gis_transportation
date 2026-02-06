import datetime
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from typing import List, Dict, Any, Tuple
from database import (
    get_db_connection,
    get_warehouse_node,
    fetch_station_data,
    fetch_distance_matrix,
    save_route_geometry
)

def solve_vrp(warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725) -> Dict[str, Any]:
    """
    Solve the Vehicle Routing Problem with time windows and capacity constraints.
    Returns a dictionary with solution details including routes, costs, and statistics.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch station data
    stations = fetch_station_data(conn)
    
    if not stations:
        conn.close()
        return {"success": False, "error": "No station data found"}
    
    # Get depot (warehouse) node
    depot_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    
    if not depot_node:
        conn.close()
        return {"success": False, "error": "Could not find warehouse node"}
    
    # Build node mappings
    nodes_in_system = [depot_node] + [s['nearest_node_id'] for s in stations]
    node_demands = [0] + [s['parcel_weight'] for s in stations]
    station_ids = [None] + [s['station_id'] for s in stations]
    node_service_times = [0] + [s['service_time'] for s in stations]
    node_windows = [(0, 480)] + [(s['window_start'], s['window_end']) for s in stations]
    
    size = len(nodes_in_system)
    node_to_idx = {node: i for i, node in enumerate(nodes_in_system)}
    idx_to_node = {i: node for node, i in node_to_idx.items()}
    
    # Fetch distance matrix
    dist_dict = fetch_distance_matrix(conn, nodes_in_system)
    
    # Build 2D distance matrix
    dist_matrix = [[1000000] * size for _ in range(size)]
    for i in range(size):
        dist_matrix[i][i] = 0
    for (u, v), cost in dist_dict.items():
        if u in node_to_idx and v in node_to_idx:
            dist_matrix[node_to_idx[u]][node_to_idx[v]] = int(float(cost))
    
    # Vehicle configuration
    num_vehicles = 8
    vehicle_capacities = [175, 261, 348, 156, 178, 142, 118, 125]
    vehicle_costs_per_km = [15, 20, 25, 12, 15, 12, 10, 10]
    vehicle_times = [
        (120, 660), (120, 660),  # V1, V2: 9 AM - 6 PM
        (0, 480),                # V3: 7 AM - 3 PM
        (0, 660),                # V4: 7 AM - 6 PM
        (120, 600),              # V5: 9 AM - 5 PM
        (60, 660),               # V6: 8 AM - 6 PM
        (60, 840),               # V7: 8 AM - 9 PM
        (0, 780)                 # V8: 7 AM - 8 PM
    ]
    
    # Create routing model
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    
    # Time callback
    def time_callback(from_idx, to_idx):
        from_node = manager.IndexToNode(from_idx)
        to_node = manager.IndexToNode(to_idx)
        travel_time = dist_matrix[from_node][to_node] / 666
        return int(travel_time + node_service_times[from_node])
    
    time_callback_index = routing.RegisterTransitCallback(time_callback)
    
    # Time dimension
    routing.AddDimension(
        time_callback_index,
        60,   # slack
        720,  # 12 hours total shift
        False,
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')
    
    # Apply time windows
    for i in range(1, size):
        index = manager.NodeToIndex(i)
        deadline = node_windows[i][1]
        time_dimension.CumulVar(index).SetRange(0, 840)
        preferred_time = max(0, deadline - 60)
        time_dimension.SetCumulVarSoftUpperBound(index, preferred_time, 5000)
        time_dimension.SetCumulVarSoftUpperBound(index, deadline, 1000000)
    
    # Vehicle-specific time constraints
    for v in range(num_vehicles):
        start_avail, end_avail = vehicle_times[v]
        start_index = routing.Start(v)
        time_dimension.CumulVar(start_index).SetRange(start_avail, start_avail)
        end_index = routing.End(v)
        time_dimension.CumulVar(end_index).SetRange(start_avail, 840)
        time_dimension.SetCumulVarSoftUpperBound(end_index, end_avail, 50000)
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(start_index))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(end_index))
        routing.SetFixedCostOfVehicle(10000, v)
    
    # Penalty for dropping parcels
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
        capacity_dimension.SetCumulVarSoftUpperBound(index, 250, 1000)
        routing.SetFixedCostOfVehicle(10000, i)
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(routing.Start(i)))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(routing.End(i)))
    
    # Solve
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 180
    
    solution = routing.SolveWithParameters(search_params)
    
    if not solution:
        conn.close()
        return {"success": False, "error": "Solver could not find a solution"}
    
    # Helper function for time formatting
    def min_to_clock(minutes):
        base_time = datetime.datetime.combine(datetime.date.today(), datetime.time(7, 0))
        target_time = base_time + datetime.timedelta(minutes=float(minutes))
        if target_time.date() > base_time.date():
            return target_time.strftime("%I:%M %p (+1 Day)")
        return target_time.strftime("%I:%M %p")
    
    # Prepare results
    cur.execute("CREATE TABLE IF NOT EXISTS vector.route_geometries (vehicle_id integer, geom geometry);")
    cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS vehicle_id integer;")
    cur.execute("UPDATE vector.station_node_map SET vehicle_id = NULL;")
    
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
            
            status = "IDEAL"
            if arrival_min <= (deadline - 60):
                status = "IDEAL"
            elif arrival_min <= deadline:
                status = "IN BUFFER"
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
                    SET vehicle_id = %s 
                    WHERE station_id = %s
                """, (v_id + 1, station_ids[node_idx]))
            
            index = solution.Value(routing.NextVar(index))
        
        # Return to depot
        time_var = time_dimension.CumulVar(index)
        return_min = solution.Min(time_var)
        
        total_weight = solution.Min(capacity_dimension.CumulVar(index))
        max_cap = vehicle_capacities[v_id]
        utilization = (total_weight / max_cap) * 100
        
        # Calculate route distance
        route_distance = 0
        prev_index = routing.Start(v_id)
        while not routing.IsEnd(prev_index):
            curr_index = solution.Value(routing.NextVar(prev_index))
            route_distance += dist_matrix[manager.IndexToNode(prev_index)][manager.IndexToNode(curr_index)]
            prev_index = curr_index
        
        total_op_cost = (route_distance / 1000.0) * vehicle_costs_per_km[v_id]
        actual_work_time = return_min - start_min
        _, end_avail = vehicle_times[v_id]
        overtime = max(0, return_min - end_avail)
        
        route_nodes.append(depot_node)
        
        if len(route_nodes) > 2:
            save_route_geometry(conn, v_id + 1, route_nodes)
        
        routes.append({
            "vehicle_id": v_id + 1,
            "stops": route_stops,
            "start_time": min_to_clock(start_min),
            "end_time": min_to_clock(return_min),
            "distance_km": round(route_distance / 1000.0, 2),
            "cost": round(total_op_cost, 2),
            "weight_kg": total_weight,
            "capacity_kg": max_cap,
            "utilization": round(utilization, 1),
            "work_duration_mins": actual_work_time,
            "overtime_mins": overtime
        })
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "success": True,
        "routes": routes,
        "total_vehicles_used": len(routes),
        "total_deliveries": sum(len(r['stops']) for r in routes)
    }
