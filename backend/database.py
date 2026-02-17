import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from typing import List, Dict, Any, Tuple
import pandas as pd

load_dotenv()

def get_db_connection():
    """Create and return a database connection"""
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def setup_station_node_map_table(conn):
    """Create or reset the station_node_map table.
    
    Uses TRUNCATE instead of DROP/CREATE to avoid blocking on active connections.
    Falls back to DROP if table structure needs to be recreated.
    """
    cur = conn.cursor()
    
    # Terminate any other connections that might be blocking
    cur.execute("""
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE datname = current_database() 
          AND pid <> pg_backend_pid()
          AND state = 'idle in transaction';
    """)
    
    # Try TRUNCATE first (fast, doesn't block)
    try:
        cur.execute("TRUNCATE TABLE vector.station_node_map;")
        conn.commit()
    except Exception:
        # Table doesn't exist yet, create it
        conn.rollback()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vector.station_node_map (
                station_id TEXT PRIMARY KEY,
                nearest_node_id BIGINT,
                parcel_weight INT DEFAULT 20,
                service_time INT DEFAULT 10,
                window_start INT DEFAULT 0,
                window_end INT DEFAULT 480,
                vehicle_id INTEGER,
                arrival_time TEXT,
                delivery_status TEXT,
                geom geometry(Point, 4326)
            );
        """)
        conn.commit()
    
    # Ensure unassigned_parcels table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vector.unassigned_parcels (
            station_id VARCHAR PRIMARY KEY,
            reason VARCHAR NOT NULL,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            parcel_weight INTEGER,
            window_end INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()

def insert_stations_from_dataframe(conn, df: pd.DataFrame, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725):
    """
    Insert station data from uploaded DataFrame to station_node_map table.
    Snaps each station to the nearest node in the main road network (component 11).
    
    Expected DataFrame columns: id, latitude, longitude (and optionally: parcel_weight, service_time, window_start, window_end)
    
    Optimization: Pre-fetches main component nodes once instead of querying for each station.
    """
    cur = conn.cursor()
    
    # Pre-fetch all nodes in main component (component 11) - do this ONCE
    # This is much faster than calling pgr_connectedComponents for each station
    # Use OR condition to ensure temp table is populated, GROUP BY ensures uniqueness
    cur.execute("""
        CREATE TEMP TABLE IF NOT EXISTS temp_main_component_nodes AS
        SELECT m.node, r.geom
        FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m
        JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
        WHERE m.component = 11
        GROUP BY m.node, r.geom;
        
        CREATE INDEX IF NOT EXISTS idx_temp_main_nodes_geom ON temp_main_component_nodes USING GIST (geom);
    """)
    
    # DEBUG: Check if temp table has nodes
    cur.execute("SELECT COUNT(*) FROM temp_main_component_nodes;")
    node_count = cur.fetchone()[0]
    print(f"DEBUG: Temp table has {node_count} nodes from component 11")
    
    # Insert stations with nearest node snapping (using pre-fetched nodes)
    inserted_count = 0
    for _, row in df.iterrows():
        station_id = str(row['id'])
        lat = float(row['latitude'])
        lon = float(row['longitude'])
        weight = int(row.get('parcel_weight', 20))
        service_time = int(row.get('service_time', 10))
        window_start = int(row.get('window_start', 0))
        window_end = int(row.get('window_end', 480))
        
        # Use pre-fetched main component nodes for faster lookups
        # FALLBACK CHAIN: nearest node in temp_table → any node in temp_table
        # NOTE: Removed pgr_connectedComponents fallback - it caused a full graph
        # traversal (160K+ nodes) per station, turning a 2-min job into 10+ min.
        cur.execute("""
            INSERT INTO vector.station_node_map (station_id, nearest_node_id, parcel_weight, service_time, window_start, window_end, geom)
            SELECT 
                %s,
                COALESCE(
                    (SELECT node 
                     FROM temp_main_component_nodes
                     ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 4326) 
                     LIMIT 1),
                    (SELECT node 
                     FROM temp_main_component_nodes
                     LIMIT 1)
                ),
                %s, %s, %s, %s,
                ST_SetSRID(ST_Point(%s, %s), 4326)
            RETURNING nearest_node_id
        """, (station_id, lon, lat, weight, service_time, window_start, window_end, lon, lat))
        
        # Check if node was assigned
        result = cur.fetchone()
        if result and result[0] is None:
            print(f"⚠️  CRITICAL: Station {station_id} at ({lat}, {lon}) got NULL nearest_node_id despite fallbacks!")
        else:
            inserted_count += 1
    
    print(f"DEBUG: Inserted {inserted_count} out of {len(df)} stations into station_node_map")
    
    # Clean up temp table
    cur.execute("DROP TABLE IF EXISTS temp_main_component_nodes;")
    
    conn.commit()
    cur.close()

def randomize_station_attributes(conn):
    """
    Randomize service times, time windows, and parcel weights for stations.
    This mimics the SQL steps 8-11 from the user's workflow.
    """
    cur = conn.cursor()
    
    # Randomize service time (5-20 minutes)
    cur.execute("""
        UPDATE vector.station_node_map 
        SET service_time = floor(random() * (20-5+1) + 5);
    """)
    
    # Update window end to 12 hours (720 minutes)
    cur.execute("""
        UPDATE vector.station_node_map 
        SET window_end = 720 WHERE window_end = 480;
    """)
    
    # Randomize time windows across 3 shifts
    cur.execute("""
        UPDATE vector.station_node_map 
        SET 
            window_start = 0, 
            window_end = CASE 
                WHEN random() < 0.3 THEN floor(random() * (180-0+1) + 0)   -- Shift 1 (7-10 AM)
                WHEN random() < 0.8 THEN floor(random() * (660-180+1) + 180) -- Shift 2 (10 AM-6 PM)
                ELSE floor(random() * (840-660+1) + 660)                    -- Shift 3 (6-9 PM)
            END;
    """)
    
    # Randomize parcel weights (10-30 kg)
    cur.execute("""
        UPDATE vector.station_node_map 
        SET parcel_weight = floor(random() * (30 - 10 + 1) + 10);
    """)
    
    conn.commit()
    cur.close()

def calculate_distance_matrix(conn, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725):
    """
    Calculate distance matrix using pgRouting's pgr_dijkstraCost (optimized for bulk calculations).
    Includes all stations plus the warehouse node.
    
    Optimizations:
    1. Uses pgr_dijkstraCost instead of individual pgr_dijkstra calls
    2. Adds spatial indexes for faster nearest node lookups
    3. Caches warehouse node to avoid repeated lookups
    """
    cur = conn.cursor()
    
    # Create spatial index on road network if not exists (one-time operation)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_road_maharashtra_geom 
        ON vector.road_maharashtra USING GIST (geom);
    """)
    
    # Create index on source/target for faster routing
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_road_maharashtra_source 
        ON vector.road_maharashtra (source);
        
        CREATE INDEX IF NOT EXISTS idx_road_maharashtra_target 
        ON vector.road_maharashtra (target);
    """)
    
    conn.commit()
    
    # Truncate existing matrix
    cur.execute("TRUNCATE TABLE vector.distance_matrix;")
    
    # Get warehouse node once (cached)
    warehouse_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    
    # Get all station nodes
    cur.execute("SELECT DISTINCT nearest_node_id FROM vector.station_node_map WHERE nearest_node_id IS NOT NULL")
    station_nodes = [row[0] for row in cur.fetchall()]
    all_nodes = station_nodes + [warehouse_node]
    
    print(f"DEBUG: Calculating distance matrix for {len(all_nodes)} nodes (warehouse + {len(station_nodes)} stations)")
    
    # Calculate distances using pgr_dijkstraCost (bulk operation - much faster!)
    # This calculates all-pairs shortest paths in one query
    try:
        cur.execute("""
            INSERT INTO vector.distance_matrix (start_vid, end_vid, agg_cost)
            SELECT start_vid, end_vid, agg_cost
            FROM pgr_dijkstraCost(
                'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
                %s::bigint[],
                %s::bigint[],
                directed := false
            )
        """, (all_nodes, all_nodes))
        
        rows_inserted = cur.rowcount
        print(f"DEBUG: Inserted {rows_inserted} distance matrix entries")
        
    except Exception as e:
        print(f"⚠️  ERROR calculating distance matrix: {e}")
        raise
    
    conn.commit()
    cur.close()

def get_warehouse_node(conn, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725) -> int:
    """Get the warehouse node snapped to the main road network"""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT m.node FROM pgr_connectedComponents(
            'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra'
        ) m JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node) 
        WHERE m.component = 11 
        ORDER BY r.geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) 
        LIMIT 1;
    """)
    result = cur.fetchone()
    cur.close()
    return result[0] if result else None

def fetch_station_data(conn) -> List[Dict[str, Any]]:
    """Fetch all station data from station_node_map"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT nearest_node_id, parcel_weight, station_id, 
               service_time, window_start, window_end,
               ST_X(geom) as longitude, ST_Y(geom) as latitude
        FROM vector.station_node_map
        WHERE nearest_node_id IS NOT NULL
        ORDER BY station_id
    """)
    rows = cur.fetchall()
    
    # Log if any stations were filtered out and record them as unassigned
    cur.execute("SELECT COUNT(*) as count FROM vector.station_node_map WHERE nearest_node_id IS NULL")
    result = cur.fetchone()
    null_count = result['count'] if result else 0
    if null_count > 0:
        print(f"\n⚠️  WARNING: {null_count} parcels have NULL nearest_node_id and will be SKIPPED!")
        print(f"These parcels could not be snapped to the road network.\n")
        
        # Record unassigned parcels in database
        cur.execute("""
            INSERT INTO vector.unassigned_parcels (station_id, reason, latitude, longitude, parcel_weight, window_end)
            SELECT 
                station_id,
                'Could not snap to road network - no valid road node found',
                ST_Y(geom) as latitude,
                ST_X(geom) as longitude,
                parcel_weight,
                window_end
            FROM vector.station_node_map
            WHERE nearest_node_id IS NULL
            ON CONFLICT (station_id) DO UPDATE SET reason = EXCLUDED.reason
        """)
        conn.commit()
    
    cur.close()
    return [dict(row) for row in rows]

def fetch_distance_matrix(conn, node_ids: List[int]) -> Dict[Tuple[int, int], float]:
    """Fetch distance matrix for given node IDs"""
    cur = conn.cursor()
    
    # Filter out None values
    valid_node_ids = [n for n in node_ids if n is not None]
    
    print(f"DEBUG: Fetching distance matrix for {len(valid_node_ids)} nodes")
    
    # Fetch all distances for the given nodes
    cur.execute("""
        SELECT start_vid, end_vid, agg_cost
        FROM vector.distance_matrix
        WHERE start_vid = ANY(%s) AND end_vid = ANY(%s)
    """, (valid_node_ids, valid_node_ids))
    
    rows = cur.fetchall()
    result = {(int(row[0]), int(row[1])): float(row[2]) for row in rows}
    
    print(f"DEBUG: Retrieved {len(result)} distance matrix entries from database")
    
    # Check for missing entries
    expected_entries = len(valid_node_ids) * len(valid_node_ids)
    if len(result) < expected_entries:
        missing = expected_entries - len(result)
        print(f"⚠️  WARNING: {missing} distance matrix entries are MISSING!")
        
        # Find which nodes have no paths
        nodes_with_paths = set()
        for (start, end) in result.keys():
            nodes_with_paths.add(start)
            nodes_with_paths.add(end)
        
        missing_nodes = set(valid_node_ids) - nodes_with_paths
        if missing_nodes:
            print(f"⚠️  Nodes with NO paths: {list(missing_nodes)[:10]}")  # Show first 10
    
    cur.close()
    return result

def save_route_geometry(conn, vehicle_id: int, route_nodes: List[int]):
    """
    Save road geometries as MultiLineStrings using pgRouting.
    This creates actual road-based routes, not straight lines.
    
    Optimization: Uses a single batched query with LATERAL join instead of
    individual queries for each segment (reduces 56+ queries to 1 per vehicle).
    """
    cur = conn.cursor()
    
    # Clean old geometry for this vehicle
    cur.execute("DELETE FROM vector.route_geometries WHERE vehicle_id = %s", (vehicle_id,))
    
    if len(route_nodes) < 2:
        cur.close()
        return
    
    # Build pairs of (start, end) nodes for all segments
    segments = [(route_nodes[i], route_nodes[i+1]) for i in range(len(route_nodes) - 1)]
    
    # Batch query: Calculate all route segments in one query using LATERAL join
    # This is MUCH faster than individual queries
    insert_query = """
        INSERT INTO vector.route_geometries (vehicle_id, geom)
        SELECT %s, ST_Multi(ST_Collect(geom ORDER BY seq))
        FROM (
            SELECT UNNEST(%s::bigint[]) as start_node, 
                   UNNEST(%s::bigint[]) as end_node
        ) AS segments
        CROSS JOIN LATERAL (
            SELECT geom, seq
            FROM pgr_dijkstra(
                'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
                segments.start_node,
                segments.end_node,
                directed := false
            ) AS di
            JOIN vector.road_maharashtra ro ON di.edge = ro.gid
        ) AS route_geoms
        WHERE geom IS NOT NULL
        HAVING ST_Collect(geom ORDER BY seq) IS NOT NULL;
    """
    
    start_nodes = [s[0] for s in segments]
    end_nodes = [s[1] for s in segments]
    
    cur.execute(insert_query, (vehicle_id, start_nodes, end_nodes))
    
    conn.commit()
    cur.close()

def fetch_route_geometries_geojson(conn) -> Dict[str, Any]:
    """
    Fetch all route geometries as GeoJSON with vehicle_id properties.
    Returns a GeoJSON FeatureCollection with different features per vehicle.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT vehicle_id, 
               ST_AsGeoJSON(geom)::json as geometry
        FROM vector.route_geometries
        ORDER BY vehicle_id
    """)
    
    features = []
    for row in cur.fetchall():
        features.append({
            "type": "Feature",
            "properties": {
                "vehicle_id": row['vehicle_id']
            },
            "geometry": row['geometry']
        })
    
    cur.close()
    
    return {
        "type": "FeatureCollection",
        "features": features
    }

def fetch_results_summary(conn) -> Dict[str, Any]:
    """
    Fetch optimization results summary including vehicle stats and route geometries.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get vehicle statistics (updated to 10 vehicles)
    cur.execute("""
        SELECT 
            v.id AS vehicle_id,
            COUNT(DISTINCT f.station_id) AS parcel_count,
            COALESCE(SUM(f.parcel_weight), 0) AS total_weight_kg,
            ROUND((SELECT COALESCE(SUM(ST_Length(geom::geography))/1000, 0) 
                   FROM vector.route_geometries 
                   WHERE vehicle_id = v.id)::numeric, 2) AS total_km
        FROM (SELECT generate_series(1,10) AS id) v 
        LEFT JOIN vector.station_node_map f ON v.id = f.vehicle_id
        GROUP BY v.id
        ORDER BY v.id;
    """)
    
    vehicles = [dict(row) for row in cur.fetchall()]
    cur.close()
    
    return {
        "vehicles": vehicles,
        "total_vehicles": len(vehicles),
        "total_deliveries": sum(v['parcel_count'] for v in vehicles),
        "total_distance_km": sum(v['total_km'] for v in vehicles)
    }
