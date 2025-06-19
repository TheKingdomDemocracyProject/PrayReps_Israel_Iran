import geopandas as gpd
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from PIL import Image, ImageFile
import random
import os

# Ensure PIL doesn't use tkinter
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Load hex map
def load_hex_map(hex_map_path):
    hex_map = gpd.read_file(hex_map_path)
    return hex_map

# Load post_label to 3CODE mapping
def load_post_label_mapping(post_label_mapping_path):
    post_label_mapping = pd.read_csv(post_label_mapping_path)
    return post_label_mapping

# Load a random heart PNG image from the directory
def load_random_heart_image():
    heart_dir = 'static/heart_icons'
    heart_pngs = [f for f in os.listdir(heart_dir) if f.endswith('.png')]
    
    # Select a random heart PNG file
    heart_png_path = os.path.join(heart_dir, random.choice(heart_pngs))
    
    # Load the image with PIL
    heart_img = Image.open(heart_png_path).convert("RGBA")
    heart_img.thumbnail((50, 50))  # Resize the image for better fit
    return heart_img

# Plot hex map with white fill color and light grey boundaries
def plot_hex_map_with_hearts(hex_map_gdf, post_label_mapping_df, prayed_for_items_list, queue_items_list, country_code):
    fig, ax = plt.subplots(1, 1, figsize=(25, 25))

    if hex_map_gdf is None or hex_map_gdf.empty:
        logging.error(f"Hex map data is missing or empty for country {country_code}. Cannot plot map.")
        plt.close(fig)
        return

    hex_map_gdf.plot(ax=ax, color='white', edgecolor='lightgrey')
    ax.set_axis_off()

    bounds = hex_map_gdf.geometry.total_bounds
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect('equal')

    logging.info(f"Plotting map for country: {country_code}. Prayed items: {len(prayed_for_items_list)}, Queue items: {len(queue_items_list)}")

    if country_code in ['israel', 'iran']:
        # Random Allocation Strategy
        if 'id' not in hex_map_gdf.columns:
            logging.error(f"'id' column missing in hex_map_gdf for {country_code}. Cannot apply random allocation.")
            plt.close(fig)
            return

        num_hearts = len(prayed_for_items_list)
        all_hex_ids = list(hex_map_gdf['id'].unique())

        if not all_hex_ids:
            logging.warning(f"No hex IDs found in map data for {country_code}. Cannot place hearts.")
            # Still save the empty map
        else:
            sorted_hex_ids = sorted(all_hex_ids)
            hex_ids_to_color = sorted_hex_ids[:num_hearts]

            for hex_id_to_color in hex_ids_to_color:
                location_geom = hex_map_gdf[hex_map_gdf['id'] == hex_id_to_color]
                if not location_geom.empty:
                    centroid = location_geom.geometry.centroid.iloc[0]
                    heart_img = load_random_heart_image()
                    imagebox = OffsetImage(heart_img, zoom=0.6)
                    ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                    ax.add_artist(ab)
                else:
                    logging.warning(f"Geometry not found for hex ID {hex_id_to_color} in {country_code}.")
        # Queue highlighting is not implemented for this strategy as per requirements.

    else:
        # Specific Mapping Strategy (for other potential countries)
        if post_label_mapping_df is None or post_label_mapping_df.empty:
            logging.error(f"Post label mapping is missing or empty for {country_code}. Cannot map items to hexes.")
            # Continue to save the map without hearts/highlights if this data is crucial
        elif not all(col in post_label_mapping_df.columns for col in ['post_label', 'name']):
            logging.error(f"Required columns ('post_label', 'name') not in post_label_mapping_df for {country_code}.")
        else:
            prayed_locations_labels = [item.get('post_label', "") for item in prayed_for_items_list]
            for location_label in prayed_locations_labels:
                location_code_series = post_label_mapping_df.loc[post_label_mapping_df['post_label'] == location_label, 'name']
                if not location_code_series.empty:
                    location_code = location_code_series.iloc[0]
                    if 'name' not in hex_map_gdf.columns:
                        logging.error(f"'name' column missing in hex_map_gdf for {country_code}. Cannot map by name.")
                        continue # or break, depending on desired behavior
                    location_geom = hex_map_gdf[hex_map_gdf['name'] == location_code]
                    if not location_geom.empty:
                        centroid = location_geom.geometry.centroid.iloc[0]
                        heart_img = load_random_heart_image()
                        imagebox = OffsetImage(heart_img, zoom=0.6)
                        ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                        ax.add_artist(ab)
                    else:
                        logging.debug(f"No geometry found for location code {location_code} (from label {location_label}) in {country_code}.")
                else:
                    logging.debug(f"No mapping found for post_label {location_label} in {country_code}.")

            # Queue Highlighting for Specific Strategy
            if queue_items_list and post_label_mapping_df is not None and not post_label_mapping_df.empty:
                # Filter queue for items belonging to the current country_code
                country_specific_queue = [item for item in queue_items_list if item.get('country_code') == country_code]
                if country_specific_queue:
                    top_queue_item = country_specific_queue[0] # Highlight top item for this country
                    top_queue_post_label = top_queue_item.get('post_label', "")
                    location_code_series_q = post_label_mapping_df.loc[post_label_mapping_df['post_label'] == top_queue_post_label, 'name']
                    if not location_code_series_q.empty:
                        location_code_q = location_code_series_q.iloc[0]
                        if 'name' in hex_map_gdf.columns:
                            location_geom_q = hex_map_gdf[hex_map_gdf['name'] == location_code_q]
                            if not location_geom_q.empty:
                                # Using .iloc[0].exterior.coords might be problematic if geometry is MultiPolygon.
                                # A safer way is to directly use the geometry object if it's simple.
                                geom_to_highlight = location_geom_q.geometry.iloc[0]
                                if geom_to_highlight.geom_type == 'Polygon':
                                    hex_patch = Polygon(geom_to_highlight.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.5, linewidth=2)
                                    ax.add_patch(hex_patch)
                                elif geom_to_highlight.geom_type == 'MultiPolygon':
                                     for poly in geom_to_highlight.geoms: # iterate over polygons in MultiPolygon
                                        hex_patch = Polygon(poly.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.5, linewidth=2)
                                        ax.add_patch(hex_patch)
                                else:
                                    logging.warning(f"Geometry type {geom_to_highlight.geom_type} not directly supported for highlighting for {location_code_q} in {country_code}.")
                            else:
                                logging.debug(f"No geometry for queue highlight for {location_code_q} (from label {top_queue_post_label}) in {country_code}.")
                        else:
                             logging.error(f"'name' column missing in hex_map_gdf for {country_code}, cannot highlight queue item by name.")
                    else:
                        logging.debug(f"No mapping for queue highlight for post_label {top_queue_post_label} in {country_code}.")
                else:
                    logging.debug(f"Queue for country {country_code} is empty or items are not for this country. No highlight.")
            elif not queue_items_list:
                logging.debug(f"Global queue is empty. No highlight for country {country_code}.")

    plt.savefig('static/hex_map.png', bbox_inches='tight', pad_inches=0.5)
    plt.close(fig)  # Close the plot to free memory
import logging # Ensure logging is imported if not already

# Example usage for Case 2
if __name__ == "__main__":
    # This example usage will likely need adjustment due to new function signature
    # and reliance on specific country_code logic.
    # For now, commenting out to prevent errors as heart_img_path is not defined here
    # and country_code is missing.
    # hex_map_path = 'data/20241105_usa_esri_v2.shp'
    # post_label_mapping_path = 'data/post_label to 3CODE.csv'
    # prayed_for_items = []
    # queue_items = [{'post_label': 'Croydon West', 'country_code': 'default'}] # Example
    # default_country = 'default' # Example country code

    # hex_map_data = load_hex_map(hex_map_path)
    # post_label_map_data = load_post_label_mapping(post_label_mapping_path)
    # plot_hex_map_with_hearts(hex_map_data, post_label_map_data, prayed_for_items, queue_items, default_country)
    pass # Placeholder for now
