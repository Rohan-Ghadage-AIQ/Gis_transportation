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
            parts = val_str.split(':')
            try:
                res = int(parts[0]) * 60 + int(parts[1])
                return res
            except Exception as e:
                print(f"DEBUG: Failed to parse clock string '{val_str}': {e}")
                return default
        
        if val_str.isdigit():
            return int(val_str)
            
        try:
            return int(float(val_str))
        except:
            try:
                return int(val_str)
            except Exception as e:
                if val_str:
                    print(f"DEBUG: safe_int could not parse '{val_str}', returning default {default}. Error: {e}")
                return default
    except:
        return default

def insert_stations_from_dataframe(conn, df: pd.DataFrame, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725):
    """Insert station data from uploaded DataFrame to station_node_map table using batch snapping."""
    cur = conn.cursor()
    
    # 1. Clear existing
    cur.execute("TRUNCATE TABLE vector.station_node_map;")
    
    # 2. Create temp table for raw inputs
    cur.execute("DROP TABLE IF EXISTS temp_input_stations;")
    cur.execute("""
        CREATE TEMP TABLE temp_input_stations (
            station_id TEXT,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            weight INT,
            service_time INT,
            window_start INT,
            window_end INT
        );
    """)
    
    # 3. Bulk insert inputs
    data = []
    for _, row in df.iterrows():
        raw_we = row.get('window_end_minutes', row.get('window_end', 600))
        data.append((
            str(row['id']),
            float(row['latitude']),
            float(row['longitude']),
            safe_int(row.get('parcel_weight'), 20),
            safe_int(row.get('service_time'), 10),
            safe_int(row.get('window_start'), 420),
            safe_int(raw_we, 600)
        ))
    
    from psycopg2.extras import execute_values
    execute_values(cur, """
        INSERT INTO temp_input_stations (station_id, lat, lon, weight, service_time, window_start, window_end)
        VALUES %s
    """, data)
    
    # 4. Snap using persistent vector.main_road_nodes (MUCH FASTER)
    cur.execute("""
        INSERT INTO vector.station_node_map (station_id, nearest_node_id, parcel_weight, service_time, window_start, window_end, geom)
        SELECT 
            s.station_id,
            (SELECT node_id 
             FROM vector.main_road_nodes
             ORDER BY geom <-> ST_SetSRID(ST_Point(s.lon, s.lat), 4326) 
             LIMIT 1),
            s.weight, s.service_time, s.window_start, s.window_end,
            ST_SetSRID(ST_Point(s.lon, s.lat), 4326)
        FROM temp_input_stations s;
    """)
    
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
    """Calculate distance matrix using spatial filtering to avoid loading 800k roads."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE vector.distance_matrix;")
    warehouse_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)
    
    # Get bounding box of all stations to avoid subquery in Dijkstra
    cur.execute("SELECT ST_Extent(geom) FROM vector.station_node_map")
    extent = cur.fetchone()[0]
    if not extent:
        cur.close()
        return

    # Get all nodes
    cur.execute("""
        SELECT nearest_node_id FROM vector.station_node_map WHERE nearest_node_id IS NOT NULL
        UNION 
        SELECT %s as nearest_node_id
    """, (warehouse_node,))
    all_nodes = [row[0] for row in cur.fetchall() if row[0] is not None]

    # Spatial Filter: Pass extent as literal to pgRouting
    cur.execute("""
        INSERT INTO vector.distance_matrix (start_vid, end_vid, agg_cost)
        SELECT start_vid, end_vid, agg_cost
        FROM pgr_dijkstraCost(
            format('SELECT gid AS id, source, target, COALESCE(live_cost_s, cost_s) AS cost 
                    FROM vector.road_maharashtra 
                    WHERE geom && ST_Expand(ST_SetSRID(%%L::box2d::geometry, 4326), 0.3)', %s),
            %s::bigint[],
            %s::bigint[],
            directed := false
        )
    """, (extent, all_nodes, all_nodes))
    conn.commit()
    cur.close()

def get_warehouse_node(conn, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725) -> int:
    """Get nearest road node for warehouse using persistent table."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT node_id 
        FROM vector.main_road_nodes
        ORDER BY geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) 
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

def save_all_route_geometries(conn, all_routes_data: List[Dict[str, Any]]):
    """
    Save route geometries for ALL vehicles in a single large query using true global batching.
    all_routes_data: List of {'vehicle_id': int, 'route_nodes': List[int]}
    """
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE vector.route_geometries;")
    
    # Ensure columns exist
    cur.execute("""
        ALTER TABLE vector.route_geometries 
        ADD COLUMN IF NOT EXISTS segment_index integer DEFAULT 0,
        ADD COLUMN IF NOT EXISTS avg_traffic_factor real DEFAULT 1.0;
    """)
    
    # Filter valid routes
    routes_to_process = [r for r in all_routes_data if len(r['route_nodes']) >= 2]
    if not routes_to_process:
        cur.close()
        return

    # 1. Get GLOBAL bounding box once (instead of per-vehicle)
    all_nodes = []
    for r in routes_to_process:
        all_nodes.extend(r['route_nodes'])
    
    cur.execute("SELECT ST_Extent(geom) FROM vector.main_road_nodes WHERE node_id = ANY(%s)", (list(set(all_nodes)),))
    global_extent = cur.fetchone()[0]
    if not global_extent:
        cur.close()
        return

    # 2. Process each vehicle using the shared global extent
    for route_info in routes_to_process:
        v_id = route_info['vehicle_id']
        route_nodes = route_info['route_nodes']

        cur.execute("""
            INSERT INTO vector.route_geometries (vehicle_id, segment_index, geom, avg_traffic_factor)
            SELECT 
                %s,
                s.idx,
                ST_Multi(ST_Collect(ro.geom ORDER BY di.seq)),
                COALESCE(AVG(ro.traffic_factor), 1.0)
            FROM (
                SELECT idx - 1 as idx, route[idx] as start_node, route[idx+1] as end_node
                FROM generate_series(1, array_length(%s::bigint[], 1) - 1) idx
                CROSS JOIN (SELECT %s::bigint[] as route) r
            ) s
            CROSS JOIN LATERAL pgr_dijkstra(
                format('SELECT gid AS id, source, target, COALESCE(live_cost_s, cost_s) AS cost 
                        FROM vector.road_maharashtra 
                        WHERE geom && ST_Expand(ST_SetSRID(%%L::box2d::geometry, 4326), 0.1)', %s),
                s.start_node, s.end_node, false
            ) AS di
            JOIN vector.road_maharashtra ro ON di.edge = ro.gid
            WHERE ro.geom IS NOT NULL
            GROUP BY s.idx, s.start_node, s.end_node;
        """, (v_id, route_nodes, route_nodes, global_extent))
    
    conn.commit()
    cur.close()

def save_route_geometry(conn, vehicle_id: int, route_nodes: List[int]):
    """Compatibility wrapper for save_route_geometry."""
    save_all_route_geometries(conn, [{'vehicle_id': vehicle_id, 'route_nodes': route_nodes}])

def fetch_route_geometries_geojson(conn) -> Dict[str, Any]:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Ensure traffic columns exist (safe for old data created before schema change)
    cur.execute("""
        ALTER TABLE vector.route_geometries 
        ADD COLUMN IF NOT EXISTS segment_index integer DEFAULT 0,
        ADD COLUMN IF NOT EXISTS avg_traffic_factor real DEFAULT 1.0;
    """)
    conn.commit()
    cur.execute("""
        SELECT vehicle_id, segment_index,
               COALESCE(avg_traffic_factor, 1.0) as traffic_factor,
               ST_AsGeoJSON(geom)::json as geometry 
        FROM vector.route_geometries 
        ORDER BY vehicle_id, segment_index
    """)
    features = []
    for r in cur.fetchall():
        tf = float(r.get('traffic_factor', 1.0))
        # Map traffic factor to color
        if tf >= 2.0:
            traffic_color = "#DC2626"   # Red - heavy
        elif tf >= 1.5:
            traffic_color = "#F97316"   # Orange - moderate
        elif tf >= 1.1:
            traffic_color = "#EAB308"   # Yellow - light
        else:
            traffic_color = "#22C55E"   # Green - free flow
        
        features.append({
            "type": "Feature",
            "properties": {
                "vehicle_id": r['vehicle_id'],
                "segment_index": r.get('segment_index', 0),
                "traffic_factor": round(tf, 2),
                "traffic_color": traffic_color
            },
            "geometry": r['geometry']
        })
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

def update_road_traffic_factor(conn, lat: float, lon: float, factor: float, radius_km: float = 2.0):
    """Legacy single-point update. Use batch_update_traffic_factors for performance."""
    batch_update_traffic_factors(conn, [(lat, lon, factor, radius_km)])

def batch_update_traffic_factors(conn, updates: List[tuple]):
    """
    Batch update traffic_factor for roads near multiple points in ONE query.
    updates: List of (lat, lon, factor, radius_km) tuples.
    Uses geometry bounding box (&&) with ST_Expand for spatial index usage.
    """
    if not updates:
        return
    cur = conn.cursor()
    try:
        # 1. Create temp table with all update points
        cur.execute("DROP TABLE IF EXISTS _tmp_traffic_updates;")
        cur.execute("""
            CREATE TEMP TABLE _tmp_traffic_updates (
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION, 
                factor REAL,
                radius_deg DOUBLE PRECISION
            );
        """)
        
        # 2. Bulk insert - convert km to degrees (at ~19°N: 1km ≈ 0.01 deg)
        from psycopg2.extras import execute_values
        execute_values(cur, """
            INSERT INTO _tmp_traffic_updates (lat, lon, factor, radius_deg) VALUES %s
        """, [(lat, lon, factor, radius_km * 0.01) for lat, lon, factor, radius_km in updates])
        
        # 3. Add a spatial index on the temp point geometries for the join
        cur.execute("""
            ALTER TABLE _tmp_traffic_updates ADD COLUMN geom geometry(Point, 4326);
        """)
        cur.execute("""
            UPDATE _tmp_traffic_updates SET geom = ST_SetSRID(ST_Point(lon, lat), 4326);
        """)
        cur.execute("""
            CREATE INDEX ON _tmp_traffic_updates USING GIST (geom);
        """)
        
        # 4. Single spatial join using && (bounding box) — uses GiST index on road_maharashtra
        cur.execute("""
            UPDATE vector.road_maharashtra r
            SET traffic_factor = t.max_factor,
                live_cost_s = r.cost_s * t.max_factor,
                live_reverse_cost_s = r.reverse_cost_s * t.max_factor,
                last_traffic_update = NOW()
            FROM (
                SELECT r2.gid, MAX(u.factor) as max_factor
                FROM vector.road_maharashtra r2
                JOIN _tmp_traffic_updates u
                ON r2.geom && ST_Expand(u.geom, u.radius_deg)
                GROUP BY r2.gid
            ) t
            WHERE r.gid = t.gid;
        """)
        
        cur.execute("DROP TABLE IF EXISTS _tmp_traffic_updates;")
    except Exception as e:
        print(f"❌ Error in batch traffic update: {e}")
        conn.rollback()
    finally:
        cur.close()

def reset_traffic_factors(conn):
    """Reset only roads that were previously modified (not all 843K roads)."""
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE vector.road_maharashtra 
            SET traffic_factor = 1.0,
                live_cost_s = cost_s,
                live_reverse_cost_s = reverse_cost_s,
                last_traffic_update = NULL
            WHERE last_traffic_update IS NOT NULL;
        """)
        conn.commit()
    except Exception as e:
        print(f"❌ Error resetting traffic factors: {e}")
        conn.rollback()
    finally:
        cur.close()

def get_current_route_states(conn) -> Dict[int, List[int]]:
    """
    Get current sequence of station IDs for each vehicle.
    Returns: {vehicle_id: [station_id1, station_id2, ...]}
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_id, station_id 
        FROM vector.station_node_map 
        WHERE vehicle_id IS NOT NULL 
        ORDER BY vehicle_id, arrival_time
    """)
    rows = cur.fetchall()
    cur.close()
    
    states: Dict[int, List] = {}
    for vid, sid in rows:
        if vid not in states:
            states[vid] = []
        states[vid].append(sid)
    return states


# ──────────────────────────────────────────
# Fleet Vehicle Management
# ──────────────────────────────────────────

# Default fleet (mirrors the previously hard-coded values in vrp_solver.py)
DEFAULT_FLEET = [
    {"name": "Vehicle 1",  "capacity_kg": 175, "cost_per_km": 15, "shift_start": 540,  "shift_end": 1080},
    {"name": "Vehicle 2",  "capacity_kg": 261, "cost_per_km": 20, "shift_start": 540,  "shift_end": 1080},
    {"name": "Vehicle 3",  "capacity_kg": 348, "cost_per_km": 25, "shift_start": 420,  "shift_end": 900},
    {"name": "Vehicle 4",  "capacity_kg": 156, "cost_per_km": 12, "shift_start": 420,  "shift_end": 1080},
    {"name": "Vehicle 5",  "capacity_kg": 178, "cost_per_km": 15, "shift_start": 540,  "shift_end": 1020},
    {"name": "Vehicle 6",  "capacity_kg": 142, "cost_per_km": 12, "shift_start": 480,  "shift_end": 1080},
    {"name": "Vehicle 7",  "capacity_kg": 118, "cost_per_km": 10, "shift_start": 480,  "shift_end": 1260},
    {"name": "Vehicle 8",  "capacity_kg": 125, "cost_per_km": 10, "shift_start": 420,  "shift_end": 1200},
    {"name": "Vehicle 9",  "capacity_kg": 200, "cost_per_km": 12, "shift_start": 420,  "shift_end": 1140},
    {"name": "Vehicle 10", "capacity_kg": 180, "cost_per_km": 14, "shift_start": 480,  "shift_end": 1200},
]

def ensure_fleet_table(conn):
    """Create fleet_vehicles table if it doesn't exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vector.fleet_vehicles (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            capacity_kg INTEGER NOT NULL,
            cost_per_km NUMERIC(6,2) NOT NULL,
            shift_start INTEGER NOT NULL,
            shift_end INTEGER NOT NULL
        );
    """)
    conn.commit()
    cur.close()

def seed_default_fleet(conn):
    """Insert default vehicles if table is empty."""
    ensure_fleet_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vector.fleet_vehicles;")
    count = cur.fetchone()[0]
    if count == 0:
        for v in DEFAULT_FLEET:
            cur.execute("""
                INSERT INTO vector.fleet_vehicles (name, capacity_kg, cost_per_km, shift_start, shift_end)
                VALUES (%s, %s, %s, %s, %s)
            """, (v["name"], v["capacity_kg"], v["cost_per_km"], v["shift_start"], v["shift_end"]))
        conn.commit()
        print(f"🚛 Seeded {len(DEFAULT_FLEET)} default vehicles.")
    cur.close()

def get_fleet_vehicles(conn) -> List[Dict[str, Any]]:
    """Get all fleet vehicles, ordered by id. Seeds defaults if empty."""
    ensure_fleet_table(conn)
    seed_default_fleet(conn)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM vector.fleet_vehicles ORDER BY id;")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    # Convert Decimal to float for JSON serialization
    for r in rows:
        r['cost_per_km'] = float(r['cost_per_km'])
    return rows

def upsert_fleet_vehicle(conn, data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a fleet vehicle. If 'id' is present, update; otherwise insert."""
    ensure_fleet_table(conn)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    vehicle_id = data.get("id")
    if vehicle_id:
        cur.execute("""
            UPDATE vector.fleet_vehicles
            SET name = %s, capacity_kg = %s, cost_per_km = %s, shift_start = %s, shift_end = %s
            WHERE id = %s
            RETURNING *;
        """, (data["name"], data["capacity_kg"], data["cost_per_km"],
              data["shift_start"], data["shift_end"], vehicle_id))
    else:
        cur.execute("""
            INSERT INTO vector.fleet_vehicles (name, capacity_kg, cost_per_km, shift_start, shift_end)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *;
        """, (data["name"], data["capacity_kg"], data["cost_per_km"],
              data["shift_start"], data["shift_end"]))
    result = dict(cur.fetchone())
    conn.commit()
    cur.close()
    result['cost_per_km'] = float(result['cost_per_km'])
    return result

def delete_fleet_vehicle(conn, vehicle_id: int) -> bool:
    """Delete a fleet vehicle by id. Returns True if deleted."""
    cur = conn.cursor()
    cur.execute("DELETE FROM vector.fleet_vehicles WHERE id = %s;", (vehicle_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    cur.close()
    return deleted
