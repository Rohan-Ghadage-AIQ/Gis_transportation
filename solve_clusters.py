import os
import psycopg2
from dotenv import load_dotenv
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# Load environment variables
load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def save_route_geometry(conn, vehicle_id, route_nodes):
    """Saves road geometries as MultiLineStrings using pgRouting."""
    cur = conn.cursor()
    cur.execute("DELETE FROM vector.route_geometries WHERE vehicle_id = %s", (vehicle_id,))
    
    for i in range(len(route_nodes) - 1):
        start = route_nodes[i]
        end = route_nodes[i+1]
        
        insert_query = f"""
            INSERT INTO vector.route_geometries (vehicle_id, geom)
            SELECT {vehicle_id}, ST_Multi(ST_Collect(geom))
            FROM pgr_dijkstra(
                'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
                {start}, {end}, directed := false
            ) AS di
            JOIN vector.road_maharashtra ro ON di.edge = ro.gid;
        """
        cur.execute(insert_query)
    conn.commit()

def solve_sequences():
    # --- 1. CONFIGURATION ---
    # FORCED DIVISION: Setting capacity to 70kg forces the spread across all 8 vehicles
    vehicle_capacities = [25,25,25,25,25,25,25,25] 
    num_vehicles = len(vehicle_capacities)
    
    warehouse_lon = 72.8724 
    warehouse_lat = 19.0725
    
    conn = get_db_connection()
    cur = conn.cursor()

    # 2. Dynamic Warehouse Snapping
    cur.execute(f"""
        SELECT m.node FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m
        JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
        WHERE m.component = 11
        ORDER BY r.geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) LIMIT 1;
    """)
    depot_node = cur.fetchone()[0]
    print(f"Warehouse Snapped to Node: {depot_node}")

    # 3. Fetch stations and weights
    cur.execute("SELECT nearest_node_id, parcel_weight, station_id FROM vector.station_node_map")
    rows = cur.fetchall()
    
    station_nodes = [row[0] for row in rows]
    station_weights = [row[1] for row in rows]
    station_ids_list = [row[2] for row in rows]
    
    nodes_in_system = [depot_node] + station_nodes
    node_demands = [0] + station_weights 
    
    # Precise mapping to ensure station_id is retrieved correctly during the loop
    # Index 0 is the Depot (None)
    node_to_station_map = {nodes_in_system[i]: ([None] + station_ids_list)[i] for i in range(len(nodes_in_system))}
    
    size = len(nodes_in_system)
    node_to_idx = {node: i for i, node in enumerate(nodes_in_system)}
    idx_to_node = {i: node for node, i in node_to_idx.items()}

    # 4. Fetch Distance Matrix
    node_ids_str = ",".join(map(str, nodes_in_system))
    cur.execute(f"""
        SELECT start_vid, end_vid, agg_cost FROM vector.distance_matrix 
        WHERE start_vid IN ({node_ids_str}) AND end_vid IN ({node_ids_str})
    """)
    
    dist_matrix = [[999999] * size for _ in range(size)]
    for i in range(size): dist_matrix[i][i] = 0
    for u, v, cost in cur.fetchall():
        if u in node_to_idx and v in node_to_idx:
            dist_matrix[node_to_idx[u]][node_to_idx[v]] = int(cost)

    # 5. Solver Setup
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return dist_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
    
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    def demand_callback(from_index):
        return node_demands[manager.IndexToNode(from_index)]
    
    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(demand_callback_index, 0, vehicle_capacities, True, 'Capacity')

    # GLOBAL SPAN: Ensures distance is balanced among all active vehicles
    distance_dimension_name = 'Distance'
    routing.AddDimension(transit_callback_index, 0, 1000000, True, distance_dimension_name)
    distance_dimension = routing.GetDimensionOrDie(distance_dimension_name)
    distance_dimension.SetGlobalSpanCostCoefficient(100)

    # FIXED COST: Forcing the use of the entire fleet
    for i in range(num_vehicles):
        routing.SetFixedCostOfVehicle(5000, i)

    # 6. Search Parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    search_parameters.time_limit.seconds = 30
    search_parameters.local_search_metaheuristic = (routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)

    print("Solving for 8 balanced routes (30s limit)...")
    solution = routing.SolveWithParameters(search_parameters)

    # 7. Results and Table Updates
    if solution:
        cur.execute("CREATE TABLE IF NOT EXISTS vector.route_geometries (vehicle_id integer, geom geometry);")
        cur.execute("DROP TABLE IF EXISTS vector.final_station_clusters;")
        
        # Creating a physical table with 'weight' column to match your pgAdmin query
        cur.execute("""
            CREATE TABLE vector.final_station_clusters (
                station_id bigint, 
                nearest_node_id bigint, 
                cluster_id int, 
                weight int, 
                geom geometry
            );
        """)
        
        print("\nStep 2: Dividing weights and saving 8 vehicles to database...")
        for vehicle_id in range(num_vehicles):
            index = routing.Start(vehicle_id)
            route = []
            route_weight = 0
            
            while not routing.IsEnd(index):
                node_idx = manager.IndexToNode(index)
                node_id = idx_to_node[node_idx]
                route.append(node_id)
                
                weight = node_demands[node_idx]
                route_weight += weight
                
                # If the current node is a delivery station (not the warehouse)
                if node_id != depot_node:
                    s_id = node_to_station_map[node_id]
                    # Direct insert ensuring the column names match the report query
                    cur.execute("""
                        INSERT INTO vector.final_station_clusters (station_id, nearest_node_id, cluster_id, weight, geom)
                        SELECT station_id, nearest_node_id, %s, parcel_weight, geom 
                        FROM vector.station_node_map WHERE station_id = %s
                    """, (vehicle_id + 1, s_id))
                
                index = solution.Value(routing.NextVar(index))
            
            route.append(depot_node)
            
            if len(route) > 2:
                print(f"Vehicle {vehicle_id + 1} Load: {route_weight}kg")
                save_route_geometry(conn, vehicle_id + 1, route)
            else:
                print(f"Vehicle {vehicle_id + 1}: Unused (Capacity sufficient without this vehicle).")

    conn.commit()
    cur.close()
    conn.close()
    print("\nDONE. Every parcel is assigned. Check pgAdmin and refresh QGIS.")

if __name__ == "__main__":
    solve_sequences()