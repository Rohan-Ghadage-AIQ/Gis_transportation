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
    """Create or reset the station_node_map table."""
    cur = conn.cursor()
    
    # Terminate any other connections that might be blocking
    cur.execute("""
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE datname = current_database() 
          AND pid <> pg_backend_pid()
          AND state = 'idle in transaction';
    """)
    
    # Try TRUNCATE first
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

def safe_int(val, default=0):
    """Safely convert any value (string, float, etc.) to int"""
    try:
        if val is None: return default
        val_str = str(val).strip()
        if ':' in val_str:
            # print(f"DEBUG: Found colon in '{val_str}', splitting...")
            parts = val_str.split(':')
            try:
                res = int(parts[0]) * 60 + int(parts[1])
                # print(f"DEBUG: Successfully parsed '{val_str}' to {res}")
                return res
            except Exception as e:
                print(f"DEBUG: Failed to parse clock string '{val_str}': {e}")
                return default
        
        if val_str.isdigit():
            return int(val_str)
            
        try:
            return int(float(val_str))
        except:
            # Final attempt: just try int() and see what it says
            try:
                # This is likely where the error message comes from if it's not caught
                return int(val_str)
            except Exception as e:
                if val_str: # only print if not empty
                    print(f"DEBUG: safe_int could not parse '{val_str}', returning default {default}. Error: {e}")
                return default
    except:
        return default

def insert_stations_from_dataframe(conn, df: pd.DataFrame, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725):
    """Insert station data from uploaded DataFrame to station_node_map table."""
    cur = conn.cursor()
    
    # Pre-fetch all nodes in main component (component 11)
    cur.execute("""
        CREATE TEMP TABLE IF NOT EXISTS temp_main_component_nodes AS
        SELECT m.node, r.geom
        FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m
        JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
        WHERE m.component = 11
        GROUP BY m.node, r.geom;
        CREATE INDEX IF NOT EXISTS idx_temp_main_nodes_geom ON temp_main_component_nodes USING GIST (geom);
    """)
    
    print(f"DEBUG: Entering insert_stations_from_dataframe. df length: {len(df)}")
    inserted_count = 0
    for i, row in df.iterrows():
        try:
            # print(f"DEBUG: Processing row {i}")
            station_id = str(row['id'])
            lat = float(row['latitude'])
            lon = float(row['longitude'])
            
            # Use safe_int for ALL numeric columns
            # print(f"DEBUG: Parsing weight from {row.get('parcel_weight')}")
            weight = safe_int(row.get('parcel_weight'), 20)
            
            # print(f"DEBUG: Parsing service_time from {row.get('service_time')}")
            service_time = safe_int(row.get('service_time'), 10)
            
            # print(f"DEBUG: Parsing window_start from {row.get('window_start')}")
            window_start = safe_int(row.get('window_start'), 420)
            
            # Handle window_end (HH:MM:SS or minutes)
            raw_we = row.get('window_end_minutes', row.get('window_end', 600))
            # print(f"DEBUG: Parsing window_end from {raw_we}")
            window_end = safe_int(raw_we, 600)
            
            # Insert with snapping
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
            
            result = cur.fetchone()
            if result and result[0] is not None:
                inserted_count += 1
            else:
                print(f"⚠️  Station {station_id} could not be snapped to road network")
                
        except Exception as e:
            import traceback
            print(f"❌ ERROR processing row {i}: {e}")
            traceback.print_exc()
            continue
    
    print(f"DEBUG: Inserted {inserted_count} out of {len(df)} stations into station_node_map")
    cur.execute("DROP TABLE IF EXISTS temp_main_component_nodes;")
    conn.commit()
    cur.close()

def randomize_station_attributes(conn):
    """Randomize station attributes."""
    cur = conn.cursor()
    cur.execute("UPDATE vector.station_node_map SET service_time = floor(random() * (20-5+1) + 5);")
    cur.execute("UPDATE vector.station_node_map SET window_end = 720 WHERE window_end = 480;")
    cur.execute("""
        UPDATE vector.station_node_map 
        SET window_start = 0, 
            window_end = CASE 
                WHEN random() < 0.3 THEN floor(random() * (180-60+1) + 60)
                WHEN random() < 0.8 THEN floor(random() * (660-240+1) + 240)
                ELSE floor(random() * (840-660+1) + 660)
            END;
    """)
    cur.execute("UPDATE vector.station_node_map SET parcel_weight = floor(random() * (30 - 10 + 1) + 10);")
    conn.commit()
    cur.close()

def calculate_distance_matrix(conn, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725):
    """Calculate distance matrix."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE vector.distance_matrix;")
    warehouse_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    cur.execute("SELECT DISTINCT nearest_node_id FROM vector.station_node_map WHERE nearest_node_id IS NOT NULL")
    station_nodes = [row[0] for row in cur.fetchall()]
    all_nodes = station_nodes + [warehouse_node]
    
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
    conn.commit()
    cur.close()

def get_warehouse_node(conn, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725) -> int:
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
    return [dict(row) for row in rows]

def fetch_distance_matrix(conn, node_ids: List[int]) -> Dict[Tuple[int, int], float]:
    cur = conn.cursor()
    valid_node_ids = [n for n in node_ids if n is not None]
    cur.execute("""
        SELECT start_vid, end_vid, agg_cost
        FROM vector.distance_matrix
        WHERE start_vid = ANY(%s) AND end_vid = ANY(%s)
    """, (valid_node_ids, valid_node_ids))
    rows = cur.fetchall()
    cur.close()
    return {(int(row[0]), int(row[1])): float(row[2]) for row in rows}

def save_route_geometry(conn, vehicle_id: int, route_nodes: List[int]):
    cur = conn.cursor()
    cur.execute("DELETE FROM vector.route_geometries WHERE vehicle_id = %s", (vehicle_id,))
    if len(route_nodes) < 2:
        cur.close()
        return
    segments = [(route_nodes[i], route_nodes[i+1]) for i in range(len(route_nodes) - 1)]
    start_nodes = [s[0] for s in segments]
    end_nodes = [s[1] for s in segments]
    cur.execute("""
        INSERT INTO vector.route_geometries (vehicle_id, geom)
        SELECT %s, ST_Multi(ST_Collect(geom ORDER BY seq))
        FROM (
            SELECT UNNEST(%s::bigint[]) as start_node, UNNEST(%s::bigint[]) as end_node
        ) AS segments
        CROSS JOIN LATERAL (
            SELECT geom, seq
            FROM pgr_dijkstra('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra', segments.start_node, segments.end_node, false) AS di
            JOIN vector.road_maharashtra ro ON di.edge = ro.gid
        ) AS route_geoms
        WHERE geom IS NOT NULL
        HAVING ST_Collect(geom ORDER BY seq) IS NOT NULL;
    """, (vehicle_id, start_nodes, end_nodes))
    conn.commit()
    cur.close()

def fetch_route_geometries_geojson(conn) -> Dict[str, Any]:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT vehicle_id, ST_AsGeoJSON(geom)::json as geometry FROM vector.route_geometries ORDER BY vehicle_id")
    features = [{"type": "Feature", "properties": {"vehicle_id": r['vehicle_id']}, "geometry": r['geometry']} for r in cur.fetchall()]
    cur.close()
    return {"type": "FeatureCollection", "features": features}

def fetch_results_summary(conn) -> Dict[str, Any]:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT v.id AS vehicle_id, COUNT(DISTINCT f.station_id) AS parcel_count, COALESCE(SUM(f.parcel_weight), 0) AS total_weight_kg,
            ROUND((SELECT COALESCE(SUM(ST_Length(geom::geography))/1000, 0) FROM vector.route_geometries WHERE vehicle_id = v.id)::numeric, 2) AS total_km
        FROM (SELECT generate_series(1,10) AS id) v 
        LEFT JOIN vector.station_node_map f ON v.id = f.vehicle_id
        GROUP BY v.id ORDER BY v.id;
    """)
    vehicles = [dict(row) for row in cur.fetchall()]
    cur.close()
    return {"vehicles": vehicles, "total_vehicles": len(vehicles), "total_deliveries": sum(v['parcel_count'] for v in vehicles), "total_distance_km": sum(v['total_km'] for v in vehicles)}
