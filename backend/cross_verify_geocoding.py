"""
Cross-Verify Geocoding: Existing Google lat/lon vs Ola Maps
============================================================
Reads addresses from converted_stations_addresses_new_copy2.csv,
creates TWO shapefiles:
  1. google_points.shp  - from the existing lat,long column (Google Maps data)
  2. ola_points.shp     - geocoded via Ola Maps API (Krutrim)

Load both in QGIS: if points overlap, data is accurate!

Usage:
    python cross_verify_geocoding.py
    python cross_verify_geocoding.py -n 5      (first 5 only)
"""

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
from shapely.geometry import Point
from dotenv import load_dotenv

load_dotenv()

# ─── Config ──────────────────────────────────────────────────────────
OLA_API_KEY = os.getenv("KRUTRIM_API_KEY", "")
OLA_GEOCODE_URL = "https://api.olamaps.io/places/v1/geocode"
OLA_HEADERS = {
    "Origin": "http://localhost:5173",
    "Referer": "http://localhost:5173/"
}
RATE_LIMIT_DELAY = 0.35
OUTPUT_DIR = Path(__file__).parent / "shapefiles"


# ─── Ola Maps Geocoding ──────────────────────────────────────────────
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
            return {"lat": None, "lng": None, "status": "NO_RESULTS"}
        return {"lat": None, "lng": None, "status": f"HTTP_{resp.status_code}"}
    except Exception as e:
        return {"lat": None, "lng": None, "status": f"ERROR"}


# ─── Haversine Distance ──────────────────────────────────────────────
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distance in metres between two lat/lon points."""
    R = 6_371_000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


# ─── Shapefile Writer ────────────────────────────────────────────────
def write_shapefile(records: list[dict], filepath: Path, source_label: str) -> int:
    """Write point features to an ESRI Shapefile (EPSG:4326)."""
    rows = []
    for r in records:
        if r["lat"] is not None and r["lng"] is not None:
            rows.append({
                "id": str(r["id"]),
                "address": str(r["address"])[:254],
                "latitude": round(r["lat"], 8),
                "longitude": round(r["lng"], 8),
                "source": source_label,
                "geometry": Point(r["lng"], r["lat"]),
            })
    if not rows:
        print(f"  [!] No valid points for {source_label} - shapefile not created.")
        return 0

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    filepath.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(filepath), driver="ESRI Shapefile", encoding="utf-8")
    print(f"  [OK] {len(rows)} features -> {filepath}")
    return len(rows)


# ─── Parse the combined "lat,long" column ─────────────────────────────
def parse_latlong(value: str):
    """Parse '19.084140, 72.883972' into (lat, lng) floats."""
    try:
        parts = value.strip().split(",")
        if len(parts) == 2:
            return float(parts[0].strip()), float(parts[1].strip())
    except (ValueError, AttributeError):
        pass
    return None, None


# ─── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Cross-verify: existing Google lat/lon vs Ola Maps geocoding"
    )
    parser.add_argument(
        "-i", "--input",
        default="converted_stations_addresses_new_copy2.csv",
        help="Input CSV (default: converted_stations_addresses_new_copy2.csv)",
    )
    parser.add_argument(
        "-n", "--limit", type=int, default=0,
        help="Process first N rows only (0 = all)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Shapefile output directory (default: {OUTPUT_DIR})",
    )
    args = parser.parse_args()

    if not OLA_API_KEY:
        print("[ERROR] KRUTRIM_API_KEY not in .env - cannot geocode via Ola Maps.")
        sys.exit(1)

    # ── Read CSV ──
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    print(f"Reading: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.limit > 0:
        rows = rows[:args.limit]

    total = len(rows)
    print(f"Addresses to process: {total}\n")

    # ── Process each address ──
    google_records = []
    ola_records = []
    comparisons = []

    print(f"{'#':<4} {'Google Lat':<14} {'Google Lng':<14} {'Ola Lat':<14} {'Ola Lng':<14} {'Dist(m)':<10} Address")
    print("-" * 120)

    for i, row in enumerate(rows, 1):
        row_id = row.get("id", str(i))
        address = row.get("address", "").strip()

        # ── Parse existing Google lat,long ──
        latlong_col = row.get("lat,long", "") or row.get("lat,lon", "") or row.get("latlong", "")
        g_lat, g_lng = parse_latlong(latlong_col)

        if not address:
            print(f"{i:<4} {'SKIP':<14} {'SKIP':<14} {'--':<14} {'--':<14} {'--':<10} (empty)")
            continue

        # ── Geocode via Ola Maps ──
        ola = geocode_ola(address)
        time.sleep(RATE_LIMIT_DELAY)

        google_records.append({"id": row_id, "address": address, "lat": g_lat, "lng": g_lng})
        ola_records.append({"id": row_id, "address": address, "lat": ola["lat"], "lng": ola["lng"]})

        # ── Distance comparison ──
        dist_str = "--"
        if g_lat and g_lng and ola["lat"] and ola["lng"]:
            dist = haversine_m(g_lat, g_lng, ola["lat"], ola["lng"])
            dist_str = f"{dist:.1f}"
            comparisons.append({
                "id": row_id,
                "address": address,
                "google_lat": g_lat, "google_lng": g_lng,
                "ola_lat": ola["lat"], "ola_lng": ola["lng"],
                "distance_m": dist,
            })

        g_lat_s = f"{g_lat:.6f}" if g_lat else "--"
        g_lng_s = f"{g_lng:.6f}" if g_lng else "--"
        o_lat_s = f"{ola['lat']:.6f}" if ola["lat"] else "--"
        o_lng_s = f"{ola['lng']:.6f}" if ola["lng"] else "--"
        addr_short = address[:40] + "..." if len(address) > 40 else address
        print(f"{i:<4} {g_lat_s:<14} {g_lng_s:<14} {o_lat_s:<14} {o_lng_s:<14} {dist_str:<10} {addr_short}")

    # ── Write Shapefiles ──
    out_dir = Path(args.output_dir)
    print(f"\nWriting shapefiles to: {out_dir}")

    g_count = write_shapefile(google_records, out_dir / "google_points.shp", "Google Maps")
    o_count = write_shapefile(ola_records, out_dir / "ola_points.shp", "Ola Maps")

    # ── Summary ──
    print("\n" + "=" * 65)
    print("  CROSS-VERIFICATION SUMMARY")
    print("=" * 65)
    print(f"  Total addresses:          {total}")
    print(f"  Google Maps points:       {g_count}")
    print(f"  Ola Maps points:          {o_count}")

    if comparisons:
        distances = [c["distance_m"] for c in comparisons]
        avg = sum(distances) / len(distances)
        mx = max(distances)
        within_100 = sum(1 for d in distances if d <= 100)
        within_500 = sum(1 for d in distances if d <= 500)

        print(f"\n  Distance (Google vs Ola Maps):")
        print(f"    Average offset:       {avg:.1f} m")
        print(f"    Max offset:           {mx:.1f} m")
        print(f"    Within 100m:          {within_100}/{len(distances)}")
        print(f"    Within 500m:          {within_500}/{len(distances)}")

        flagged = [c for c in comparisons if c["distance_m"] > 500]
        if flagged:
            print(f"\n  [!] {len(flagged)} address(es) with >500m offset:")
            for c in flagged:
                addr_short = c["address"][:55] + "..." if len(c["address"]) > 55 else c["address"]
                print(f"      ID {c['id']:>3} | {c['distance_m']:>8.1f}m | {addr_short}")
        else:
            print(f"\n  [OK] All addresses within 500m - data looks accurate!")

    print("=" * 65)

    # ── Export comparison CSV ──
    if comparisons:
        comp_csv = out_dir / "google_vs_ola_comparison.csv"
        with open(comp_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "address", "google_lat", "google_lng",
                "ola_lat", "ola_lng", "distance_m"
            ])
            writer.writeheader()
            writer.writerows(comparisons)
        print(f"\n  Comparison CSV: {comp_csv}")

    print(f"\n  QGIS Steps:")
    print(f"  1. Open QGIS")
    print(f"  2. Layer > Add Vector Layer > Browse to:")
    print(f"     - {out_dir / 'google_points.shp'}  (set color: BLUE)")
    print(f"     - {out_dir / 'ola_points.shp'}     (set color: RED)")
    print(f"  3. If points overlap = data is accurate!")
    print()


if __name__ == "__main__":
    main()
