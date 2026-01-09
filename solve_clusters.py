import os
import psycopg2
from dotenv import load_dotenv
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def solve_clusters():
    num_vehicles = int(os.getenv("NUM_CLUSTERS", 5))
    depot_node = int(os.getenv("WAREHOUSE_NODE_ID", 638948))

    # 1. Fetch data from pgAdmin
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT start_vid, end_vid, agg_cost FROM vector.distance_matrix")
    rows = cur.fetchall()

    # 2. Build Index Mapping
    all_nodes = sorted(list(set([r[0] for r in rows] + [r[1] for r in rows])))
    node_to_idx = {node: i for i, node in enumerate(all_nodes)}
    idx_to_node = {i: node for node, i in node_to_idx.items()}
    
    size = len(all_nodes)
    dist_matrix = [[999999] * size for _ in range(size)]
    for i in range(size): dist_matrix[i][i] = 0
    
    for start_node, end_node, cost in rows:
        dist_matrix[node_to_idx[start_node]][node_to_idx[end_node]] = int(cost)

    # 3. Setup OR-Tools
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, node_to_idx[depot_node])
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return dist_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # --- ADDED: BALANCING LOGIC (Correctly Indented) ---
    dimension_name = 'Distance'
    routing.AddDimension(
        transit_callback_index,
        0,      # no slack
        1000000, # maximum distance (increased to avoid "No Solution" errors)
        True,   # start cumul to zero
        dimension_name)

    distance_dimension = routing.GetDimensionOrDie(dimension_name)
    # This coefficient forces the solver to balance the 5 routes
    distance_dimension.SetGlobalSpanCostCoefficient(100)

    # 4. Solve
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    
    solution = routing.SolveWithParameters(search_parameters)

    # 5. Output Results
    if solution:
        print("Successfully created 5 balanced clusters:")
        for vehicle_id in range(num_vehicles):
            index = routing.Start(vehicle_id)
            cluster_nodes = []
            while not routing.IsEnd(index):
                node_id = idx_to_node[manager.IndexToNode(index)]
                if node_id != depot_node:
                    cluster_nodes.append(node_id)
                index = solution.Value(routing.NextVar(index))
            print(f"Cluster {vehicle_id + 1}: {cluster_nodes}")
    else:
        print("No solution found. Try increasing the maximum distance in AddDimension.")

if __name__ == "__main__":
    solve_clusters()