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
    """Fetches road geometries for each leg and saves them as a MultiLineString."""
    cur = conn.cursor()
    # Clear existing geometry for this vehicle
    cur.execute("DELETE FROM vector.route_geometries WHERE vehicle_id = %s", (vehicle_id,))
    
    for i in range(len(route_nodes) - 1):
        start = route_nodes[i]
        end = route_nodes[i+1]
        
        # Use ST_Multi and ST_Collect to handle multiple segments correctly
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
    print(f"  -> Road geometry for Vehicle {vehicle_id} saved.")
    
def solve_sequences():
    num_clusters = 5
    depot_node = int(os.getenv("WAREHOUSE_NODE_ID", 638948))
    conn = get_db_connection()
    cur = conn.cursor()

    # STEP 1: Ensure Geometry Table exists and run PostGIS Clustering
    print("Step 1: Initializing tables and PostGIS Clustering...")
    cur.execute("CREATE TABLE IF NOT EXISTS vector.route_geometries (vehicle_id integer, geom geometry);")
    cur.execute("DROP TABLE IF EXISTS vector.final_station_clusters;")
    cur.execute("""
        CREATE TABLE vector.final_station_clusters AS
        SELECT 
            station_id,
            nearest_node_id,
            ST_ClusterKMeans(geom, 5) OVER () AS cluster_id,
            geom
        FROM vector.station_node_map;
    """)
    conn.commit()
    print("  -> Clusters created via ST_ClusterKMeans.")

    # STEP 2: Optimize and Save each Cluster
    print("\nStep 2: Optimizing sequences and generating road lines...")
    for cluster_id in range(num_clusters):
        # Fetch nodes for this specific cluster
        cur.execute(f"SELECT nearest_node_id FROM vector.final_station_clusters WHERE cluster_id = {cluster_id}")
        nodes_in_cluster = [depot_node] + [row[0] for row in cur.fetchall()]
        
        if len(nodes_in_cluster) <= 1:
            print(f"Cluster {cluster_id + 1}: No stations assigned.")
            continue

        # OR-Tools Index Mapping
        size = len(nodes_in_cluster)
        node_to_idx = {node: i for i, node in enumerate(nodes_in_cluster)}
        idx_to_node = {i: node for node, i in node_to_idx.items()}

        # Build local distance matrix for these nodes
        node_ids_str = ",".join(map(str, nodes_in_cluster))
        cur.execute(f"""
            SELECT start_vid, end_vid, agg_cost 
            FROM vector.distance_matrix 
            WHERE start_vid IN ({node_ids_str}) AND end_vid IN ({node_ids_str})
        """)
        
        dist_matrix = [[999999] * size for _ in range(size)]
        for i in range(size): dist_matrix[i][i] = 0
        for u, v, cost in cur.fetchall():
            if u in node_to_idx and v in node_to_idx:
                dist_matrix[node_to_idx[u]][node_to_idx[v]] = int(cost)

        # OR-Tools Solver
        manager = pywrapcp.RoutingIndexManager(size, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            return dist_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)

        solution = routing.SolveWithParameters(search_parameters)

        if solution:
            index = routing.Start(0)
            route = []
            while not routing.IsEnd(index):
                route.append(idx_to_node[manager.IndexToNode(index)])
                index = solution.Value(routing.NextVar(index))
            route.append(depot_node)
            
            print(f"Cluster {cluster_id + 1} Path: {' -> '.join(map(str, route))}")
            
            # Save the result as a road geometry in the DB
            save_route_geometry(conn, cluster_id + 1, route)

    cur.close()
    conn.close()
    print("\nAll routes processed successfully. Check QGIS for results.")

if __name__ == "__main__":
    solve_sequences()