import csv
import struct

def parse_wkb_point(wkb_hex):
    """
    Parse WKB (Well-Known Binary) Point geometry to extract longitude and latitude.
    Format: SRID=4326;POINT(lon lat)
    """
    # Remove '0101000020E6100000' prefix (WKB header for SRID 4326 Point)
    # The remaining 16 bytes are: 8 bytes for X (lon), 8 bytes for Y (lat)
    
    # Convert hex string to bytes
    wkb_bytes = bytes.fromhex(wkb_hex)
    
    # Skip first 9 bytes (byte order + type + SRID)
    # Extract longitude (8 bytes, little-endian double)
    lon = struct.unpack('<d', wkb_bytes[9:17])[0]
    # Extract latitude (8 bytes, little-endian double)
    lat = struct.unpack('<d', wkb_bytes[17:25])[0]
    
    return lon, lat

def convert_station_data_to_csv(input_file, output_file):
    """
    Convert station_node_map data to simple CSV format (id, latitude, longitude)
    """
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.writer(outfile)
        
        # Write header
        writer.writerow(['id', 'latitude', 'longitude', 'parcel_weight', 'service_time', 'window_start', 'window_end'])
        
        for row in reader:
            station_id = row['station_id']
            wkb_geom = row['geom']
            parcel_weight = row['parcel_weight']
            service_time = row['service_time']
            window_start = row['window_start']
            window_end = row['window_end']
            
            # Parse WKB geometry to get lon, lat
            lon, lat = parse_wkb_point(wkb_geom)
            
            # Write to output CSV
            writer.writerow([station_id, lat, lon, parcel_weight, service_time, window_start, window_end])
    
    print(f"Converted {input_file} to {output_file}")
    print(f"You can now upload {output_file} to the frontend application")

if __name__ == "__main__":
    # Save your input data to 'station_data_input.csv' first
    convert_station_data_to_csv('station_data_input.csv', 'converted_stations.csv')
