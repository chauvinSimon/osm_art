import argparse

from utils.utils import res_dir, yaml_load
from utils.utils_names import add_labels_to_svg, clean_name
from utils.utils_osm import logger


def apply_name_selection(name_positions_dir):
    name_positions = yaml_load(name_positions_dir / "name_positions.yaml")

    selected_name_positions = {}
    for name_svg_path in (name_positions_dir / "individual_maps").glob("*.svg"):
        name = name_svg_path.stem
        if name not in name_positions:
            logger.warning(f"Name {name} not found in name_positions")
            continue
        selected_name_positions[name] = name_positions[name]
    logger.info(f"{len(selected_name_positions)} names selected")

    add_labels_to_svg(
        svg_path=name_positions_dir / "map_no_names.svg",
        name_positions=selected_name_positions,
        output_path=name_positions_dir / f"map_selected_names.svg",
        font_size=1,
    )

    # export names to txt
    with open(name_positions_dir / "selected_names.txt", "w") as f:
        for name in sorted(selected_name_positions):
            f.write(f"{clean_name(name)}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Apply name selection defined in `name_positions.yaml`."
    )
    parser.add_argument("project_name", type=str)
    args = parser.parse_args()

    apply_name_selection(
        name_positions_dir=res_dir / args.project_name / "names",
    )
