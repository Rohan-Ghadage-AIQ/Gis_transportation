"""
Reverse Geocoding Utility: Convert coordinates to addresses

This script takes a CSV with lat/lon coordinates and converts them to addresses
using Nominatim (OpenStreetMap) reverse geocoding API.

Usage:
    python reverse_geocode_csv.py input.csv output.csv
"""

import pandas as pd
import requests
import time
import sys
from typing import Optional, Dict

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Reverse geocode coordinates to address using Nominatim
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        Address string or None if failed
    """
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "addressdetails": 1
            },
            headers={
                "User-Agent": "VehicleRoutingSystem/1.0"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract address components
            address_parts = data.get("address", {})
            
            # Build a clean address string
            components = []
            
            # Road/street
            if "road" in address_parts:
                components.append(address_parts["road"])
            
            # Suburb/locality
            if "suburb" in address_parts:
                components.append(address_parts["suburb"])
            elif "neighbourhood" in address_parts:
                components.append(address_parts["neighbourhood"])
            
            # City
            if "city" in address_parts:
                components.append(address_parts["city"])
            elif "town" in address_parts:
                components.append(address_parts["town"])
            elif "village" in address_parts:
                components.append(address_parts["village"])
            
            # State
            if "state" in address_parts:
                components.append(address_parts["state"])
            
            # Postcode
            if "postcode" in address_parts:
                components.append(address_parts["postcode"])
            
            # Join components
            if components:
                return ", ".join(components)
            else:
                # Fallback to display_name
                return data.get("display_name", None)
        
        return None
        
    except Exception as e:
        print(f"Error reverse geocoding ({lat}, {lon}): {e}")
        return None


def convert_csv(input_file: str, output_file: str):
    """
    Convert coordinate-based CSV to address-based CSV
    
    Args:
        input_file: Path to input CSV with lat/lon
        output_file: Path to output CSV with addresses
    """
    print(f"Reading {input_file}...")
    df = pd.read_csv(input_file)
    
    # Validate columns
    if 'latitude' not in df.columns or 'longitude' not in df.columns:
        print("Error: CSV must have 'latitude' and 'longitude' columns")
        return
    
    print(f"Found {len(df)} locations to reverse geocode")
    print("\nStarting reverse geocoding (1 request per second)...")
    print("=" * 60)
    
    addresses = []
    
    for i, row in df.iterrows():
        lat = row['latitude']
        lon = row['longitude']
        
        print(f"\n[{i+1}/{len(df)}] Reverse geocoding ({lat:.6f}, {lon:.6f})...")
        
        address = reverse_geocode(lat, lon)
        
        if address:
            print(f"✓ {address[:80]}...")
            addresses.append(address)
        else:
            print(f"✗ Failed - using coordinates as fallback")
            addresses.append(f"{lat}, {lon}")
        
        # Rate limit: 1 request per second for Nominatim
        if i < len(df) - 1:  # Don't sleep after last request
            time.sleep(1)
    
    print("\n" + "=" * 60)
    print(f"✓ Completed reverse geocoding!")
    
    # Add address column
    df['address'] = addresses
    
    # Reorder columns: id, address, then other columns
    cols = ['id', 'address']
    other_cols = [col for col in df.columns if col not in ['id', 'address', 'latitude', 'longitude']]
    cols.extend(other_cols)
    
    df_output = df[cols]
    
    # Save to output file
    df_output.to_csv(output_file, index=False)
    print(f"\n✓ Saved address-based CSV to: {output_file}")
    print(f"  Total records: {len(df_output)}")
    print(f"  Columns: {', '.join(df_output.columns.tolist())}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python reverse_geocode_csv.py input.csv output.csv")
        print("\nExample:")
        print("  python reverse_geocode_csv.py converted_stations.csv sample_data_address_real.csv")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    convert_csv(input_file, output_file)
