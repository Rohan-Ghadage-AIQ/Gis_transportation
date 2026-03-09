"""
Maintenance Team Planning — Database Functions
Completely separate from the logistics station_node_map tables.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from typing import List, Dict, Any
import pandas as pd
from database import get_db_connection, safe_int, get_warehouse_node


# ──────────────────────────────────────────
# Table Setup
# ──────────────────────────────────────────

def setup_maintenance_tables(conn):
    """Create (or reset) the maintenance-specific tables. Never touches logistics tables."""
    cur = conn.cursor()

    # Task table
    try:
        cur.execute("TRUNCATE TABLE vector.maintenance_task_node_map;")
        conn.commit()
    except Exception:
        conn.rollback()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vector.maintenance_task_node_map (
                task_id          TEXT PRIMARY KEY,
                company_name     TEXT,
                address          TEXT,
                service_time     INT DEFAULT 30,
                slot_start       INT DEFAULT 420,
                slot_end         INT DEFAULT 600,
                nearest_node_id  BIGINT,
                technician_id    INTEGER,
                arrival_time     TEXT,
                task_status      TEXT,
                geom             geometry(Point, 4326)
            );
        """)
        conn.commit()

    # Route geometries (separate from logistics)
    try:
        cur.execute("TRUNCATE TABLE vector.maintenance_route_geometries;")
        conn.commit()
    except Exception:
        conn.rollback()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vector.maintenance_route_geometries (
                vehicle_id          INTEGER,
                segment_index       INTEGER DEFAULT 0,
                geom                geometry,
                avg_traffic_factor  REAL DEFAULT 1.0
            );
        """)
        conn.commit()

    # Unassigned maintenance tasks
    try:
        cur.execute("TRUNCATE TABLE vector.maintenance_unassigned;")
        conn.commit()
    except Exception:
        conn.rollback()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vector.maintenance_unassigned (
                task_id TEXT PRIMARY KEY,
                reason  TEXT NOT NULL,
                latitude  DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                service_time INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

    cur.close()


# ──────────────────────────────────────────
# Insert Tasks
# ──────────────────────────────────────────

def insert_maintenance_tasks(conn, df: pd.DataFrame):
    """Insert tasks from the parsed tasks DataFrame into maintenance_task_node_map."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE vector.maintenance_task_node_map;")

    # Temp table for batch snapping
    cur.execute("DROP TABLE IF EXISTS _tmp_maint_input;")
    cur.execute("""
        CREATE TEMP TABLE _tmp_maint_input (
            task_id     TEXT,
            company_name TEXT,
            address     TEXT,
            lat         DOUBLE PRECISION,
            lon         DOUBLE PRECISION,
            service_time INT,
            slot_start  INT,
            slot_end    INT
        );
    """)

    data = []
    for _, row in df.iterrows():
        data.append((
            str(row['id']),
            str(row.get('company_name', '')),
            str(row.get('address', '')),
            float(row['latitude']),
            float(row['longitude']),
            safe_int(row.get('service_time', 30), 30),
            safe_int(row.get('slot_start', 420), 420),
            safe_int(row.get('slot_end', 600), 600),
        ))

    execute_values(cur, """
        INSERT INTO _tmp_maint_input (task_id, company_name, address, lat, lon, service_time, slot_start, slot_end)
        VALUES %s
    """, data)

    # Snap to nearest road node using persistent main_road_nodes table
    cur.execute("""
        INSERT INTO vector.maintenance_task_node_map
            (task_id, company_name, address, service_time, slot_start, slot_end, nearest_node_id, geom)
        SELECT
            s.task_id, s.company_name, s.address,
            s.service_time, s.slot_start, s.slot_end,
            (SELECT node_id FROM vector.main_road_nodes
             ORDER BY geom <-> ST_SetSRID(ST_Point(s.lon, s.lat), 4326) LIMIT 1),
            ST_SetSRID(ST_Point(s.lon, s.lat), 4326)
        FROM _tmp_maint_input s;
    """)

    conn.commit()
    cur.close()


# ──────────────────────────────────────────
# Fetch Tasks (mirrors fetch_station_data)
# ──────────────────────────────────────────

def fetch_maintenance_tasks(conn) -> List[Dict[str, Any]]:
    """Fetch all maintenance tasks with node IDs."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT task_id AS station_id, company_name,
               nearest_node_id, service_time,
               slot_start AS window_start, slot_end AS window_end,
               ST_X(geom) AS longitude, ST_Y(geom) AS latitude
        FROM vector.maintenance_task_node_map
        WHERE nearest_node_id IS NOT NULL
        ORDER BY task_id
    """)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────
# Distance Matrix (reuses logistics road network)
# ──────────────────────────────────────────

def calculate_maintenance_distance_matrix(conn, warehouse_lon: float, warehouse_lat: float):
    """Calculate distance matrix for maintenance tasks using the same road network."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE vector.distance_matrix;")
    wh_node = get_warehouse_node(conn, warehouse_lon, warehouse_lat)

    cur.execute("""
        SELECT nearest_node_id FROM vector.maintenance_task_node_map WHERE nearest_node_id IS NOT NULL
        UNION
        SELECT %s AS nearest_node_id
    """, (wh_node,))
    all_nodes = [row[0] for row in cur.fetchall() if row[0] is not None]

    cur.execute("SELECT ST_Extent(geom) FROM vector.maintenance_task_node_map")
    extent = cur.fetchone()[0]
    if not extent:
        cur.close()
        return

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


# ──────────────────────────────────────────
# Route Geometry (separate table)
# ──────────────────────────────────────────

def save_maintenance_route_geometries(conn, all_routes_data: List[Dict[str, Any]]):
    """Save route geometries for maintenance vehicles. Same logic as logistics but writes to maintenance table."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE vector.maintenance_route_geometries;")

    routes_to_process = [r for r in all_routes_data if len(r['route_nodes']) >= 2]
    if not routes_to_process:
        cur.close()
        return

    all_nodes = []
    for r in routes_to_process:
        all_nodes.extend(r['route_nodes'])

    cur.execute("SELECT ST_Extent(geom) FROM vector.main_road_nodes WHERE node_id = ANY(%s)", (list(set(all_nodes)),))
    global_extent = cur.fetchone()[0]
    if not global_extent:
        cur.close()
        return

    for route_info in routes_to_process:
        v_id = route_info['vehicle_id']
        route_nodes = route_info['route_nodes']

        cur.execute("""
            INSERT INTO vector.maintenance_route_geometries (vehicle_id, segment_index, geom, avg_traffic_factor)
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


# ──────────────────────────────────────────
# Fetch Route GeoJSON (for map display)
# ──────────────────────────────────────────

def fetch_maintenance_route_geojson(conn) -> Dict[str, Any]:
    """Fetch route geometries as GeoJSON for the maintenance module."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT vehicle_id, segment_index,
               COALESCE(avg_traffic_factor, 1.0) AS traffic_factor,
               ST_AsGeoJSON(geom)::json AS geometry
        FROM vector.maintenance_route_geometries
        ORDER BY vehicle_id, segment_index
    """)
    features = []
    for r in cur.fetchall():
        tf = float(r.get('traffic_factor', 1.0))
        if tf >= 2.0:
            traffic_color = "#DC2626"
        elif tf >= 1.5:
            traffic_color = "#F97316"
        elif tf >= 1.1:
            traffic_color = "#EAB308"
        else:
            traffic_color = "#22C55E"
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


# ──────────────────────────────────────────
# Results Summary
# ──────────────────────────────────────────

def fetch_maintenance_results_summary(conn, num_technicians: int) -> Dict[str, Any]:
    """Fetch route summary for maintenance, same pattern as logistics."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT v.id AS vehicle_id,
               COUNT(DISTINCT f.task_id) AS task_count,
               COALESCE(SUM(f.service_time), 0) AS total_service_mins,
               ROUND((SELECT COALESCE(SUM(ST_Length(geom::geography))/1000, 0)
                       FROM vector.maintenance_route_geometries WHERE vehicle_id = v.id)::numeric, 2) AS total_km
        FROM (SELECT generate_series(1, %s) AS id) v
        LEFT JOIN vector.maintenance_task_node_map f ON v.id = f.technician_id
        GROUP BY v.id ORDER BY v.id;
    """, (num_technicians,))
    vehicles = [dict(row) for row in cur.fetchall()]
    cur.close()
    return {
        "vehicles": vehicles,
        "total_vehicles": len(vehicles),
        "total_tasks": sum(v['task_count'] for v in vehicles),
        "total_distance_km": sum(float(v['total_km']) for v in vehicles)
    }
