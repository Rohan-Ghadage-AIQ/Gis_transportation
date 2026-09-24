import ee
import geemap
import os

print("=====================================================")
print(" GEE - Monsoon Sentinel-2 Cloud-Masked Downloader")
print("=====================================================")

try:
    # Try to initialize with existing credentials
    ee.Initialize()
except Exception as e:
    print("Authentication required. Please log into Google Earth Engine in your browser.")
    ee.Authenticate()
    ee.Initialize()

# Bounding box for Mumbai
mumbai_bbox = ee.Geometry.Rectangle([72.75, 18.85, 73.05, 19.35])

def mask_s2_clouds(image):
    """
    Masks clouds and cloud shadows in Sentinel-2 using the SCL band.
    """
    scl = image.select('SCL')
    # SCL Classes:
    # 3 = Cloud shadows
    # 8 = Cloud medium probability
    # 9 = Cloud high probability
    # 10 = Thin cirrus
    mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
    
    # Return the masked image (we keep the original 10000x scaling for consistency)
    return image.updateMask(mask)

print("\nFetching Sentinel-2 images from July to September 2023 (Monsoon Season)...")
# Filter the collection for Mumbai during the monsoon
collection = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
              .filterBounds(mumbai_bbox)
              .filterDate('2023-07-01', '2023-09-30')
              .map(mask_s2_clouds))

print("Stitching clear pixels into a massive Monsoon Composite (this removes the clouds)...")
# The median() function takes the median value of all unmasked pixels over the 3 months.
# This creates a perfect, cloud-free composite of the ground during the wettest season!
composite = collection.median().clip(mumbai_bbox)

# Select Green, NIR, and SWIR bands
selected_image = composite.select(['B3', 'B8', 'B11'])

output_filename = "mumbai_monsoon_multispectral.tif"
print(f"\nDownloading the cloud-masked composite to {os.path.abspath(output_filename)}...")
print("Please wait, GEE is computing the composite in the cloud...")

geemap.ee_export_image(
    selected_image,
    filename=output_filename,
    scale=20, # 20m resolution 
    region=mumbai_bbox,
    file_per_band=False
)

print("\n✅ Download complete! You now have the monsoon TIFF file.")
