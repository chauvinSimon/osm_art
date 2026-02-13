import argparse
import shutil

import cairosvg

from utils.utils import load_config, osm_dir, res_dir, yaml_dump
from utils.utils_log import logger
from utils.utils_names import add_labels_to_svg, get_svg_name_positions
from utils.utils_osm import OSMToSVGConverter
from utils.utils_scale import create_scale_bar


def main(
    project_name: str,
    save_name_maps=False,
    print_all_available_names=False,
    project_name_suffix="",
):
    osm_path = osm_dir / f"{project_name}.osm"
    assert osm_path.exists(), f"{osm_path} does not exist"

    project_name = osm_path.stem + project_name_suffix
    project_dir = res_dir / project_name
    project_dir.mkdir(exist_ok=True, parents=True)

    config = load_config()
    project_config = config["projects"][osm_path.stem]
    north, west, east, south = project_config["nwes"]
    nswe_bounds = (north, south, west, east)
    target_width_cm = project_config.get("width_cm", None)
    target_height_cm = project_config.get("height_cm", None)

    # Initialize converter
    converter = OSMToSVGConverter(
        osm_path=osm_path,
        svg_out_path=project_dir / f"{project_name}.svg",
        target_width_cm=target_width_cm,
        target_height_cm=target_height_cm,
        margin_mm=0,
        # fill_paths=False,  # for visualization
        fill_paths=True,  # for xtools
        osm_config=config["osm"],
        nswe_bounds=nswe_bounds,
    )

    # Convert
    svg_saving_path, transformed_gdfs = converter.convert()
    assert svg_saving_path == project_dir / f"{project_name}.svg"
    logger.info(f"Conversion complete: {svg_saving_path}")
    cairosvg.svg2png(
        url=str(svg_saving_path), write_to=str(svg_saving_path.with_suffix(".png"))
    )

    # Get scale information
    scale_info = converter.get_scale_info()
    if scale_info:
        logger.info(f"Map scale: 1:{scale_info['scale_ratio']}")
        logger.info(f"1cm on map = {scale_info['meters_per_cm']:.2f}m in reality")

    # create scale
    create_scale_bar(
        svg_path=project_dir / f"{project_name}_scale_bar.svg",
        total_cm=scale_info["one_km_in_reality_in_cm"],
    )

    if save_name_maps:
        grouped_names = converter.extract_all_names_with_tags(
            use_print=print_all_available_names,
        )
        group_names = set()
        for cat in config["name_categories"]:
            if not cat in grouped_names:
                logger.warning(f"Category {cat} not found in grouped_names")
                continue
            group_names.update(grouped_names[cat])
        name_positions = get_svg_name_positions(
            transformed_gdfs, group_names=group_names
        )
        # order alphabetically
        name_positions = dict(sorted(name_positions.items()))
        # only keep first 5  # for debug
        # name_positions = dict(list(name_positions.items())[:5])

        # drop strange names, e.g. containing "/"
        for name in list(name_positions.keys()):
            if "/" in name:
                logger.warning(f"Dropping name {name}")
                del name_positions[name]

        # Rimini: only keep names containing one of ["Via", "Viale"]
        # for name in list(name_positions.keys()):
        #     if not any(word in name.lower() for word in ["via", "viale"]):
        #         del name_positions[name]

        names_saving_dir = project_dir / "names"
        names_saving_dir.mkdir(exist_ok=True)
        if save_name_maps:
            individual_dir = names_saving_dir / "individual_maps"
            individual_dir.mkdir(exist_ok=True)
            # Save maps with single name
            for name, (x, y) in name_positions.items():
                name_svg_path = individual_dir / f"{name}.svg"
                add_labels_to_svg(
                    svg_path=svg_saving_path,
                    name_positions={name: (x, y)},
                    output_path=str(name_svg_path),
                    font_size=1,
                )
                # cairosvg.svg2png(url=str(name_svg_path), write_to=str(name_svg_path.with_suffix(".png")))

            # save names
            yaml_dump(name_positions, names_saving_dir / "name_positions.yaml")
            # copy svg_path to names_saving_dir
            shutil.copy(svg_saving_path, names_saving_dir / "map_no_names.svg")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert a .osm file exported from https://www.openstreetmap.org/export "
        "to a .svg file importable to `xTool Studio`."
    )
    parser.add_argument("project_name", type=str)
    parser.add_argument("--project_name_suffix", type=str, default="")
    parser.add_argument("--save_name_maps", action="store_true")
    parser.add_argument("--print_all_available_names", action="store_true")
    args = parser.parse_args()

    main(
        project_name=args.project_name,
        project_name_suffix=args.project_name_suffix,
        save_name_maps=args.save_name_maps,
        print_all_available_names=args.print_all_available_names,
    )
