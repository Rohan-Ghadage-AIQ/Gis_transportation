-- Add traffic columns to road network
ALTER TABLE vector.road_maharashtra ADD COLUMN IF NOT EXISTS traffic_factor DOUBLE PRECISION DEFAULT 1.0;
ALTER TABLE vector.road_maharashtra ADD COLUMN IF NOT EXISTS live_cost_s DOUBLE PRECISION;
ALTER TABLE vector.road_maharashtra ADD COLUMN IF NOT EXISTS live_reverse_cost_s DOUBLE PRECISION;
ALTER TABLE vector.road_maharashtra ADD COLUMN IF NOT EXISTS last_traffic_update TIMESTAMP;

-- Initialize live columns to static costs
UPDATE vector.road_maharashtra SET live_cost_s = cost_s WHERE live_cost_s IS NULL;
UPDATE vector.road_maharashtra SET live_reverse_cost_s = reverse_cost_s WHERE live_reverse_cost_s IS NULL;
