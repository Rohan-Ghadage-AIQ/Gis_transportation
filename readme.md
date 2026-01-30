```
-- Updated Query - SQL
-- 1. Reset the Mapping Table
DROP TABLE IF EXISTS vector.station_node_map CASCADE;
CREATE TABLE vector.station_node_map (
    station_id TEXT PRIMARY KEY,
    nearest_node_id BIGINT,
    parcel_weight INT DEFAULT 20,
    geom geometry(Point, 4326)
);

-- 2. Populate from your current sample table (e.g., sample_1_data)
-- This logic snaps your 60 points to the main road network (Component 11)
INSERT INTO vector.station_node_map (station_id, nearest_node_id, geom)
SELECT 
    id,
    (SELECT m.node 
     FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m
     JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
     WHERE m.component = 11 
     ORDER BY r.geom <-> s.geom LIMIT 1),
    geom
FROM vector.sample_1_data s; -- Change this table name for switching data

-----------------------------------------------------

-- 1. Clear the old matrix
TRUNCATE TABLE vector.distance_matrix;
-- Insert data into distance matrix
-- 2. Calculate costs between all nodes currently in the map (60 + Warehouse)
INSERT INTO vector.distance_matrix (start_vid, end_vid, agg_cost)
SELECT start_vid, end_vid, agg_cost
FROM pgr_dijkstraCost(
    'SELECT gid AS id, source, target, cost FROM vector.road_maharashtra',
    (SELECT ARRAY_AGG(DISTINCT nearest_node_id) FROM vector.station_node_map) 
    || (SELECT m.node FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m 
        JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
        WHERE m.component = 11 ORDER BY r.geom <-> ST_SetSRID(ST_Point(72.8724, 19.0725), 4326) LIMIT 1),
    (SELECT ARRAY_AGG(DISTINCT nearest_node_id) FROM vector.station_node_map) 
    || (SELECT m.node FROM pgr_connectedComponents('SELECT gid AS id, source, target, cost FROM vector.road_maharashtra') m 
        JOIN vector.road_maharashtra r ON (r.source = m.node OR r.target = m.node)
        WHERE m.component = 11 ORDER BY r.geom <-> ST_SetSRID(ST_Point(72.8724, 19.0725), 4326) LIMIT 1),
    directed := false
);
------------------------------------------
SELECT * FROM vector.distance_matrix;
----------------
SELECT * FROM vector.final_station_clusters;
----------------
SELECT * FROM vector.route_geometries;
----------------
-- This query checks how many distance pairs exist for the stations currently in your map
SELECT 
    (SELECT COUNT(*) FROM vector.station_node_map) as stations_in_map,
    COUNT(dm.*) as matching_distances_found
FROM vector.distance_matrix dm
WHERE dm.start_vid IN (SELECT nearest_node_id FROM vector.station_node_map)
  AND dm.end_vid IN (SELECT nearest_node_id FROM vector.station_node_map);

  -------

  SELECT COUNT(*) FROM vector.distance_matrix 
WHERE start_vid = 175614 OR end_vid = 175614;

---------------

SELECT 
    cluster_id AS vehicle_id,
    COUNT(station_id) AS parcel_count,
    SUM(weight) AS total_weight_kg
FROM vector.final_station_clusters
GROUP BY cluster_id
ORDER BY cluster_id;

------------------------
-- Run all queries till here after this run the python script and then below query

SELECT 
    v.id AS vehicle_id,
    COUNT(DISTINCT f.station_id) AS parcel_count,
    COALESCE(SUM(f.weight), 0) AS total_weight_kg,
    ROUND((SELECT COALESCE(SUM(ST_Length(geom::geography))/1000, 0) 
           FROM vector.route_geometries 
           WHERE vehicle_id = v.id)::numeric, 2) AS total_km
FROM (SELECT generate_series(1,8) AS id) v 
LEFT JOIN vector.final_station_clusters f ON v.id = f.cluster_id
GROUP BY v.id
ORDER BY v.id;

```
### Run the script solve_clusters.py
## see output in console
![Console output](image-1.png)

## run the last block of SQL query 
![SQL output](image.png)

## Updated logic - output 
![SQL query output](image-2.png)

## After Adding Time window constraints
![VRP Time ZWindow](image-3.png)

# Run this query to get overview of vehicle id, time window, service time window
```
SELECT * FROM vector.station_node_map
ORDER BY station_id ASC 
```
![alt text](image-4.png)

# Final Console Output 
```

PS C:\Users\91832\Desktop\AIQ\GisTransportation2> python solve_clusters.py

==================================================
SUCCESS: SAVING ROUTES & CALCULATING ARRIVAL TIMES
==================================================

--- Vehicle 1 Route ---
Warehouse (Start) | Clock-in: 09:00 AM
Warehouse       | Arrives: 09:00 AM [IDEAL]
Station 3490    | Arrives: 09:39 AM [IDEAL]
Station 11625   | Arrives: 09:58 AM [IN BUFFER]
Station 3645    | Arrives: 10:38 AM [IDEAL]
Station 3597    | Arrives: 11:23 AM [IN BUFFER]
Station 3666    | Arrives: 11:45 AM [IN BUFFER]
Station 3661    | Arrives: 12:00 PM [IDEAL]
Station 3657    | Arrives: 12:18 PM [IDEAL]
Station 3566    | Arrives: 12:44 PM [IDEAL]
Warehouse (End) | Arrives: 02:09 PM
Total Work Duration: 309 minutes [ON TIME]
Vehicle 1: Geometry and assignments saved.

--- Vehicle 2 Route ---
Warehouse (Start) | Clock-in: 09:00 AM
Warehouse       | Arrives: 09:00 AM [IDEAL]
Station 3166    | Arrives: 09:03 AM [IDEAL]
Station 3105    | Arrives: 09:28 AM [IDEAL]
Station 3163    | Arrives: 09:52 AM [IN BUFFER]
Station 3151    | Arrives: 10:10 AM [IDEAL]
Station 3156    | Arrives: 10:30 AM [IDEAL]
Station 3157    | Arrives: 10:46 AM [IDEAL]
Warehouse (End) | Arrives: 11:13 AM
Total Work Duration: 133 minutes [ON TIME]
Vehicle 2: Geometry and assignments saved.

--- Vehicle 3 Route ---
Warehouse (Start) | Clock-in: 07:00 AM
Warehouse       | Arrives: 07:00 AM [IDEAL]
Station 3169    | Arrives: 07:07 AM [IDEAL]
Station 11603   | Arrives: 07:50 AM [IN BUFFER]
Station 3455    | Arrives: 08:18 AM [IDEAL]
Station 3472    | Arrives: 08:41 AM [IDEAL]
Station 3476    | Arrives: 08:48 AM [IN BUFFER]
Station 3485    | Arrives: 09:23 AM [IDEAL]
Station 3499    | Arrives: 09:40 AM [IDEAL]
Station 3449    | Arrives: 09:51 AM [IDEAL]
Warehouse (End) | Arrives: 10:30 AM
Total Work Duration: 210 minutes [ON TIME]
Vehicle 3: Geometry and assignments saved.

--- Vehicle 4 Route ---
Warehouse (Start) | Clock-in: 07:00 AM
Warehouse       | Arrives: 07:00 AM [IDEAL]
Station 3535    | Arrives: 07:53 AM [IDEAL]
Station 3546    | Arrives: 08:07 AM [IDEAL]
Station 3534    | Arrives: 08:30 AM [IDEAL]
Station 3526    | Arrives: 08:37 AM [IDEAL]
Station 3520    | Arrives: 08:56 AM [IDEAL]
Station 3522    | Arrives: 09:19 AM [IN BUFFER]
Station 3510    | Arrives: 09:38 AM [IN BUFFER]
Station 3504    | Arrives: 10:00 AM [IN BUFFER]
Warehouse (End) | Arrives: 10:57 AM
Total Work Duration: 237 minutes [ON TIME]
Vehicle 4: Geometry and assignments saved.

--- Vehicle 5 Route ---
Warehouse (Start) | Clock-in: 09:00 AM
Warehouse       | Arrives: 09:00 AM [IDEAL]
Station 3025    | Arrives: 09:16 AM [IN BUFFER]
Station 3067    | Arrives: 09:29 AM [IDEAL]
Station 3061    | Arrives: 09:40 AM [IDEAL]
Station 3046    | Arrives: 10:00 AM [IDEAL]
Station 3063    | Arrives: 10:09 AM [IDEAL]
Station 3135    | Arrives: 10:43 AM [IDEAL]
Station 3132    | Arrives: 10:57 AM [IDEAL]
Station 3011    | Arrives: 11:15 AM [IN BUFFER]
Warehouse (End) | Arrives: 11:31 AM
Total Work Duration: 151 minutes [ON TIME]
Vehicle 5: Geometry and assignments saved.

--- Vehicle 6 Route ---
Warehouse (Start) | Clock-in: 08:00 AM
Warehouse       | Arrives: 08:00 AM [IDEAL]
Station 11606   | Arrives: 08:30 AM [IN BUFFER]
Station 3629    | Arrives: 09:16 AM [IN BUFFER]
Station 12204   | Arrives: 10:37 AM [IN BUFFER]
Station 12205   | Arrives: 10:57 AM [IN BUFFER]
Station 12217   | Arrives: 11:51 AM [IDEAL]
Station 12201   | Arrives: 12:07 PM [IDEAL]
Station 12199   | Arrives: 01:29 PM [IDEAL]
Station 3052    | Arrives: 02:27 PM [IN BUFFER]
Warehouse (End) | Arrives: 03:11 PM
Total Work Duration: 431 minutes [ON TIME]
Vehicle 6: Geometry and assignments saved.

--- Vehicle 7 Route ---
Warehouse (Start) | Clock-in: 08:00 AM
Warehouse       | Arrives: 08:00 AM [IDEAL]
Station 2987    | Arrives: 08:20 AM [IN BUFFER]
Station 2980    | Arrives: 08:36 AM [IDEAL]
Station 2978    | Arrives: 08:54 AM [IDEAL]
Station 3013    | Arrives: 09:20 AM [IDEAL]
Station 3162    | Arrives: 09:37 AM [IN BUFFER]
Station 3150    | Arrives: 09:57 AM [IDEAL]
Warehouse (End) | Arrives: 10:28 AM
Total Work Duration: 148 minutes [ON TIME]
Vehicle 7: Geometry and assignments saved.

--- Vehicle 8 Route ---
Warehouse (Start) | Clock-in: 07:00 AM
Warehouse       | Arrives: 07:00 AM [IDEAL]
Station 3137    | Arrives: 07:14 AM [IN BUFFER]
Station 3558    | Arrives: 08:34 AM [IDEAL]
Station 3577    | Arrives: 08:49 AM [IN BUFFER]
Station 3580    | Arrives: 09:13 AM [IN BUFFER]
Station 3588    | Arrives: 09:36 AM [IDEAL]
Station 3562    | Arrives: 09:52 AM [IDEAL]
Station 3616    | Arrives: 11:00 AM [IN BUFFER]
Station 3617    | Arrives: 11:23 AM [IDEAL]
Warehouse (End) | Arrives: 01:07 PM
Total Work Duration: 367 minutes [ON TIME]
Vehicle 8: Geometry and assignments saved.

Success: Balanced weight and road routes saved to database.
```