import svgwrite

from utils.utils_log import logger


def create_scale_bar(
    svg_path="scale_bar.svg",
    total_cm=4.328,
    bar_height_mm=3,
    tick_height_mm_main=5,
    tick_height_mm_minor=3,
    stroke_color="black",
    stroke_width_mm=0.5,
):
    """
    Create a horizontal scale bar SVG with ticks above the bar only.
    """
    # Convert total length to mm
    total_mm = total_cm * 10

    # SVG dimensions (add padding)
    width_mm = total_mm + 10
    height_mm = bar_height_mm + tick_height_mm_main + 10  # enough height for main ticks

    dwg = svgwrite.Drawing(
        svg_path,
        size=(f"{width_mm}mm", f"{height_mm}mm"),
        viewBox=f"0 0 {width_mm} {height_mm}",
    )

    # Base horizontal bar
    bar_y = height_mm - 5 - bar_height_mm  # leave bottom padding
    dwg.add(
        dwg.rect(insert=(5, bar_y), size=(total_mm, bar_height_mm), fill=stroke_color)
    )

    # Tick positions in mm
    ticks_main = [0, total_mm / 2, total_mm]  # 0m, 500m, 1km
    ticks_minor = [total_mm / 4, 3 * total_mm / 4]  # 250m, 750m

    # Draw main ticks (above bar)
    for x in ticks_main:
        dwg.add(
            dwg.line(
                start=(5 + x, bar_y - tick_height_mm_main),
                end=(5 + x, bar_y + bar_height_mm),
                stroke=stroke_color,
                stroke_width=stroke_width_mm,
            )
        )

    # Draw minor ticks (above bar)
    for x in ticks_minor:
        dwg.add(
            dwg.line(
                start=(5 + x, bar_y - tick_height_mm_minor),
                end=(5 + x, bar_y + bar_height_mm),
                stroke=stroke_color,
                stroke_width=stroke_width_mm,
            )
        )

    dwg.save()
    logger.info(f"Scale bar saved to {svg_path}")


if __name__ == "__main__":
    create_scale_bar()
