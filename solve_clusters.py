import os
import psycopg2
from dotenv import load_dotenv
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

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
    # 1. SETUP: Lowered capacity to 155kg forces the spread across all 8 vehicles
    vehicle_capacities = [300] * 8 
    num_vehicles = len(vehicle_capacities)
    warehouse_lon, warehouse_lat = 72.8724, 19.0725
    
    conn = get_db_connection()
    cur = conn.cursor()

    # 2. FETCH DATA
    cur.execute("SELECT nearest_node_id, parcel_weight, station_id FROM vector.station_node_map")
    rows = cur.fetchall()
    
    # Get Depot (Warehouse) node
    cur.execute(f"SELECT m.node FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node) WHERE m.component = 11 ORDER BY r.geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) LIMIT 1;")
    depot_node = cur.fetchone()[0]

    nodes_in_system = [depot_node] + [r[0] for r in rows]
    node_demands = [0] + [r[1] for r in rows]
    station_ids = [None] + [r[2] for r in rows]
    
    size = len(nodes_in_system)
    node_to_idx = {node: i for i, node in enumerate(nodes_in_system)}
    idx_to_node = {i: node for node, i in node_to_idx.items()}

    # 3. FETCH DISTANCE MATRIX
    node_ids_str = ",".join(map(str, nodes_in_system))
    cur.execute(f"SELECT start_vid, end_vid, agg_cost FROM vector.distance_matrix WHERE start_vid IN ({node_ids_str}) AND end_vid IN ({node_ids_str})")
    
    dist_matrix = [[1000000] * size for _ in range(size)]
    for i in range(size): dist_matrix[i][i] = 0
    for u, v, cost in cur.fetchall():
        if u in node_to_idx and v in node_to_idx:
            dist_matrix[node_to_idx[u]][node_to_idx[v]] = int(float(cost))

    # 4. SOLVER CONFIGURATION
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(from_idx, to_idx):
        return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(dist_cb))

    def demand_cb(from_idx):
        return node_demands[manager.IndexToNode(from_idx)]
    routing.AddDimensionWithVehicleCapacity(routing.RegisterUnaryTransitCallback(demand_cb), 0, vehicle_capacities, True, 'Capacity')

    # FORCE USE OF ALL 8 VEHICLES via Fixed Costs
    for i in range(num_vehicles):
        routing.SetFixedCostOfVehicle(10000, i)

    # 5. SOLVE
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 60

    solution = routing.SolveWithParameters(search_params)

    # 6. SAVE RESULTS (Clusters and Geometries)
    if solution:
        # Prepare tables
        cur.execute("CREATE TABLE IF NOT EXISTS vector.route_geometries (vehicle_id integer, geom geometry);")
        cur.execute("DROP TABLE IF EXISTS vector.final_station_clusters;")
        cur.execute("CREATE TABLE vector.final_station_clusters (station_id text, cluster_id int, weight int);")
        
        print("\nProcessing and saving routes for all vehicles...")
        for v_id in range(num_vehicles):
            index = routing.Start(v_id)
            route_nodes = []
            
            while not routing.IsEnd(index):
                node_idx = manager.IndexToNode(index)
                node_id = idx_to_node[node_idx]
                route_nodes.append(node_id)
                
                # Save station assignments to cluster table
                if node_id != depot_node:
                    cur.execute("INSERT INTO vector.final_station_clusters VALUES (%s, %s, %s)", 
                                (station_ids[node_idx], v_id + 1, node_demands[node_idx]))
                
                index = solution.Value(routing.NextVar(index))
            
            route_nodes.append(depot_node) # Complete the loop back to warehouse
            
            # Save actual road geometry if vehicle has stops
            if len(route_nodes) > 2:
                save_route_geometry(conn, v_id + 1, route_nodes)
                print(f"Vehicle {v_id + 1}: Geometry and assignments saved.")
            else:
                print(f"Vehicle {v_id + 1}: No stops assigned.")

        conn.commit()
        cur.close()
        conn.close()
        print("\nSuccess: Balanced weight and road routes saved to database.")

if __name__ == "__main__":
    solve_sequences()