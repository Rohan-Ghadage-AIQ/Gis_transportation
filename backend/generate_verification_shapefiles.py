"""
Geocoding Accuracy Verification - Shapefile Exporter
=====================================================
Geocodes addresses via BOTH Ola Maps AND Google Maps / Nominatim,
exports the results as two ESRI Shapefiles, and prints a
distance-difference summary.

Usage:
    python generate_verification_shapefiles.py
    python generate_verification_shapefiles.py -i my_addresses.csv
    python generate_verification_shapefiles.py -n 10             (first 10 only)

Load both shapefiles in QGIS to visually compare:
    shapefiles/ola_maps_geocoded.shp   - Ola Maps results
    shapefiles/reference_geocoded.shp  - Google Maps or Nominatim results
If points overlap -> geocoding is accurate!
"""

# Fix Windows console encoding for special characters
import sys
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import os
import csv
import time
import argparse
import requests
from math import radians, cos, sin, asin, sqrt
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from dotenv import load_dotenv

load_dotenv()

# ─── API Config ──────────────────────────────────────────────────────
OLA_API_KEY = os.getenv("KRUTRIM_API_KEY", "")
OLA_GEOCODE_URL = "https://api.olamaps.io/places/v1/geocode"
OLA_HEADERS = {
    "Origin": "http://localhost:5173",
    "Referer": "http://localhost:5173/"
}

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

RATE_LIMIT_DELAY = 0.35       # seconds between Ola/Google calls
NOMINATIM_DELAY = 1.1         # Nominatim requires ≥1 req/sec
OUTPUT_DIR = Path(__file__).parent / "shapefiles"


# ─── Geocoding Functions ─────────────────────────────────────────────

def geocode_ola(address: str) -> dict:
    """Geocode a single address via Ola Maps API."""
    try:
        resp = requests.get(
            OLA_GEOCODE_URL,
            params={"address": address, "language": "en", "api_key": OLA_API_KEY},
            headers=OLA_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("geocodingResults", [])
            if results:
                loc = results[0].get("geometry", {}).get("location", {})
                lat, lng = loc.get("lat"), loc.get("lng")
                if lat is not None and lng is not None:
                    return {"lat": float(lat), "lng": float(lng), "status": "OK"}
        return {"lat": None, "lng": None, "status": f"HTTP_{resp.status_code}"}
    except Exception as e:
        return {"lat": None, "lng": None, "status": f"ERROR: {e}"}


def geocode_google(address: str) -> dict:
    """Geocode a single address via Google Maps Geocoding API."""
    try:
        resp = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"address": address, "key": GOOGLE_API_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return {"lat": loc["lat"], "lng": loc["lng"], "status": "OK"}
            return {"lat": None, "lng": None, "status": data.get("status", "NO_RESULTS")}
        return {"lat": None, "lng": None, "status": f"HTTP_{resp.status_code}"}
    except Exception as e:
        return {"lat": None, "lng": None, "status": f"ERROR: {e}"}


def geocode_nominatim(address: str) -> dict:
    """Geocode a single address via Nominatim (OpenStreetMap) — free, no key needed."""
    try:
        search_query = f"{address}, India"
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": search_query,
                "format": "json",
                "limit": 1,
                "countrycodes": "in",
            },
            headers={"User-Agent": "GIS-Transportation-Verification/1.0"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                return {
                    "lat": float(data[0]["lat"]),
                    "lng": float(data[0]["lon"]),
                    "status": "OK",
                }
            return {"lat": None, "lng": None, "status": "NO_RESULTS"}
        return {"lat": None, "lng": None, "status": f"HTTP_{resp.status_code}"}
    except Exception as e:
        return {"lat": None, "lng": None, "status": f"ERROR: {e}"}


def geocode_reference(address: str, use_google: bool) -> dict:
    """
    Geocode with the reference source.
    Tries Google first (if enabled & key present), falls back to Nominatim.
    """
    if use_google and GOOGLE_API_KEY:
        result = geocode_google(address)
        if result["lat"] is not None:
            result["source"] = "Google"
            return result
    # Fallback to Nominatim
    result = geocode_nominatim(address)
    result["source"] = "Nominatim"
    return result


# ─── Distance Calculation ────────────────────────────────────────────

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Haversine distance in metres between two lat/lon points."""
    R = 6_371_000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


# ─── Shapefile Writer ────────────────────────────────────────────────

def create_shapefile(records: list[dict], filepath: Path, source_label: str):
    """
    Write a list of records to an ESRI Shapefile.
    Each record must have: id, address, lat, lng
    """
    rows = []
    for r in records:
        if r["lat"] is not None and r["lng"] is not None:
            rows.append({
                "id": r["id"],
                "address": r["address"][:254],  # shapefile field limit
                "latitude": r["lat"],
                "longitude": r["lng"],
                "source": source_label,
                "geometry": Point(r["lng"], r["lat"]),  # lon, lat order for shapefile
            })

    if not rows:
        print(f"  ⚠  No valid coordinates for {source_label} — shapefile not created.")
        return 0

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    filepath.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(filepath), driver="ESRI Shapefile", encoding="utf-8")
    print(f"  ✅ Wrote {len(rows)} features → {filepath}")
    return len(rows)


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Geocode addresses via Ola Maps + reference source and export shapefiles"
    )
    parser.add_argument(
        "-i", "--input",
        default="geocode_verification.csv",
        help="Input CSV with 'address' column (default: geocode_verification.csv)",
    )
    parser.add_argument(
        "-n", "--limit",
        type=int, default=0,
        help="Process only the first N rows (0 = all)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Output directory for shapefiles (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-google",
        action="store_true",
        help="Skip Google Maps API entirely, use Nominatim (OSM) only as reference",
    )
    args = parser.parse_args()

    # ── Validate API keys ──
    if not OLA_API_KEY:
        print("❌ KRUTRIM_API_KEY not found in .env — cannot geocode via Ola Maps.")
        sys.exit(1)

    # Determine reference source
    use_google = False
    if not args.no_google and GOOGLE_API_KEY:
        # Quick test to see if Google Geocoding API is actually enabled
        test = geocode_google("Mumbai, India")
        if test["lat"] is not None:
            use_google = True
            print("✅ Google Maps Geocoding API is active — using as reference source.")
        else:
            print(f"⚠️  Google Maps API returned '{test['status']}' — falling back to Nominatim (OSM).")
    else:
        print("ℹ️  Using Nominatim (OpenStreetMap) as reference geocoding source.")

    ref_label = "Google Maps" if use_google else "Nominatim (OSM)"

    # ── Read input CSV ──
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        sys.exit(1)

    print(f"\n📂 Reading: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.limit > 0:
        rows = rows[: args.limit]

    total = len(rows)
    print(f"🔢 Total addresses to process: {total}\n")

    # ── Geocode each address with both sources ──
    ola_records = []
    ref_records = []
    comparisons = []

    header = f"{'#':<4} {'Ola Status':<14} {'Ref Status':<14} {'Dist(m)':<10} Address"
    print(header)
    print("─" * max(len(header), 80))

    for i, row in enumerate(rows, 1):
        address = row.get("address", "").strip()
        row_id = row.get("id", str(i))

        if not address:
            print(f"{i:<4} {'SKIP':<14} {'SKIP':<14} {'--':<10} (empty)")
            continue

        # ── Use existing ola_lat/ola_lng if available, otherwise call API ──
        existing_ola_lat = row.get("ola_lat")
        existing_ola_lng = row.get("ola_lng")
        if existing_ola_lat and existing_ola_lng:
            try:
                ola = {"lat": float(existing_ola_lat), "lng": float(existing_ola_lng), "status": "CACHED"}
            except ValueError:
                ola = geocode_ola(address)
                time.sleep(RATE_LIMIT_DELAY)
        else:
            ola = geocode_ola(address)
            time.sleep(RATE_LIMIT_DELAY)

        # ── Call reference source ──
        ref = geocode_reference(address, use_google)
        delay = RATE_LIMIT_DELAY if use_google else NOMINATIM_DELAY
        time.sleep(delay)

        ola_records.append({"id": row_id, "address": address, **ola})
        ref_records.append({"id": row_id, "address": address, **ref})

        # ── Distance comparison ──
        dist_str = "--"
        if ola["lat"] and ref["lat"]:
            dist = haversine_m(ola["lat"], ola["lng"], ref["lat"], ref["lng"])
            dist_str = f"{dist:.1f}"
            comparisons.append({"id": row_id, "address": address, "distance_m": dist})

        addr_short = address[:50] + "..." if len(address) > 50 else address
        print(f"{i:<4} {ola['status']:<14} {ref['status']:<14} {dist_str:<10} {addr_short}")

    # ── Export Shapefiles ──
    out_dir = Path(args.output_dir)
    print(f"\n📁 Writing shapefiles to: {out_dir}")

    ola_count = create_shapefile(ola_records, out_dir / "ola_maps_geocoded.shp", "Ola Maps")
    ref_count = create_shapefile(ref_records, out_dir / "reference_geocoded.shp", ref_label)

    # ── Summary ──
    print("\n" + "═" * 65)
    print("  SUMMARY")
    print("═" * 65)
    print(f"  Total addresses:         {total}")
    print(f"  Ola Maps geocoded:       {ola_count}")
    print(f"  {ref_label} geocoded:  {ref_count}")

    if comparisons:
        distances = [c["distance_m"] for c in comparisons]
        avg_dist = sum(distances) / len(distances)
        max_dist = max(distances)
        within_100 = sum(1 for d in distances if d <= 100)
        within_500 = sum(1 for d in distances if d <= 500)

        print(f"\n  📐 Distance Comparison (Ola vs {ref_label}):")
        print(f"     Average offset:      {avg_dist:.1f} m")
        print(f"     Max offset:          {max_dist:.1f} m")
        print(f"     Within 100m:         {within_100}/{len(distances)}")
        print(f"     Within 500m:         {within_500}/{len(distances)}")

        # Flag large offsets
        flagged = [c for c in comparisons if c["distance_m"] > 500]
        if flagged:
            print(f"\n  ⚠️  {len(flagged)} address(es) with >500m offset:")
            for c in flagged:
                addr_short = c["address"][:60] + "..." if len(c["address"]) > 60 else c["address"]
                print(f"     ID {c['id']:>4} | {c['distance_m']:>8.1f}m | {addr_short}")
        else:
            print(f"\n  ✅ All addresses within 500m — looking accurate!")

    print("═" * 65)
    print(f"\n🗺️  Open these in QGIS to visually compare:")
    print(f"    1. {out_dir / 'ola_maps_geocoded.shp'}")
    print(f"    2. {out_dir / 'reference_geocoded.shp'}")
    print(f"    Use different colors for each layer (e.g., red for Ola, blue for {ref_label})")
    print(f"    If points overlap → your geocoding is accurate! ✅\n")

    # ── Also export a comparison CSV for quick reference ──
    if comparisons:
        comp_csv = out_dir / "distance_comparison.csv"
        with open(comp_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "address", "distance_m"])
            writer.writeheader()
            writer.writerows(comparisons)
        print(f"📊 Distance comparison CSV: {comp_csv}\n")


if __name__ == "__main__":
    main()
