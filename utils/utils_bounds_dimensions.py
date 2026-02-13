import geopandas as gpd
import pyproj
from shapely.geometry import box

from utils.utils_log import logger


def calculate_bounds_dimensions(north, south, west, east, epsg_code):
    """
    Calculate the width and height of a bounding box in meters.

    :param north: Northern latitude
    :param south: Southern latitude
    :param west: Western longitude
    :param east: Eastern longitude
    :param epsg_code: EPSG code for the coordinate system (e.g., 32633 for UTM Zone 33N)

    :return: Tuple of (width_m, height_m) in meters
    """
    # Primary method: GeoDataFrame with box geometry
    clip_box = box(west, south, east, north)
    # EPSG:4326 = WGS84 is the standard geographic coordinate system for latitude/longitude
    clip_box_gdf = gpd.GeoDataFrame([{"geometry": clip_box}], crs="EPSG:4326")
    clip_box_projected = clip_box_gdf.to_crs(f"EPSG:{epsg_code}")

    minx, miny, maxx, maxy = clip_box_projected.total_bounds
    width_m = maxx - minx
    height_m = maxy - miny

    # Internal verification using pyproj
    target_crs = f"EPSG:{epsg_code}"
    # transform from one CRS to another: "Convert FROM WGS84 TO UTM."
    transformer = pyproj.Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)

    # Project all four corners
    sw_x, sw_y = transformer.transform(west, south)
    se_x, se_y = transformer.transform(east, south)
    nw_x, nw_y = transformer.transform(west, north)
    ne_x, ne_y = transformer.transform(east, north)

    # Calculate extent from corners
    pyproj_minx = min(sw_x, se_x, nw_x, ne_x)
    pyproj_maxx = max(sw_x, se_x, nw_x, ne_x)
    pyproj_miny = min(sw_y, se_y, nw_y, ne_y)
    pyproj_maxy = max(sw_y, se_y, nw_y, ne_y)

    pyproj_width_m = pyproj_maxx - pyproj_minx
    pyproj_height_m = pyproj_maxy - pyproj_miny

    # Check for discrepancies (tolerance: 1 meter)
    width_diff = abs(width_m - pyproj_width_m)
    height_diff = abs(height_m - pyproj_height_m)

    if width_diff > 1e-3 or height_diff > 1e-3:
        logger.error(
            f"Bounds calculation discrepancy detected! "
            f"GDF: ({width_m:.1f}m x {height_m:.1f}m), "
            f"PyProj: ({pyproj_width_m:.1f}m x {pyproj_height_m:.1f}m), "
            f"Diff: ({width_diff:.1f}m x {height_diff:.1f}m)"
        )

    print(
        f"Bounds dimensions (from input N,S,W,E):     {width_m:,.1f}m x {height_m:,.1f}m (EPSG:{epsg_code}) (diff with pyproj: {1000*width_diff:.3f}mm, {1000*height_diff:.3f}mm)"
    )

    return width_m, height_m
