def get_utm_epsg_from_bounds_manual(north, south, west, east):
    """
    Determine the appropriate UTM EPSG code from geographic bounds (manual calculation).

    :param north: Northern latitude
    :param south: Southern latitude
    :param west: Western longitude
    :param east: Eastern longitude
    :return: EPSG code as string (e.g., "32630"), zone number, hemisphere
    """
    # Calculate center point
    center_lat = (north + south) / 2
    center_lon = (west + east) / 2

    # Calculate UTM zone (valid for -180 to +180 longitude)
    utm_zone = int((center_lon + 180) / 6) + 1

    # Determine hemisphere (N or S)
    if center_lat >= 0:
        # Northern hemisphere: EPSG:326XX
        epsg_code = 32600 + utm_zone
    else:
        # Southern hemisphere: EPSG:327XX
        epsg_code = 32700 + utm_zone

    hemisphere = "N" if center_lat >= 0 else "S"

    return str(epsg_code), utm_zone, hemisphere


def get_utm_epsg_from_bounds_proj4(north, south, west, east):
    """
    Determine the appropriate UTM EPSG code using pyproj's proj4 string.
    """
    import pyproj

    # Calculate center point
    center_lat = (north + south) / 2
    center_lon = (west + east) / 2

    # Calculate UTM zone
    utm_zone = int((center_lon + 180) / 6) + 1
    hemisphere = "north" if center_lat >= 0 else "south"

    # Use pyproj to create UTM CRS
    utm_crs = pyproj.CRS.from_proj4(
        f"+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84"
    )

    # Get the EPSG code
    epsg_code = utm_crs.to_epsg()

    return str(epsg_code) if epsg_code else None, utm_zone, hemisphere[0].upper()


def get_utm_epsg_from_bounds_aoi(north, south, west, east):
    """
    Determine the appropriate UTM EPSG code using pyproj's area of interest query.
    """
    import pyproj

    utm_crs_list = pyproj.database.query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=pyproj.aoi.AreaOfInterest(
            west_lon_degree=west,
            south_lat_degree=south,
            east_lon_degree=east,
            north_lat_degree=north,
        ),
    )

    if utm_crs_list:
        epsg_code = utm_crs_list[0].code
        # Extract zone and hemisphere from the name
        name = utm_crs_list[0].name  # e.g., "WGS 84 / UTM zone 30N"
        zone_part = name.split("zone ")[1] if "zone " in name else "??"
        zone = int(zone_part[:-1]) if zone_part[:-1].isdigit() else None
        hemisphere = zone_part[-1] if zone_part else "?"
        return str(epsg_code), zone, hemisphere

    return None, None, None


def main():
    """Test and compare different methods of determining UTM EPSG codes."""

    # Test cases: (name, [north, west, east, south])
    test_cases = [
        ("Brittany, France", [48.33708, -4.28381, -4.22570, 48.28765]),
        ("New York, USA", [40.9176, -74.2591, -73.7004, 40.4774]),
        ("Sydney, Australia", [-33.5781, 150.5209, 151.3430, -34.1692]),
        ("Tokyo, Japan", [35.8174, 139.5684, 140.1216, 35.5494]),
        ("Reykjavik, Iceland", [64.2008, -22.0986, -21.7279, 64.0671]),
        ("Cape Town, South Africa", [-33.7252, 18.2763, 18.7041, -34.1524]),
        ("Null Island (edge case)", [1.0, -1.0, 1.0, -1.0]),
    ]

    print("=" * 90)
    print(f"{'Location':<25} {'Manual':<15} {'Proj4':<15} {'AOI':<15} {'Match':<10}")
    print("=" * 90)

    for name, bounds in test_cases:
        north, west, east, south = bounds

        try:
            # Method 1: Manual calculation
            epsg1, zone1, hem1 = get_utm_epsg_from_bounds_manual(
                north, south, west, east
            )
            result1 = f"{zone1}{hem1} ({epsg1})"
        except Exception as e:
            result1 = f"ERROR: {e}"

        try:
            # Method 2: Proj4
            epsg2, zone2, hem2 = get_utm_epsg_from_bounds_proj4(
                north, south, west, east
            )
            result2 = f"{zone2}{hem2} ({epsg2})" if epsg2 else "None"
        except Exception as e:
            result2 = f"ERROR: {e}"

        try:
            # Method 3: Area of Interest
            epsg3, zone3, hem3 = get_utm_epsg_from_bounds_aoi(north, south, west, east)
            result3 = f"{zone3}{hem3} ({epsg3})" if epsg3 else "None"
        except Exception as e:
            result3 = f"ERROR: {e}"

        # Check if all methods agree
        match = "✓" if epsg1 == epsg2 == epsg3 else "✗"

        print(f"{name:<25} {result1:<15} {result2:<15} {result3:<15} {match:<10}")

    print("=" * 90)

    # Detailed example
    print("\nDetailed example for Brittany, France:")
    north, west, east, south = [48.33708, -4.28381, -4.22570, 48.28765]
    epsg, zone, hem = get_utm_epsg_from_bounds_manual(north, south, west, east)
    print(f"  Bounds: N={north}, S={south}, W={west}, E={east}")
    print(f"  Center: ({(north + south) / 2:.5f}, {(west + east) / 2:.5f})")
    print(f"  Result: UTM Zone {zone}{hem} -> EPSG:{epsg}")


if __name__ == "__main__":
    main()
