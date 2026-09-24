import rasterio
import numpy as np
import osmnx as ox
import geopandas as gpd
from shapely.geometry import Point, LineString
import pandas as pd
import math

def densify_geometry(line, step=10):
    """Returns a list of points spaced by `step` meters along the line."""
    length = line.length
    if length < step:
        # If the line is very short, just use the midpoint
        return [line.interpolate(length / 2)]
    
    # Create points at regular intervals
    points = []
    distances = np.arange(0, length, step)
    for dist in distances:
        points.append(line.interpolate(dist))
    # Add the end point just in case
    points.append(line.interpolate(length))
    return points

def find_depressions(points, elevations, depth_threshold=0.3):
    """
    Finds local minima in the elevation profile that are lower than
    their neighbors by at least depth_threshold.
    """
    depressions = []
    if len(elevations) < 3:
        return depressions

    for i in range(1, len(elevations) - 1):
        z = elevations[i]
        # Check if it is a local minimum
        if z < elevations[i-1] and z < elevations[i+1]:
            # Calculate depth from adjacent points
            depth = min(elevations[i-1] - z, elevations[i+1] - z)
            if depth >= depth_threshold:
                depressions.append((points[i], z, depth))
    return depressions

def main():
    import pyproj
    import psycopg2
    terrain_path = 'MMR_Terrain_UTM43N.tif'
    
    print("Extracting bounds from DEM...")
    with rasterio.open(terrain_path) as src:
        bounds = src.bounds
    
    # Convert UTM to LatLon
    transformer = pyproj.Transformer.from_crs("epsg:32643", "epsg:4326", always_xy=True)
    lon_min, lat_min = transformer.transform(bounds.left, bounds.bottom)
    lon_max, lat_max = transformer.transform(bounds.right, bounds.top)
    
    print("Connecting to local PostgreSQL database to fetch existing Maharashtra road network...")
    conn = psycopg2.connect("dbname=routing user=postgres password=postgres host=localhost port=5432")
    
    query = f"""
        SELECT gid as osmid, geom as geometry 
        FROM vector.road_maharashtra 
        WHERE geom && ST_MakeEnvelope({lon_min}, {lat_min}, {lon_max}, {lat_max}, 4326)
    """
    edges = gpd.read_postgis(query, conn, geom_col='geometry')
    conn.close()
    
    print(f"Fetched {len(edges)} road segments from local database.")
    
    if len(edges) == 0:
        print("No roads found. Please ensure the routing_backup.backup is fully restored.")
        return
        
    # Reproject to UTM 43N to match the DEM
    edges = edges.to_crs(epsg=32643)
    
    water_logging_points = []
    
    print("Analyzing road elevation profiles...")
    with rasterio.open(terrain_path) as src:
        # We will iterate through each road segment
        for idx, row in edges.iterrows():
            geom = row.geometry
            if not isinstance(geom, LineString):
                continue
                
            # Densify the line into points every 15 meters
            pts = densify_geometry(geom, step=15)
            
            # Extract coordinates for sampling
            coords = [(p.x, p.y) for p in pts]
            
            # Sample elevations
            elevations = [val[0] for val in src.sample(coords)]
            
            # Find depressions (sinks) in the profile
            # Using a threshold of 0.2 meters (20 cm) drop to consider it a significant sink
            deps = find_depressions(pts, elevations, depth_threshold=0.2)
            
            for p, z, depth in deps:
                water_logging_points.append({
                    'geometry': p,
                    'elevation': float(z),
                    'depth': float(depth),
                    'osmid': idx[0] if isinstance(idx, tuple) else idx, # osmid is usually the first part of multi-index
                    'name': row.get('name', 'Unknown')
                })

    print(f"Found {len(water_logging_points)} potential water logging points.")
    
    if len(water_logging_points) > 0:
        # Create a GeoDataFrame
        gdf_points = gpd.GeoDataFrame(water_logging_points, geometry='geometry', crs="EPSG:32643")
        
        # Reproject back to WGS84 for GeoJSON/Visualization
        gdf_points = gdf_points.to_crs(epsg=4326)
        
        # Save to GeoJSON and CSV
        out_geojson = 'water_logging_points.geojson'
        out_csv = 'water_logging_points.csv'
        
        # Some names might be lists if multiple segments merged, convert to string
        gdf_points['name'] = gdf_points['name'].astype(str)
        
        gdf_points.to_file(out_geojson, driver="GeoJSON")
        
        # For CSV, add Lat/Lon columns
        gdf_points['latitude'] = gdf_points.geometry.y
        gdf_points['longitude'] = gdf_points.geometry.x
        gdf_points.drop(columns=['geometry']).to_csv(out_csv, index=False)
        
        print(f"Results saved to {out_geojson} and {out_csv}")
    else:
        print("No water logging points found matching the criteria.")

if __name__ == "__main__":
    main()
