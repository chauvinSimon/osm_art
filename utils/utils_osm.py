import random
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmium as osm
import pandas as pd
import shapely.wkb as wkblib
import svgwrite
from shapely import unary_union
from shapely.affinity import affine_transform
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from utils.utils_bounds_dimensions import calculate_bounds_dimensions
from utils.utils_log import logger
from utils.utils_utm import get_utm_epsg_from_bounds_proj4


class OSMToSVGConverter:
    def __init__(
        self,
        osm_path: Path,
        svg_out_path: Path,
        osm_config,
        target_width_cm=None,
        target_height_cm=None,
        margin_mm=1,
        fill_paths=False,
        nswe_bounds=None,
    ):
        if nswe_bounds is None:
            epsg_code = "32630"  # for Brest: UTM 30N (EPSG:32630)
            logger.warning(f"No nswe_bounds specified, using {epsg_code}")
        else:
            epsg_code, zone, hem = get_utm_epsg_from_bounds_proj4(*nswe_bounds)
            logger.info(
                f"Derived zone: {zone}{hem} ({epsg_code}) for NSWE={nswe_bounds}"
            )
        logger.info(f"Using {epsg_code = }")

        self.osm_path = osm_path
        self.svg_path = svg_out_path
        self.nswe_bounds = nswe_bounds

        # Validate that exactly one dimension is set
        if target_width_cm is not None and target_height_cm is not None:
            raise ValueError(
                "Cannot specify both target_width_cm and target_height_cm. Please set only one."
            )
        if target_width_cm is None and target_height_cm is None:
            raise ValueError("Must specify either target_width_cm or target_height_cm.")

        self.fill_paths = fill_paths
        self.target_width_cm = target_width_cm
        self.target_height_cm = target_height_cm
        self.margin_mm = margin_mm
        self.epsg_code = epsg_code
        self.wkbfab = osm.geom.WKBFactory()

        self.external_rect_colour = osm_config["external_rect_colour"]
        self.background_colour = osm_config["background_colour"]
        self.layer_config = osm_config["layer_config"]

        self.bypass_river_fill = osm_config["bypass_river_fill"]
        random.seed(osm_config["random_seed"])

        self.buffer_cap_style = osm_config["buffer"]["cap_style"]
        self.buffer_join_style = osm_config["buffer"]["join_style"]

        # Road type classifications
        self.road_types = osm_config["road_types"]

    def extract_bounds_from_osm(self):
        """Extract bounds directly from OSM file header if available."""
        try:
            with open(self.osm_path, "r") as f:
                for line in f:
                    if "<bounds" in line:
                        import xml.etree.ElementTree as ET

                        bounds_elem = ET.fromstring(line.strip())
                        return (
                            float(bounds_elem.get("maxlat")),
                            float(bounds_elem.get("minlat")),
                            float(bounds_elem.get("minlon")),
                            float(bounds_elem.get("maxlon")),
                        )
                    elif "<osm" in line:
                        break
        except Exception as e:
            logger.warning(f"Could not extract bounds from OSM: {e}")
        return None

    class OSMHandler(osm.SimpleHandler):
        def __init__(self, parent):
            super().__init__()
            self.parent = parent
            self.features = {
                "buildings": [],
                "roads": [],
                "coastlines": [],
                "rivers": [],
                "named_nodes": [],
                "named_ways": [],
                "water_bodies": [],
                "beaches": [],
                "fields": [],
            }
            # collect all names with tags
            self.all_names = []

        def process_tags(self, tags, geom=None):
            """Store name with tags and optional geometry."""
            if "name" in tags:
                entry = {"name": tags["name"], "tags": dict(tags)}
                self.all_names.append(entry)
                if geom is not None:
                    # store geometry along with tags
                    if geom.geom_type == "Point":
                        self.features["named_nodes"].append(
                            {"geometry": geom, "tags": dict(tags)}
                        )
                    else:
                        self.features["named_ways"].append(
                            {"geometry": geom, "tags": dict(tags)}
                        )

        @staticmethod
        def is_water_body(tags):
            """Check if tags indicate a water body."""
            # Standard water tags
            if tags.get("natural") == "water":
                return True
            # Explicit water types
            if tags.get("water") in ["lake", "pond", "reservoir", "basin", "lagoon"]:
                return True
            # Leisure water features
            if tags.get("leisure") in ["swimming_pool", "swimming_area"]:
                return True
            return False

        def way(self, w):
            if not w.nodes:
                return
            try:
                wkb = self.parent.wkbfab.create_linestring(w)
                geom = wkblib.loads(wkb, hex=True)
                tags = dict(w.tags)

                # classify into existing layers
                if "building" in tags:
                    self.features["buildings"].append({"geometry": geom, "tags": tags})
                elif "highway" in tags:
                    self.features["roads"].append({"geometry": geom, "tags": tags})
                elif tags.get("natural") == "coastline":
                    self.features["coastlines"].append({"geometry": geom, "tags": tags})
                elif tags.get("waterway") in ["river", "stream", "ditch", "canal"]:
                    self.features["rivers"].append({"geometry": geom, "tags": tags})
                elif self.is_water_body(tags):
                    self.features["water_bodies"].append(
                        {"geometry": geom, "tags": tags}
                    )
                elif tags.get("natural") == "beach":
                    self.features["beaches"].append({"geometry": geom, "tags": tags})
                elif tags.get("natural") == "sand":
                    self.features["beaches"].append({"geometry": geom, "tags": tags})
                elif (
                    tags.get("natural") in ["scrub", "grassland", "wood", "tree_row"]
                    or tags.get("landuse")
                    in ["grass", "meadow", "farmland", "farmyard"]
                    or tags.get("leisure") in ["park"]
                ):
                    self.features["fields"].append({"geometry": geom, "tags": tags})
                elif tags.get("man_made") in ["pier"]:
                    tags["highway"] = "pier"
                    self.features["roads"].append({"geometry": geom, "tags": tags})
                # else:
                #     print(tags)

                # collect name
                self.process_tags(tags, geom)

            except Exception as e:
                logger.warning(f"Error parsing way {w.id}: {e}")

        def node(self, n):
            if "name" in n.tags and n.location.valid():
                from shapely.geometry import Point

                geom = Point(n.location.lon, n.location.lat)
                self.process_tags(n.tags, geom)

        def area(self, a):
            """Process areas (closed ways and multipolygon relations)."""
            # this was necessary to find some lakes!
            try:
                tags = dict(a.tags)

                # Build the area geometry
                wkb = self.parent.wkbfab.create_multipolygon(a)
                geom = wkblib.loads(wkb, hex=True)

                # Classify the area
                if self.is_water_body(tags):
                    self.features["water_bodies"].append(
                        {"geometry": geom, "tags": tags}
                    )
                    logger.info(f"Found water body area: {tags.get('name', 'unnamed')}")
                elif tags.get("natural") == "beach":
                    self.features["beaches"].append({"geometry": geom, "tags": tags})
                elif tags.get("natural") == "sand":
                    self.features["beaches"].append({"geometry": geom, "tags": tags})
                elif "building" in tags:
                    self.features["buildings"].append({"geometry": geom, "tags": tags})
                elif (
                    tags.get("natural") in ["scrub", "grassland", "wood", "tree_row"]
                    or tags.get("landuse")
                    in ["grass", "meadow", "farmland", "farmyard", "forest"]
                    or tags.get("leisure") in ["park"]
                ):
                    self.features["fields"].append({"geometry": geom, "tags": tags})

                # Collect name
                self.process_tags(tags, geom)

            except Exception as e:
                logger.warning(f"Error parsing area {a.id}: {e}")

    def parse_osm_data(self):
        """Parse OSM data and return GeoDataFrames."""
        handler = self.OSMHandler(self)
        handler.apply_file(str(self.osm_path), locations=True)

        # Convert to GeoDataFrames
        gdfs = {}
        for name, features in handler.features.items():
            if features:
                # Tell GeoPandas "These coordinates are in WGS84 lat/lon format." -> EPSG:4326
                gdfs[name] = gpd.GeoDataFrame(features, crs="EPSG:4326")
            else:
                gdfs[name] = gpd.GeoDataFrame(
                    columns=["geometry", "tags"], crs="EPSG:4326"
                )
                logger.info(f"No {name} found in OSM data")

        logger.info(f"Using provided bounds for clipping: {self.nswe_bounds}")
        north, south, west, east = self.nswe_bounds
        calculate_bounds_dimensions(north, south, west, east, epsg_code=self.epsg_code)

        clip_box = box(west, south, east, north)
        gdfs = {
            name: self.clean_gdf(
                gdf,
                clip_box,
                # Rivers require special handling. Otherwise, strange shape resulting from re-organisation of vertices.
                convert_to_boundaries=(name in ["water_bodies"]),
            )
            for name, gdf in gdfs.items()
        }

        # # Clip layers that need it (like roads, buildings, rivers)
        # clip_layers = ['buildings', 'roads', 'coastlines', 'rivers']
        # for layer in clip_layers:
        #     gdfs[layer] = self.clean_gdf(gdfs[layer], clip_box)
        #
        # # Do NOT clip named nodes/ways aggressively
        # # Optional: filter named ways to within bounds for performance
        # if not gdfs['named_ways'].empty:
        #     gdfs['named_ways'] = gdfs['named_ways'][gdfs['named_ways'].intersects(clip_box)]
        #     gdfs['named_ways'] = gdfs['named_ways'].explode(index_parts=False).reset_index(drop=True)

        return gdfs

    @staticmethod
    def clean_gdf(gdf, clip_box, convert_to_boundaries=False):
        """Clip to bounding box and explode multi-geometries."""
        if gdf.empty:
            return gdf

        gdf = gdf[gdf.intersects(clip_box)].copy()
        if gdf.empty:
            return gdf

        if convert_to_boundaries:
            # I found this fix for problematic geometry
            gdf["geometry"] = gdf["geometry"].apply(lambda g: g.buffer(0))

        gdf["geometry"] = gdf["geometry"].apply(lambda g: g.intersection(clip_box))
        # Filter out empty geometries
        gdf = gdf[~gdf["geometry"].is_empty]
        gdf = gdf.explode(index_parts=False).reset_index(drop=True)
        return gdf

    def project_and_transform_geometries(self, gdfs):
        """Project to metric CRS and transform for SVG."""
        # Project all layers to metric CRS
        projected_gdfs = {}
        for name, gdf in gdfs.items():
            if not gdf.empty:
                projected_gdfs[name] = gdf.to_crs(f"EPSG:{self.epsg_code}")
            else:
                projected_gdfs[name] = gdf

        # Compute global bounds from all non-empty layers
        non_empty_gdfs = [gdf for gdf in projected_gdfs.values() if not gdf.empty]
        if not non_empty_gdfs:
            raise ValueError("No valid geometries found after projection")

        all_geoms = gpd.GeoDataFrame(pd.concat(non_empty_gdfs, ignore_index=True))
        minx, miny, maxx, maxy = (
            all_geoms.total_bounds
        )  # e.g. [404769.3328384713, 5348998.1642350415, 409166.2887520391, 5354560.829344296]

        # Calculate scale factor based on which dimension is specified
        width_m = maxx - minx
        height_m = maxy - miny
        print(
            f"Bounds dimensions (from all proj elements): {width_m:,.1f}m x {height_m:,.1f}m"
        )

        if self.target_width_cm is not None:
            # Scale based on width (original behavior)
            scale_factor = (self.target_width_cm * 10 - 2 * self.margin_mm) / width_m
            height_scaled = height_m * scale_factor
            width_scaled = self.target_width_cm * 10
        else:
            # Scale based on height (new behavior)
            scale_factor = (self.target_height_cm * 10 - 2 * self.margin_mm) / height_m
            width_scaled = width_m * scale_factor
            height_scaled = self.target_height_cm * 10

        # Transform all layers using single affine transform
        transformed_gdfs = {}
        for name, gdf in projected_gdfs.items():
            transformed_gdfs[name] = self.transform_gdf(
                gdf, minx, miny, scale_factor, width_scaled, height_scaled
            )

        svg_w = width_scaled + 2 * self.margin_mm
        svg_h = height_scaled + 2 * self.margin_mm

        svg_dimensions = (svg_w, svg_h)

        # Calculate scale information
        logger.info(f"Original dimensions: {width_m:,.0f}m x {height_m:,.0f}m")
        logger.info(f"Scaled dimensions: {svg_w:.0f}mm x {svg_h:.0f}mm")
        for ref_dim in [100, 200, 150, 300]:
            logger.info(
                f"Corresponding to {ref_dim:.0f}mm x {ref_dim * svg_h / svg_w:.0f}mm"
            )
        for ref_dim in [100, 200, 150, 300]:
            logger.info(
                f"Corresponding to {ref_dim * svg_w / svg_h:.0f}mm x {ref_dim:.0f}mm"
            )

        # todo: Use width_scaled instead of svg_w for scale calculation. Same if margin == 0
        w_cm_map = svg_w / 10
        w_cm_reality = width_m * 100
        scale_ratio = int(w_cm_reality / w_cm_map)

        one_km_in_reality_in_cm = 100_000 * w_cm_map / w_cm_reality
        logger.info(f"Scale factor: 1:{scale_ratio}")
        logger.info(f"Scale: 1cm on map = {scale_ratio / 100:.1f}m in reality")
        logger.info(f"Scale: 1km in reality = {one_km_in_reality_in_cm:.3f}cm on map")

        # Store scale information for later use
        self.scale_info = {
            "scale_ratio": scale_ratio,
            "meters_per_cm": scale_ratio / 100,
            "one_km_in_reality_in_cm": one_km_in_reality_in_cm,
        }

        return transformed_gdfs, svg_dimensions

    def transform_gdf(self, gdf, minx, miny, scale_factor, width_scaled, height_scaled):
        """
        Transform geometries using single affine transform:
        translate, scale, invert Y, and add margin.
        """
        if gdf.empty:
            return gdf

        gdf = gdf.copy()

        # Affine transform parameters [a, b, d, e, xoff, yoff]
        a = scale_factor  # X scale
        b = 0  # XY shear
        d = 0  # YX shear
        e = -scale_factor  # Y scale (invert)
        xoff = self.margin_mm - minx * scale_factor
        yoff = height_scaled + self.margin_mm + miny * scale_factor

        gdf["geometry"] = gdf["geometry"].apply(
            lambda g: affine_transform(g, [a, b, d, e, xoff, yoff])
        )

        return gdf

    def classify_roads(self, roads_gdf):
        """Classify roads by type."""
        if roads_gdf.empty:
            return {
                road_type: gpd.GeoDataFrame(
                    columns=["geometry", "tags"], crs=roads_gdf.crs
                )
                for road_type in self.road_types.keys()
            }

        classified = {}
        for road_type, highway_types in self.road_types.items():
            mask = roads_gdf["tags"].apply(lambda x: x.get("highway") in highway_types)
            classified[road_type] = roads_gdf[mask].copy()

        return classified

    def create_svg(self, gdfs, svg_dimensions):
        """Create SVG with all layers."""
        width_mm, height_mm = svg_dimensions

        # Create SVG with proper dimensions
        dwg = svgwrite.Drawing(
            str(self.svg_path),
            size=(f"{width_mm}mm", f"{height_mm}mm"),
            viewBox=f"0 0 {width_mm} {height_mm}",
            profile="tiny",
        )

        # Classify roads
        road_layers = self.classify_roads(gdfs["roads"])

        # Combine all layers for rendering
        all_layers = {
            "coastlines": gdfs["coastlines"],
            "rivers": gdfs["rivers"],
            "water_bodies": gdfs["water_bodies"],
            "beaches": gdfs["beaches"],
            "fields": gdfs["fields"],
            **road_layers,
            "buildings": gdfs["buildings"],
        }

        # Create SVG layers
        for (
            layer_name,
            stroke_color,
            stroke_width,
            fill_color,
            dasharray,
        ) in self.layer_config:
            if layer_name in all_layers and not all_layers[layer_name].empty:
                self.add_layer_to_svg(
                    dwg,
                    layer_name,
                    all_layers[layer_name],
                    stroke_color,
                    stroke_width,
                    fill_color,
                    dasharray,
                )

        # Background rectangle to check scale
        if self.external_rect_colour is not None:
            dwg.add(
                dwg.rect(
                    insert=(0, 0),
                    size=(f"{width_mm}mm", f"{height_mm}mm"),
                    fill="none",
                    stroke=self.external_rect_colour,
                    stroke_width=0.1,
                )
            )

        if self.background_colour is not None:
            bg_rect = dwg.rect(
                insert=(0, 0),
                size=(f"{width_mm}mm", f"{height_mm}mm"),
                fill=self.background_colour,
                stroke="none",
            )
            dwg.elements.insert(0, bg_rect)  # push it to the back

        dwg.save()
        logger.info(f"SVG saved to {self.svg_path}")
        return self.svg_path

    def add_layer_to_svg(
        self, dwg, name, gdf, stroke_color, stroke_width, fill_color, dasharray="none"
    ):
        """Add a layer to the SVG."""
        layer = dwg.add(dwg.g(id=name))

        for geom in gdf.geometry:
            if geom.is_empty:
                continue

            # ---------------------------
            # Special case: Coastlines should be simple lines
            # ---------------------------
            if name == "coastlines":
                if geom.geom_type == "LineString":
                    points = [(x, y) for x, y in geom.coords]
                    layer.add(
                        dwg.polyline(
                            points,
                            stroke=stroke_color,
                            fill="none",
                            stroke_width=stroke_width,
                        )
                    )
                continue  # Skip further processing for coastlines

            # ---------------------------
            # Lines (roads, rivers, etc.)
            # ---------------------------
            if geom.geom_type == "LineString":
                points = [(x, y) for x, y in geom.coords]

                # Buildings as closed LineStrings
                if (
                    name
                    in [
                        "buildings",
                        "water_bodies",
                        "beaches",
                        "fields",
                    ]
                    and len(points) >= 3
                ):
                    if points[0] != points[-1]:
                        points.append(points[0])
                    layer.add(
                        dwg.polygon(
                            points,
                            fill=(
                                random.choice(fill_color).lower()
                                if isinstance(fill_color, list)
                                else fill_color.lower()
                            ),
                            stroke=stroke_color.lower(),
                            stroke_width=stroke_width,
                            # opacity=0.75 if name == "water_bodies" else 1,
                        )
                    )

                else:
                    line_style = {
                        "fill": "none",
                        "stroke": stroke_color,
                        "stroke_width": stroke_width,
                    }
                    if dasharray != "none":
                        line_style["stroke_dasharray"] = dasharray

                    if self.fill_paths and dasharray != "none":
                        # Convert dash pattern string, e.g. "4,1", to list of floats
                        pattern = [float(x) for x in dasharray.split(",")]
                        self._add_dashed_line_as_polygons(
                            layer,
                            dwg,
                            LineString(points),
                            stroke_color,
                            stroke_width,
                            pattern,
                        )

                    elif self.fill_paths:
                        # Special case: RIVERS → draw outline of buffered shape (no fill)
                        if (
                            self.bypass_river_fill
                            and name == "rivers"
                            and geom.geom_type == "LineString"
                        ):
                            # Convert points to shapely line
                            line = geom

                            river_width = stroke_width
                            outline_width = 0.1

                            # Create buffered river shape
                            river_poly = line.buffer(
                                river_width / 2,
                                cap_style=self.buffer_cap_style,
                                join_style=self.buffer_join_style,
                            )

                            # Draw only the exterior as stroke
                            layer.add(
                                dwg.polyline(
                                    points=list(river_poly.exterior.coords),
                                    fill="none",
                                    stroke=stroke_color,
                                    stroke_width=outline_width,
                                )
                            )
                            continue

                        # Buffer the line into a thin Polygon strip (like a fat line)
                        # This creates an actual **closed polygon** around the road centerline, filled with the stroke color.

                        # Use short segments to avoid self-intersections
                        line = LineString(points)

                        # Check if the line has no self-intersections
                        if line.is_simple:  # No self-intersections

                            # line.buffer(d) expands the line into a 2D polygon by extending a distance d on both sides of the line.
                            buffered = line.buffer(
                                stroke_width / 2,
                                cap_style=self.buffer_cap_style,
                                join_style=self.buffer_join_style,
                            )

                            # Check if the buffer is valid and has no holes
                            if (
                                not buffered.is_empty
                                and buffered.geom_type == "Polygon"
                                and len(buffered.interiors) == 0
                            ):
                                poly_points = list(buffered.exterior.coords)
                                layer.add(
                                    dwg.polygon(
                                        points=poly_points,
                                        fill=stroke_color.lower(),
                                        stroke="none",
                                    )
                                )
                            else:
                                # Fallback: Cut the line into short segments
                                # logger.info(layer.attribs["id"])
                                self._add_segmented_line(
                                    layer, dwg, line, stroke_color, stroke_width
                                )
                        else:
                            # Complex line with self-intersections: cut into segments
                            logger.error(
                                f"UNEXPECTED (Unusual) - Complex line with self-intersections: {layer.attribs['id']}"
                            )
                            self._add_segmented_line(
                                layer, dwg, line, stroke_color, stroke_width
                            )

                    else:
                        # Xtool ignores `stroke-width`. It only sees lines without width!
                        layer.add(dwg.polyline(points, **line_style))

            # ---------------------------
            # Polygons (water bodies, buildings, etc.)
            # ---------------------------
            elif geom.geom_type == "Polygon":
                points = [(x, y) for x, y in geom.exterior.coords]
                layer.add(
                    dwg.polygon(
                        points,
                        fill=(
                            random.choice(fill_color).lower()
                            if isinstance(fill_color, list)
                            else fill_color.lower()
                        ),
                        stroke=stroke_color.lower(),
                        stroke_width=stroke_width,
                    )
                )

            # ---------------------------
            # MultiPolygons
            # ---------------------------
            elif geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    points = [(x, y) for x, y in poly.exterior.coords]
                    layer.add(
                        dwg.polygon(
                            points,
                            fill=(
                                random.choice(fill_color).lower()
                                if isinstance(fill_color, list)
                                else fill_color.lower()
                            ),
                            stroke=stroke_color.lower(),
                            stroke_width=stroke_width,
                        )
                    )
            else:
                logger.error(f"Unsupported geometry type: {geom.geom_type}")

    def _add_dashed_line_as_polygons(
        self, layer, dwg, line, stroke_color, stroke_width, dash_pattern
    ):
        """
        Convert a LineString into dashed polygons (for XTool) with specified stroke width and dash pattern.
         Args:
            layer: svgwrite layer/group
            dwg: svgwrite drawing
            line: Shapely LineString
            stroke_color: color for the dashes
            stroke_width: width of the stroke
            dash_pattern: list of lengths [dash, gap, dash, gap, ...]
        """
        if line.is_empty or len(line.coords) < 2:
            return

        # Compute total length of the line
        total_length = line.length
        pattern = np.array(dash_pattern, dtype=float)

        # Starting at distance 0 along the line
        pos = 0.0
        pattern_index = 0
        segment_polys = []

        while pos < total_length:
            segment_len = pattern[pattern_index % len(pattern)]
            end_pos = min(pos + segment_len, total_length)

            # Only create polygon for "dash" segments (even indices)
            if pattern_index % 2 == 0:
                start_pt = line.interpolate(pos)
                end_pt = line.interpolate(end_pos)
                segment = LineString([start_pt.coords[0], end_pt.coords[0]])
                buffered = segment.buffer(
                    stroke_width / 2,
                    cap_style=self.buffer_cap_style,
                    join_style=self.buffer_join_style,
                )
                if not buffered.is_empty:
                    segment_polys.append(buffered)

            pos = end_pos
            pattern_index += 1

        # Merge all dash polygons
        if segment_polys:
            merged = unary_union(segment_polys)
            if merged.geom_type == "Polygon":
                layer.add(
                    dwg.polygon(
                        points=list(merged.exterior.coords),
                        fill=stroke_color,
                        stroke="none",
                    )
                )
            elif merged.geom_type == "MultiPolygon":
                for poly in merged.geoms:
                    layer.add(
                        dwg.polygon(
                            points=list(poly.exterior.coords),
                            fill=stroke_color,
                            stroke="none",
                        )
                    )

    def _add_segmented_line(self, layer, dwg, line, stroke_color, stroke_width):
        """
        Cup a complex line into short segments
        Each segment is buffered individually.
        """
        coords = list(line.coords)
        if len(coords) < 2:
            return

        # Create short segments (e.g. 5% of total length)
        total_length = line.length
        segment_length = max(
            total_length * 0.05, stroke_width * 2
        )  # At least 2x stroke width

        # Interpolate points along the line
        distances = np.arange(0, total_length, segment_length)
        if distances[-1] < total_length:
            distances = np.append(distances, total_length)

        # Create segments
        for i in range(len(distances) - 1):
            start_point = line.interpolate(distances[i])
            end_point = line.interpolate(distances[i + 1])

            segment = LineString([start_point.coords[0], end_point.coords[0]])
            buffered = segment.buffer(
                stroke_width / 2,
                cap_style=self.buffer_cap_style,
                join_style=self.buffer_join_style,
            )

            if not buffered.is_empty and buffered.geom_type == "Polygon":
                poly_points = list(buffered.exterior.coords)
                layer.add(
                    dwg.polygon(
                        points=poly_points, fill=stroke_color.lower(), stroke="none"
                    )
                )
            else:
                logger.error("Failed to create buffered polygon for segment")

    def convert(self):
        """Main conversion method."""
        logger.info(f"Converting {self.osm_path} to SVG...")

        # Parse OSM data
        gdfs = self.parse_osm_data()

        # Project and transform
        transformed_gdfs, svg_dims = self.project_and_transform_geometries(gdfs)

        # Create SVG
        return self.create_svg(transformed_gdfs, svg_dims), transformed_gdfs

    def get_scale_info(self):
        """
        Return scale information for external use.
        Returns None if convert() hasn't been called yet.
        """
        if hasattr(self, "scale_info"):
            return self.scale_info
        return None

    def extract_all_names_with_tags(self, use_print=True):
        """
        Extract all names from OSM with their tags and group them into meaningful categories.
        Returns a dict: {group_name: set of names}
        """
        handler = self.OSMHandler(self)
        handler.apply_file(str(self.osm_path), locations=True)

        all_names = handler.all_names
        logger.info(f"Total names found: {len(all_names)}\n")

        # Define groups and associated tag keys
        group_definitions = {
            "Streets/Roads": ["highway", "cycleway", "foot", "motorroad"],
            "Places": ["place"],
            "Admin": ["boundary", "admin_level", "city_limit"],
            "Rivers/Water": ["waterway", "reservoir_type", "tidal"],
            "Natural": ["natural", "trees", "backcountry", "hiking"],
            "Buildings/Landmarks": [
                "building",
                "castle_type",
                "memorial",
                "artwork_type",
                "site",
                "monument",
            ],
            "Amenities/Services": [
                "amenity",
                "bar",
                "bench",
                "brewery",
                "post_office",
                "school:FR",
                "healthcare",
            ],
            "Leisure/Tourism/Culture": [
                "leisure",
                "tourism",
                "historic",
                "pilgrimage",
                "artist_name",
            ],
            "Utilities/Infrastructure": [
                "power",
                "substation",
                "transformer",
                "voltage",
                "charge",
            ],
        }

        grouped_names = {group: set() for group in group_definitions}
        grouped_names["Other"] = set()

        all_tag_keys = set()

        # Assign names to groups
        for entry in all_names:
            name = entry["name"]
            tags = entry["tags"]
            all_tag_keys.update(tags.keys())

            assigned = False
            for group, keys in group_definitions.items():
                if any(k in tags for k in keys):
                    grouped_names[group].add(name)
                    assigned = True
                    break
            if not assigned:
                grouped_names["Other"].add(name)

        # Print grouped names
        for group, names in grouped_names.items():
            if names:
                logger.info(f"--- {group} ({len(names)}) ---")
                if use_print:
                    # print()
                    for n in sorted(names):
                        logger.info(n)

        # Print all tag keys encountered
        # logger.info(f"\nAll tag keys encountered in dataset:\n{sorted(all_tag_keys)}")

        return grouped_names
