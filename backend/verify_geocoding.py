# Cross-Verification Script for Geocoding via Ola Maps API
# Usage:
#   python verify_geocoding.py input.csv
#   python verify_geocoding.py input.csv -n 5          (first 5 only)
#   python verify_geocoding.py input.csv -o output.csv (custom output)

import os
import sys
import csv
import time
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

# Config
API_KEY = os.getenv("KRUTRIM_API_KEY", "")
OLA_MAPS_URL = "https://api.olamaps.io/places/v1/geocode"
HEADERS = {
    "Origin": "http://localhost:5173",
    "Referer": "http://localhost:5173/"
}
RATE_LIMIT_DELAY = 0.3


def geocode_address(address):
    """Geocode a single address using Ola Maps API."""
    try:
        response = requests.get(
            OLA_MAPS_URL,
            params={"address": address, "language": "en", "api_key": API_KEY},
            headers=HEADERS,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get("geocodingResults", [])
            if results:
                result = results[0]
                geo = result.get("geometry", {}).get("location", {})
                return {
                    "status": "OK",
                    "lat": geo.get("lat"),
                    "lng": geo.get("lng"),
                    "formatted_address": result.get("formatted_address", ""),
                    "confidence": result.get("confidence", "N/A"),
                    "num_results": len(results)
                }
            return {"status": "NO_RESULTS", "lat": None, "lng": None,
                    "formatted_address": "", "confidence": 0, "num_results": 0}
        elif response.status_code == 403:
            return {"status": "AUTH_ERROR_403", "lat": None, "lng": None,
                    "formatted_address": response.text[:100], "confidence": 0, "num_results": 0}
        else:
            return {"status": f"HTTP_{response.status_code}", "lat": None, "lng": None,
                    "formatted_address": response.text[:100], "confidence": 0, "num_results": 0}
    except requests.exceptions.Timeout:
        return {"status": "TIMEOUT", "lat": None, "lng": None,
                "formatted_address": "", "confidence": 0, "num_results": 0}
    except Exception as e:
        return {"status": f"ERROR", "lat": None, "lng": None,
                "formatted_address": str(e)[:80], "confidence": 0, "num_results": 0}


def main():
    parser = argparse.ArgumentParser(description="Cross-verify geocoding via Ola Maps API")
    parser.add_argument("input_csv", help="Path to input CSV with 'address' column")
    parser.add_argument("--output", "-o", default="geocode_verification.csv", help="Output CSV path")
    parser.add_argument("--limit", "-n", type=int, default=0, help="Limit rows (0 = all)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: KRUTRIM_API_KEY not found in .env file.")
        sys.exit(1)

    # Read input CSV
    print(f"Reading: {args.input_csv}")
    rows = []
    with open(args.input_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if args.limit > 0:
        rows = rows[:args.limit]

    total = len(rows)
    print(f"Geocoding {total} addresses via Ola Maps API...\n")
    print(f"{'#':<4} {'Status':<16} {'Lat':<12} {'Lng':<12} Address")
    print("-" * 100)

    results = []
    ok_count = 0
    fail_count = 0

    for i, row in enumerate(rows, 1):
        address = row.get("address", "").strip()
        if not address:
            print(f"{i:<4} {'SKIP':<16} {'--':<12} {'--':<12} (empty)")
            continue

        geo = geocode_address(address)

        if geo["lat"] and geo["lng"]:
            ok_count += 1
            lat_str = f"{geo['lat']:.6f}"
            lng_str = f"{geo['lng']:.6f}"
        else:
            fail_count += 1
            lat_str = "--"
            lng_str = "--"

        addr_short = address[:55] + "..." if len(address) > 55 else address
        print(f"{i:<4} {geo['status']:<16} {lat_str:<12} {lng_str:<12} {addr_short}")

        # Build output row
        result_row = dict(row)
        result_row["ola_lat"] = geo["lat"] or ""
        result_row["ola_lng"] = geo["lng"] or ""
        result_row["ola_status"] = geo["status"]
        result_row["ola_formatted_address"] = geo["formatted_address"]
        result_row["ola_confidence"] = geo["confidence"]
        result_row["ola_num_results"] = geo["num_results"]

        # Distance diff if original lat/lon exists
        orig_lat = row.get("latitude")
        orig_lng = row.get("longitude")
        if orig_lat and orig_lng and geo["lat"] and geo["lng"]:
            try:
                from math import radians, cos, sin, asin, sqrt
                olat, olng = float(orig_lat), float(orig_lng)
                nlat, nlng = float(geo["lat"]), float(geo["lng"])
                R = 6371000
                dlat = radians(nlat - olat)
                dlng = radians(nlng - olng)
                a = sin(dlat / 2) ** 2 + cos(radians(olat)) * cos(radians(nlat)) * sin(dlng / 2) ** 2
                dist_m = 2 * R * asin(sqrt(a))
                result_row["distance_diff_m"] = round(dist_m, 1)
            except Exception:
                result_row["distance_diff_m"] = ""
        else:
            result_row["distance_diff_m"] = ""

        results.append(result_row)
        time.sleep(RATE_LIMIT_DELAY)

    # Write output
    if results:
        fieldnames = list(results[0].keys())
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    print("\n" + "=" * 60)
    print(f"Geocoded OK: {ok_count}/{total}")
    print(f"Failed:      {fail_count}/{total}")
    print(f"Output:      {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
