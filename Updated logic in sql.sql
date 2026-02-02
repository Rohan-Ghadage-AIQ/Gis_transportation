-- restart from scratch
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
-- RUN THIS QUERY TO GET OPTIMIZED ROUTES WITH DISTANCE & WEIGHT CONSTRAINT
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
-----------------------------
-- SELECT vehicle_id, ST_AsText(geom) 
-- FROM vector.route_geometries 
-- WHERE vehicle_id IN (6, 7, 8);
-----------------------------

-- ADD TIME WINDOWS & SERVICE TIME CONSTRAINTS
-- 1. Add time-related columns to your existing map
ALTER TABLE vector.station_node_map 
ADD COLUMN IF NOT EXISTS service_time INT DEFAULT 10,
ADD COLUMN IF NOT EXISTS window_start INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS window_end INT DEFAULT 480;

-- 2. Populate with the random 5-20 min service times
UPDATE vector.station_node_map 
SET service_time = floor(random() * (20-5+1) + 5);

-- 3. Set specific deadlines for testing (9:00 AM is 0 mins)
-- ST01 must be delivered by 10:00 AM (60 mins)
UPDATE vector.station_node_map SET window_end = 60 WHERE station_id = (SELECT station_id FROM vector.station_node_map LIMIT 1);
-- ST02 must be delivered by 10:30 AM (90 mins)
UPDATE vector.station_node_map SET window_end = 90 WHERE station_id = (SELECT station_id FROM vector.station_node_map OFFSET 1 LIMIT 1);

-----------------------------------

SELECT 
    station_id, 
    window_end,
    -- Calculate estimated travel time in minutes (Distance in meters / 500)
    (ST_Distance(geom::geography, ST_SetSRID(ST_Point(72.8724, 19.0725), 4326)::geography) / 500) as est_travel_mins
FROM vector.station_node_map
WHERE (ST_Distance(geom::geography, ST_SetSRID(ST_Point(72.8724, 19.0725), 4326)::geography) / 500) > window_end;

UPDATE vector.station_node_map SET window_end = 90 WHERE station_id = '3616';

SELECT station_id, vehicle_id, window_end 
FROM vector.station_node_map 
WHERE station_id = '3616';

-- This query will tell the total Time of all vehicles to deliver & service time
SELECT 
    SUM(service_time) + SUM(ST_Distance(geom::geography, ST_SetSRID(ST_Point(72.8724, 19.0725), 4326)::geography) / 666) as total_required_mins
FROM vector.station_node_map;
----------------

-- how many parcels each vehicle is carrying and their total weight
SELECT 
    vehicle_id, 
    COUNT(*) as parcel_count, 
    SUM(parcel_weight) as total_weight_kg
FROM vector.station_node_map
WHERE vehicle_id IS NOT NULL
GROUP BY vehicle_id
ORDER BY vehicle_id;

---
-- Check Arrival Times vs. Deadlines
SELECT 
    station_id, 
    vehicle_id, 
    parcel_weight,
    service_time,
    window_end as deadline_mins,
    -- This calculates the 'Clock' version of your deadline for easier reading
    to_char(interval '9 hours' + (window_end * interval '1 minute'), 'HH12:MI AM') as deadline_clock
FROM vector.station_node_map
ORDER BY vehicle_id, window_end;

-------
-- Find the "Impossible" Stations
SELECT 
    station_id, 
    window_end,
    -- Estimated travel in mins at your 40km/h speed
    ROUND((ST_Distance(geom::geography, ST_SetSRID(ST_Point(72.8724, 19.0725), 4326)::geography) / 666)::numeric, 2) as min_travel_mins
FROM vector.station_node_map
WHERE (ST_Distance(geom::geography, ST_SetSRID(ST_Point(72.8724, 19.0725), 4326)::geography) / 666) > window_end;

---------------
-- Update the Window end to 12 Hours shift from 9 AM to 9 PM

UPDATE vector.station_node_map SET window_end = 720 WHERE window_end = 480;
----------------------------
-- Reset windows to 7 AM - 9 PM (0 to 840 mins)
-- Then assign random deadlines within your 3 shifts
UPDATE vector.station_node_map 
SET 
    window_start = 0, 
    window_end = CASE 
        WHEN random() < 0.3 THEN floor(random() * (180-0+1) + 0)   -- Shift 1 (7-10 AM)
        WHEN random() < 0.8 THEN floor(random() * (660-180+1) + 180) -- Shift 2 (10 AM-6 PM)
        ELSE floor(random() * (840-660+1) + 660)                    -- Shift 3 (6-9 PM)
    END;

-- Explicitly set your test cases (Minutes from 7 AM) parcel with 3616 id will deliver at 11 AM.
UPDATE vector.station_node_map SET window_end = 240 WHERE station_id = '3616'; -- 11:00 AM
---------------
-- setting the window end timing for different vehicles 
UPDATE vector.station_node_map 
SET window_end = 180 
WHERE station_id IN ('3504', '3522', '3558');
------------------------

-- Update parcel weights to be a random integer between 10 and 30
UPDATE vector.station_node_map 
SET parcel_weight = floor(random() * (30 - 10 + 1) + 10);
----------

-- sum of the parcels_weight in the data
select sum(parcel_weight) from vector.station_node_map
------------
