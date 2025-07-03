import geopandas as gpd
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # Use Agg backend for Matplotlib
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.offsetbox import AnnotationBbox, OffsetImage  # noqa: E402
from PIL import Image  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402


# Load hex map
def load_hex_map(hex_map_path):
    hex_map = gpd.read_file(hex_map_path)
    return hex_map


# Load post_label to 3CODE mapping
def load_post_label_mapping(post_label_mapping_path):
    post_label_mapping = pd.read_csv(post_label_mapping_path)
    return post_label_mapping


# Load a random heart image from the directory
def load_random_heart_image(heart_dir, size):
    heart_images = [f for f in os.listdir(heart_dir) if f.endswith(".png")]
    selected_heart = os.path.join(
        heart_dir, random.choice(heart_images)
    )  # Randomly select a heart PNG
    heart_img = Image.open(selected_heart)
    heart_img.thumbnail((size, size))  # Resize the image for better fit
    return heart_img


# Plot hex map with hearts
def plot_hex_map_with_hearts(
    hex_map, post_label_mapping, heart_dir, output_path, dpi=300
):
    fig, ax = plt.subplots(
        1, 1, figsize=(33.1, 46.8), dpi=dpi
    )  # A0 size: 33.1 x 46.8 inches
    hex_map.plot(ax=ax, color="white", edgecolor="white")  # Use white for edges
    ax.set_axis_off()  # Hide the axis

    # Find the bounds of the hex map
    # Returns (minx, miny, maxx, maxy)
    bounds = hex_map.geometry.total_bounds
    # padding = 0.1 # F841: local variable 'padding' is assigned to but never used
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect("equal")  # Set aspect ratio to be equal

    # Plot hearts for all locations
    for location in post_label_mapping["post_label"]:
        location_code = post_label_mapping.loc[
            post_label_mapping["post_label"] == location, "name"
        ]
        if not location_code.empty:
            location_code = location_code.iloc[0]
            location_geom = hex_map[hex_map["name"] == location_code]
            if not location_geom.empty:
                centroid = location_geom.geometry.centroid.iloc[0]

                # Load a random heart image from the directory
                heart_img = load_random_heart_image(heart_dir, size=400)

                imagebox = OffsetImage(
                    heart_img, zoom=0.1
                )  # Adjust zoom for better fit
                ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                ax.add_artist(ab)

    # Save the plot as an image in the specified directory with tight bounding box
    plt.savefig(output_path, bbox_inches="tight")
    plt.close(fig)  # Close the plot to free memory


if __name__ == "__main__":
    hex_map_path = "data/20241105_usa_esri_v2.shp"
    post_label_mapping_path = "data/post_label to 3CODE.csv"
    # Directory containing different colored heart PNGs
    heart_dir = "static/heart_icons"
    output_path = "output/A0_prayer_map.png"
    dpi = 300  # Set high DPI for print quality

    hex_map = load_hex_map(hex_map_path)
    post_label_mapping = load_post_label_mapping(post_label_mapping_path)
    plot_hex_map_with_hearts(hex_map, post_label_mapping, heart_dir, output_path, dpi)
    print(f"A0 size map saved to {output_path}")
