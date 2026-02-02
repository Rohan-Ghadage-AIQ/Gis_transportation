import os
import psycopg2
from dotenv import load_dotenv
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import datetime
load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT")
    )

def save_route_geometry(conn, vehicle_id, route_nodes):
    """Saves road geometries as MultiLineStrings using pgRouting."""
    cur = conn.cursor()
    # Clean old geometry for this specific vehicle before inserting new ones
    cur.execute("DELETE FROM vector.route_geometries WHERE vehicle_id = %s", (vehicle_id,))
    
    for i in range(len(route_nodes) - 1):
        start = route_nodes[i]
        end = route_nodes[i+1]
        
        # This query finds the actual road path between two nodes
        insert_query = f"""
            INSERT INTO vector.route_geometries (vehicle_id, geom)
            SELECT {vehicle_id}, ST_Multi(ST_Collect(geom))
            FROM pgr_dijkstra(
                'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
                {start}, {end}, directed := false
            ) AS di
            JOIN vector.road_maharashtra ro ON di.edge = ro.gid
            HAVING ST_Collect(geom) IS NOT NULL; -- Only insert if a path was actually found
        """
        cur.execute(insert_query)
    conn.commit()

def solve_sequences():
    # 1. DATABASE CONNECTION & DATA FETCHING (Must come first)
    conn = get_db_connection()
    cur = conn.cursor()
    warehouse_lon, warehouse_lat = 72.8724, 19.0725

    # Fetch station data
    cur.execute("""
        SELECT nearest_node_id, parcel_weight, station_id, 
               service_time, window_start, window_end 
        FROM vector.station_node_map
    """)
    rows = cur.fetchall()
    
    # Get Depot (Warehouse) node snapped to main network
    cur.execute(f"""
        SELECT m.node FROM pgr_connectedComponents(
            'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra'
        ) m JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node) 
        WHERE m.component = 11 
        ORDER BY r.geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) 
        LIMIT 1;
    """)
    depot_node = cur.fetchone()[0]

    # Map nodes to indices
    nodes_in_system = [depot_node] + [r[0] for r in rows]
    node_demands = [0] + [r[1] for r in rows]
    station_ids = [None] + [r[2] for r in rows]
    
    # Time Data: Depot starts at 0 (9:00 AM) and can work 480 mins (8 hours)
    node_service_times = [0] + [r[3] for r in rows]
    node_windows = [(0, 480)] + [(r[4], r[5]) for r in rows]
    
    size = len(nodes_in_system)
    node_to_idx = {node: i for i, node in enumerate(nodes_in_system)}
    idx_to_node = {i: node for node, i in node_to_idx.items()}

    # 2. FETCH DISTANCE MATRIX
    node_ids_str = ",".join(map(str, nodes_in_system))
    cur.execute(f"""
        SELECT start_vid, end_vid, agg_cost 
        FROM vector.distance_matrix 
        WHERE start_vid IN ({node_ids_str}) AND end_vid IN ({node_ids_str})
    """)
    
    dist_matrix = [[1000000] * size for _ in range(size)]
    for i in range(size): dist_matrix[i][i] = 0
    for u, v, cost in cur.fetchall():
        if u in node_to_idx and v in node_to_idx:
            dist_matrix[node_to_idx[u]][node_to_idx[v]] = int(float(cost))

    # 3. SOLVER CONFIGURATION
    num_vehicles = 8
    # Set a high HARD limit (500) to ensure the solver always finds a valid path
    vehicle_capacities = [
    175, 261,  # Vehicle 1, 2
    348, 156,  # Vehicle 3, 4
    178, 142,  # Vehicle 5, 6
    118, 125   # Vehicle 7, 8
]
    
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    
    # 4. CALLBACKS & DIMENSIONS
    
    # Time Callback: (Distance / 666m/min) + Service Time
    def time_callback(from_idx, to_idx):
        from_node = manager.IndexToNode(from_idx)
        to_node = manager.IndexToNode(to_idx)
        travel_time = dist_matrix[from_node][to_node] / 666 
        return int(travel_time + node_service_times[from_node])

    time_callback_index = routing.RegisterTransitCallback(time_callback)
    
    # routing.SetArcCostEvaluatorOfAllVehicles(time_callback_index) # Minimize Time

    # Time Dimension for Windows
    routing.AddDimension(
        time_callback_index,
        60,   # allow waiting time (slack)
        720,  # 12 hours Total shift 9 AM TO 9 PM
        False, 
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')

    # Apply Windows to all nodes

    # 1. Clear any Hard Ranges that might be causing failures
    # Apply Tiered Windows to all nodes
    for i in range(1, size):
        index = manager.NodeToIndex(i)
        deadline = node_windows[i][1]
        
        # 1. Physical Hard Limit (End of the day)
        time_dimension.CumulVar(index).SetRange(0, 840)
        
        # 2. THE BUFFER LOGIC
        # We want to deliver 60 mins before the deadline if possible.
        preferred_time = max(0, deadline - 60) 
        # Small penalty (1,000) for every minute between 10 AM and 11 AM
        time_dimension.SetCumulVarSoftUpperBound(index, preferred_time, 5000)
        
        # 3. THE DEADLINE LOGIC
        # Massive penalty (100,000) for every minute after 11 AM
        time_dimension.SetCumulVarSoftUpperBound(index, deadline, 1000000)
        
    # 2. Define Unique Vehicle Shifts (Minutes from 7:00 AM)
    # Format: (Start_Min, End_Min)
    vehicle_times = [
        (120, 660), (120, 660), # V1, V2: 9 AM - 6 PM
        (0, 480),               # V3: 7 AM - 3 PM
        (0, 660),               # V4: 7 AM - 6 PM
        (120, 600),             # V5: 9 AM - 5 PM
        (60, 660),              # V6: 8 AM - 6 PM
        (60, 840),              # V7: 8 AM - 9 PM
        (0, 780)                # V8: 7 AM - 8 PM
    ]
    
    for v in range(num_vehicles):
        start_avail, end_avail = vehicle_times[v]
        
        # Start exactly at their specific clock-in time
        start_index = routing.Start(v)
        time_dimension.CumulVar(start_index).SetRange(start_avail, start_avail)
        
        # End at or after shift end, but before 9 PM
        end_index = routing.End(v)
        time_dimension.CumulVar(end_index).SetRange(start_avail, 840)
        
        # Soft Upper Bound forces them to try to return by their shift end
        time_dimension.SetCumulVarSoftUpperBound(end_index, end_avail, 50000)

        # Optimization: Prioritize starting on time and finishing early
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(start_index))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(end_index))
        
        routing.SetFixedCostOfVehicle(10000, v)
        
    # Penalty for dropping a parcel (1 million) to 6 million
    for i in range(1, size):
        routing.AddDisjunction([manager.NodeToIndex(i)], 10000000)
        
    # Distance Callback
    def dist_cb(from_idx, to_idx):
        return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(dist_cb))

    # Demand Callback
    def demand_cb(from_idx):
        return node_demands[manager.IndexToNode(from_idx)]
    
    # 4. CAPACITY & SOFT PENALTY
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(demand_cb), 
        0, 
        vehicle_capacities, 
        True, 
        'Capacity'
    )

    # Set Soft Upper Bound to force balance around 160kg
    capacity_dimension = routing.GetDimensionOrDie('Capacity')
    for i in range(num_vehicles):
        index = routing.End(i)
        # Allows flex up to 500 but punishes the solver if it crosses 160
        capacity_dimension.SetCumulVarSoftUpperBound(index, 250, 1000)
        # Apply Fixed Cost to encourage using all trucks
        routing.SetFixedCostOfVehicle(10000, i)
        # Ensure start/end for each vehicle is within 8 hours
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(routing.Start(i)))
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(routing.End(i)))

    # 5. SOLVE
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 180 # 2 minutes search time to 3 minutes

    solution = routing.SolveWithParameters(search_params)

    # Helper function for clock formatting
    def min_to_clock(minutes):
        """
        Converts minutes elapsed since 7:00 AM into a readable 12-hour clock string.
        Aligned with the new heterogeneous fleet and 3-shift delivery logic.
        """
        # 1. Define the base start time (7:00 AM)
        base_time = datetime.datetime.combine(datetime.date.today(), datetime.time(7, 0))
        
        # 2. Add the elapsed minutes from the solver
        target_time = base_time + datetime.timedelta(minutes=float(minutes))
        
        # 3. Format with a check for midnight rollovers
        if target_time.date() > base_time.date():
            return target_time.strftime("%I:%M %p (+1 Day)")
            
        return target_time.strftime("%I:%M %p")
    
    # 6. SAVE RESULTS
    if solution:
        # Prepare the geometries table
        cur.execute("CREATE TABLE IF NOT EXISTS vector.route_geometries (vehicle_id integer, geom geometry);")
        
        # Prepare the station_node_map to store the results
        # We add a 'vehicle_id' column if it doesn't exist
        cur.execute("ALTER TABLE vector.station_node_map ADD COLUMN IF NOT EXISTS vehicle_id integer;")
        # Clear old assignments
        cur.execute("UPDATE vector.station_node_map SET vehicle_id = NULL;")

        print("\n" + "="*50)
        print("SUCCESS: SAVING ROUTES & CALCULATING ARRIVAL TIMES")
        print("="*50)
     
        for v_id in range(num_vehicles):
            index = routing.Start(v_id)
            if routing.IsEnd(solution.Value(routing.NextVar(index))):
                print(f"Vehicle {v_id + 1}: Unused")
                continue

            print(f"\n--- Vehicle {v_id + 1} Route ---")
            route_nodes = []
            
            # 1. IMPROVEMENT: Show the actual Clock-in time for this specific vehicle
            start_min = solution.Min(time_dimension.CumulVar(index))
            print(f"Warehouse (Start) | Clock-in: {min_to_clock(start_min)}")
            
            while not routing.IsEnd(index):
                node_idx = manager.IndexToNode(index)
                node_id = idx_to_node[node_idx]
                route_nodes.append(node_id)
                
                # Define the deadline for THIS specific station ---
                deadline = node_windows[node_idx][1] #
                
                # Arrival Time Trace
                arrival_min = solution.Min(time_dimension.CumulVar(index))
                status = ""
                # Buffer Logic: Ideal is >60 mins early
                if arrival_min <= (deadline - 60):
                    status = " [IDEAL]"
                # Buffer Logic: 0-60 mins before deadline
                elif arrival_min <= deadline:
                    status = " [IN BUFFER]"
                else:
                    status = " [LATE]"
                    
                node_name = f"Station {station_ids[node_idx]}" if node_id != depot_node else "Warehouse"
                print(f"{node_name.ljust(15)} | Arrives: {min_to_clock(arrival_min)}{status}")
                
                if node_id != depot_node:
                    cur.execute("""
                        UPDATE vector.station_node_map 
                        SET vehicle_id = %s 
                        WHERE station_id = %s
                    """, (v_id + 1, station_ids[node_idx]))
                
                index = solution.Value(routing.NextVar(index))
            
            # Return to Depot
            time_var = time_dimension.CumulVar(index)
            return_min = solution.Min(time_var)
            print(f"Warehouse (End) | Arrives: {min_to_clock(return_min)}")
            
            # Vehicle capacity print
            total_weight = solution.Min(capacity_dimension.CumulVar(index))
            max_cap = vehicle_capacities[v_id]
            utilization = (total_weight / max_cap) * 100
            print(f"Weight Carried: {total_weight}kg / {max_cap}kg ({utilization:.1f}% Utilized)")
            
            # ----------------------------------
            actual_work_time = return_min - start_min
            
            # 3. IMPROVEMENT: Check if the vehicle exceeded its specific shift end
            _, end_avail = vehicle_times[v_id]
            overtime = max(0, return_min - end_avail)
            overtime_str = f" (Overtime: {overtime} mins)" if overtime > 0 else " [ON TIME]"
            
            print(f"Total Work Duration: {actual_work_time} minutes{overtime_str}")
            
            route_nodes.append(depot_node)
            
            if len(route_nodes) > 2:
                save_route_geometry(conn, v_id + 1, route_nodes)
                print(f"Vehicle {v_id + 1}: Geometry and assignments saved.")
            else:
                print(f"Vehicle {v_id + 1}: No stops assigned.")
            
        conn.commit()
        cur.close()
        conn.close()
        print("\nSuccess: Balanced weight and road routes saved to database.")
    else:
        print("\nError: Solver could not find a solution. Try increasing search time or adjusting constraints.")
        
if __name__ == "__main__":
    solve_sequences()