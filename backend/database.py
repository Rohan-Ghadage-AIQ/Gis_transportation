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
    """Create or reset the station_node_map table"""
    cur = conn.cursor()
    cur.execute("""
        DROP TABLE IF EXISTS vector.station_node_map CASCADE;
        CREATE TABLE vector.station_node_map (
            station_id TEXT PRIMARY KEY,
            nearest_node_id BIGINT,
            parcel_weight INT DEFAULT 20,
            service_time INT DEFAULT 10,
            window_start INT DEFAULT 0,
            window_end INT DEFAULT 480,
            vehicle_id INTEGER,
            geom geometry(Point, 4326)
        );
    """)
    conn.commit()
    cur.close()

def insert_stations_from_dataframe(conn, df: pd.DataFrame, warehouse_lon: float = 72.8724, warehouse_lat: float = 19.0725):
    """
    Insert station data from uploaded DataFrame to station_node_map table.
    Snaps each station to the nearest node in the main road network (component 11).
    
    Expected DataFrame columns: id, latitude, longitude (and optionally: parcel_weight, service_time, window_start, window_end)
    """
    cur = conn.cursor()
    
    # Insert stations with nearest node snapping
    for _, row in df.iterrows():
        station_id = str(row['id'])
        lat = float(row['latitude'])
        lon = float(row['longitude'])
        weight = int(row.get('parcel_weight', 20))
        service_time = int(row.get('service_time', 10))
        window_start = int(row.get('window_start', 0))
        window_end = int(row.get('window_end', 480))
        
        cur.execute(f"""
            INSERT INTO vector.station_node_map (station_id, nearest_node_id, parcel_weight, service_time, window_start, window_end, geom)
            SELECT 
                %s,
                (SELECT m.node 
                 FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m
                 JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
                 WHERE m.component = 11 
                 ORDER BY r.geom <-> ST_SetSRID(ST_Point(%s, %s), 4326) LIMIT 1),
                %s, %s, %s, %s,
                ST_SetSRID(ST_Point(%s, %s), 4326)
        """, (station_id, lon, lat, weight, service_time, window_start, window_end, lon, lat))
    
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
    Calculate distance matrix using pgRouting's pgr_dijkstraCost.
    Includes all stations plus the warehouse node.
    """
    cur = conn.cursor()
    
    # Truncate existing matrix
    cur.execute("TRUNCATE TABLE vector.distance_matrix;")
    
    # Calculate distances
    cur.execute(f"""
        INSERT INTO vector.distance_matrix (start_vid, end_vid, agg_cost)
        SELECT start_vid, end_vid, agg_cost
        FROM pgr_dijkstraCost(
            'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
            (SELECT ARRAY_AGG(DISTINCT nearest_node_id) FROM vector.station_node_map) 
            || (SELECT m.node FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m 
                JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
                WHERE m.component = 11 ORDER BY r.geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) LIMIT 1),
            (SELECT ARRAY_AGG(DISTINCT nearest_node_id) FROM vector.station_node_map) 
            || (SELECT m.node FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m 
                JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
                WHERE m.component = 11 ORDER BY r.geom <-> ST_SetSRID(ST_Point({warehouse_lon}, {warehouse_lat}), 4326) LIMIT 1),
            directed := false
        );
    """)
    
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
        ORDER BY station_id
    """)
    rows = cur.fetchall()
    cur.close()
    return [dict(row) for row in rows]

def fetch_distance_matrix(conn, node_ids: List[int]) -> Dict[Tuple[int, int], float]:
    """Fetch distance matrix for given node IDs"""
    cur = conn.cursor()
    node_ids_str = ",".join(map(str, node_ids))
    cur.execute(f"""
        SELECT start_vid, end_vid, agg_cost 
        FROM vector.distance_matrix 
        WHERE start_vid IN ({node_ids_str}) AND end_vid IN ({node_ids_str})
    """)
    
    dist_dict = {}
    for u, v, cost in cur.fetchall():
        dist_dict[(u, v)] = float(cost)
    
    cur.close()
    return dist_dict

def save_route_geometry(conn, vehicle_id: int, route_nodes: List[int]):
    """
    Save road geometries as MultiLineStrings using pgRouting.
    This creates actual road-based routes, not straight lines.
    """
    cur = conn.cursor()
    
    # Clean old geometry for this vehicle
    cur.execute("DELETE FROM vector.route_geometries WHERE vehicle_id = %s", (vehicle_id,))
    
    for i in range(len(route_nodes) - 1):
        start = route_nodes[i]
        end = route_nodes[i+1]
        
        # Find actual road path between two nodes
        insert_query = f"""
            INSERT INTO vector.route_geometries (vehicle_id, geom)
            SELECT {vehicle_id}, ST_Multi(ST_Collect(geom))
            FROM pgr_dijkstra(
                'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
                {start}, {end}, directed := false
            ) AS di
            JOIN vector.road_maharashtra ro ON di.edge = ro.gid
            HAVING ST_Collect(geom) IS NOT NULL;
        """
        cur.execute(insert_query)
    
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
    
    # Get vehicle statistics
    cur.execute("""
        SELECT 
            v.id AS vehicle_id,
            COUNT(DISTINCT f.station_id) AS parcel_count,
            COALESCE(SUM(f.parcel_weight), 0) AS total_weight_kg,
            ROUND((SELECT COALESCE(SUM(ST_Length(geom::geography))/1000, 0) 
                   FROM vector.route_geometries 
                   WHERE vehicle_id = v.id)::numeric, 2) AS total_km
        FROM (SELECT generate_series(1,8) AS id) v 
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
