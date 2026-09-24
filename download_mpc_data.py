import os

# Fix PROJ conflict with existing PostgreSQL/PostGIS installation
if "PROJ_LIB" in os.environ:
    del os.environ["PROJ_LIB"]
if "PROJ_DATA" in os.environ:
    del os.environ["PROJ_DATA"]

import pystac_client
import odc.stac
import rioxarray

print("=====================================================")
print(" Earth Search (AWS) - Sentinel-2 Image Downloader")
print(" (No account or authentication required!)")
print("=====================================================")

# Bounding box for Mumbai
bbox = [72.75, 18.85, 73.05, 19.35]

print("Connecting to Earth Search STAC API (AWS)...")
catalog = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")

print("Searching for cloud-free Sentinel-2 imagery...")
search = catalog.search(
    collections=["sentinel-2-l2a"],
    bbox=bbox,
    datetime="2023-01-01/2023-12-31",
    query={"eo:cloud_cover": {"lt": 5}},
)

items = list(search.items())
if not items:
    print("Error: No cloud-free images found matching the criteria.")
    exit(1)

print(f"Found {len(items)} matching satellite images. Using the clearest one: {items[0].id}")

# Load the data directly into memory using odc-stac
# Sentinel-2 Bands we need:
# green = Green (B03)
# nir = NIR (B08)
# swir16 = SWIR 1 (B11)
print("Downloading Green, NIR, and SWIR bands...")
print("This may take 1-3 minutes depending on your internet connection.")

ds = odc.stac.stac_load(
    [items[0]],
    bands=["green", "nir", "swir16"],
    bbox=bbox,
    resolution=20, # 20m resolution keeps the file size manageable and matches B11's native resolution
    chunks={"x": 2048, "y": 2048}
)

# Select the first (and only) time slice
ds = ds.isel(time=0)

# Convert Dataset to DataArray for TIFF export
da = ds.to_array(dim="band")

output_filename = "mumbai_sentinel2_multispectral.tif"
print(f"Saving to {os.path.abspath(output_filename)}...")

# Export to GeoTIFF
da.rio.to_raster(output_filename)

print("✅ Download complete! The multispectral TIFF file is ready.")
