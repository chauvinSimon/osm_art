import unicodedata
from xml.etree import ElementTree as ET

from utils.utils_osm import logger


def remove_accents(text):
    # Normalize text to NFD (Normalization Form Decomposed)
    text = unicodedata.normalize("NFD", text)
    # Filter out combining characters (like accents)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def clean_name(name):
    return name
    # return remove_accents(name).upper()


def get_svg_name_positions(transformed_gdfs, group_names=None):
    """
    Compute approximate positions of names on the SVG.
    Returns dict: {name: (x, y)}
    """
    name_positions = {}

    # Include named nodes and named ways
    layers_to_check = ["named_nodes", "named_ways"]

    for layer_name in layers_to_check:
        gdf = transformed_gdfs.get(layer_name)
        if gdf is None or gdf.empty:
            continue

        for _, row in gdf.iterrows():
            tags = row["tags"]
            name = tags.get("name")
            if not name:
                continue
            if group_names and name not in group_names:
                continue

            geom = row["geometry"]
            # If it's a polygon or linestring, take centroid
            if geom.geom_type in [
                "Polygon",
                "MultiPolygon",
                "LineString",
                "MultiLineString",
            ]:
                pos = geom.centroid
            elif geom.geom_type == "Point":
                pos = geom
            else:
                continue

            while name in name_positions:
                logger.warning(
                    f"Duplicate name: {name} "
                    f"at ({pos.x}, {pos.y}) and "
                    f"at ({name_positions[name][0]}, {name_positions[name][1]})"
                )
                name += "_"
            name_positions[name] = (pos.x, pos.y)

    return name_positions


def add_labels_to_svg(
    svg_path,
    name_positions,
    output_path=None,
    font_size=3,
    font_colour="red",
    background_colour="yellow",
    background_opacity=0.2,
):
    """
    Add name labels to an existing SVG.

    Parameters:
    - svg_path: path to the existing SVG
    - name_positions: dict {name: (x, y)}
    - output_path: path to save the new SVG (default: add '_labeled' suffix)
    - font_size: size of the label text in SVG units (mm)
    """
    if output_path is None:
        output_path = str(svg_path).replace(".svg", "_labeled.svg")

    # Parse existing SVG
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # Wrap existing content in <g> with scaling and opacity
    original_content = list(root)
    for elem in original_content:
        root.remove(elem)

    content_group = ET.Element("g", opacity=str(background_opacity))
    for elem in original_content:
        content_group.append(elem)
    root.append(content_group)

    # Add labels group
    labels_group = ET.Element(
        "g",
        id="labels",
        style=f"font-family:Consolas;font-size:{font_size}mm;fill:{font_colour}",
    )

    for name, (x, y) in name_positions.items():
        # Estimate text size
        text_width = len(name) * font_size * 2.2  # rough mm estimate
        text_height = font_size * 4.0

        # Background rectangle
        rect_elem = ET.Element(
            "rect",
            x=str(x),
            y=str(y - text_height * 0.8),
            width=str(text_width),
            height=str(text_height),
            fill=background_colour,
        )

        # Text element
        text_elem = ET.Element("text", x=str(x), y=str(y))
        text_elem.text = name

        # Append in correct order
        labels_group.append(rect_elem)
        labels_group.append(text_elem)

    root.append(labels_group)

    # Add background colour (white)
    background = ET.Element(
        "rect", x="0", y="0", width="100%", height="100%", fill="white"
    )
    root.insert(0, background)

    # Save new SVG
    tree.write(output_path)
    logger.debug(f"Labeled SVG saved to {output_path}")
