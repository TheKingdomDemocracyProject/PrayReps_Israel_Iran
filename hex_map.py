import logging
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

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Load hex map
def load_hex_map(hex_map_path):
    try:
        hex_map = gpd.read_file(hex_map_path)
        return hex_map
    except Exception as e:
        logging.error(f"Error reading GeoJSON file at {hex_map_path}: {e}", exc_info=True)
        return None

# Load post_label to 3CODE mapping
def load_post_label_mapping(post_label_mapping_path):
    post_label_mapping = pd.read_csv(post_label_mapping_path)
    return post_label_mapping

# Load a random heart PNG image from the directory
def load_random_heart_image():
    # APP_ROOT should already be defined at the global scope in hex_map.py
    heart_dir = os.path.join(APP_ROOT, 'static/heart_icons')

    if not os.path.isdir(heart_dir):
        logging.error(f"Heart icons directory not found: {heart_dir}")
        return None

    heart_pngs = [f for f in os.listdir(heart_dir) if f.endswith('.png')]
    if not heart_pngs:
        logging.error(f"No PNG images found in heart icons directory: {heart_dir}")
        return None
    
    heart_png_path = os.path.join(heart_dir, random.choice(heart_pngs))
    logging.debug(f"Loading random heart image from: {heart_png_path}")
    try:
        heart_img = Image.open(heart_png_path).convert("RGBA")
        heart_img.thumbnail((25, 25))  # Resize the image
        return heart_img
    except FileNotFoundError:
        logging.error(f"Heart image file not found: {heart_png_path}")
        return None
    except Exception as e:
        logging.error(f"Error loading heart image {heart_png_path}: {e}")
        return None

# Plot hex map with white fill color and light grey boundaries
def plot_hex_map_with_hearts(hex_map_gdf, post_label_mapping_df, prayed_for_items_list, queue_items_list, country_code):
    # ==== DETAILED LOGGING START ====
    logging.info(f"[plot_hex_map_with_hearts] Processing country_code: {country_code}")
    logging.info(f"[plot_hex_map_with_hearts] Number of prayed_for_items_list: {len(prayed_for_items_list)}")
    logging.info(f"[plot_hex_map_with_hearts] Number of queue_items_list: {len(queue_items_list)}")
    # ==== DETAILED LOGGING END ====

    logging.info(f"Plotting hex map for country {country_code}. Output path: {os.path.join(APP_ROOT, 'static/hex_map.png')}")
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))

    if hex_map_gdf is None or hex_map_gdf.empty:
        logging.error(f"Hex map data is missing or empty for country {country_code}. Cannot plot map.")
        plt.close(fig)
        return

    # Original line:
    # hex_map_gdf.plot(ax=ax, color='white', edgecolor='lightgrey')
    # ax.set_axis_off()

    if country_code in ['israel', 'iran']:
        num_prayed = len(prayed_for_items_list)
        # Determine a base color for hexes based on whether num_prayed is even or odd
        # This ensures a very obvious visual change if num_prayed changes.
        fill_color_for_hexes = 'lightyellow' if num_prayed % 2 == 0 else 'lightcyan'
        logging.info(f"DEBUG IR/ISR: num_prayed={num_prayed}, hex_fill_color={fill_color_for_hexes}")
        hex_map_gdf.plot(ax=ax, color=fill_color_for_hexes, edgecolor='lightgrey')
    else:
        # Default behavior for other countries
        hex_map_gdf.plot(ax=ax, color='white', edgecolor='lightgrey')

    ax.set_axis_off() # Ensure axis is turned off after plotting

    bounds = hex_map_gdf.geometry.total_bounds
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect('equal')

    logging.info(f"Plotting map for country: {country_code}. Prayed items: {len(prayed_for_items_list)}, Queue items: {len(queue_items_list)}")

    if country_code in ['israel', 'iran']:
        # ==== DETAILED LOGGING FOR ISRAEL/IRAN START ====
        logging.info(f"[plot_hex_map_with_hearts - {country_code}] Using Random Allocation Strategy.")
        # ==== DETAILED LOGGING FOR ISRAEL/IRAN END ====
        # Random Allocation Strategy
        if 'id' not in hex_map_gdf.columns:
            logging.error(f"'id' column missing in hex_map_gdf for {country_code}. Cannot apply random allocation.")
            plt.close(fig)
            return

        num_hearts = len(prayed_for_items_list)
        # ==== DETAILED LOGGING FOR ISRAEL/IRAN START ====
        logging.info(f"[plot_hex_map_with_hearts - {country_code}] num_hearts to be plotted: {num_hearts}")
        # ==== DETAILED LOGGING FOR ISRAEL/IRAN END ====
        all_hex_ids = list(hex_map_gdf['id'].unique())

        if not all_hex_ids:
            logging.warning(f"No hex IDs found in map data for {country_code}. Cannot place hearts.")
            # Still save the empty map
        else:
            sorted_hex_ids = sorted(all_hex_ids)
            hex_ids_to_color = sorted_hex_ids[:num_hearts]
            # ==== DETAILED LOGGING FOR ISRAEL/IRAN START ====
            logging.info(f"[plot_hex_map_with_hearts - {country_code}] hex_ids_to_color (first 5 if many): {hex_ids_to_color[:5]}")
            if len(hex_ids_to_color) > 5:
                logging.info(f"[plot_hex_map_with_hearts - {country_code}] ... and {len(hex_ids_to_color) - 5} more hex_ids_to_color.")
            # ==== DETAILED LOGGING FOR ISRAEL/IRAN END ====

            for hex_id_to_color in hex_ids_to_color:
                location_geom = hex_map_gdf[hex_map_gdf['id'] == hex_id_to_color]
                if not location_geom.empty:
                    centroid = location_geom.geometry.centroid.iloc[0]
                    heart_img = load_random_heart_image()
                    if heart_img: # Check if heart_img is not None
                        imagebox = OffsetImage(heart_img, zoom=0.6)
                        ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                        ax.add_artist(ab)
                    else:
                        logging.warning(f"Skipping heart placement for a hex in {country_code} due to missing heart image.")
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
                        if heart_img: # Check if heart_img is not None
                            imagebox = OffsetImage(heart_img, zoom=0.6)
                            ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                            ax.add_artist(ab)
                        else:
                            logging.warning(f"Skipping heart placement for a hex in {country_code} due to missing heart image.")
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

    # Conditional Highlighting for Top Queue Item
    if queue_items_list: # Check if queue is not empty
        top_queue_item = queue_items_list[0]
        # ==== DETAILED LOGGING FOR ISRAEL/IRAN START ====
        if country_code in ['israel', 'iran']:
            if top_queue_item.get('country_code') == country_code:
                logging.info(f"[plot_hex_map_with_hearts - {country_code}] Top queue item ({top_queue_item.get('person_name')}) matches current country. Attempting highlighting.")
            else:
                logging.info(f"[plot_hex_map_with_hearts - {country_code}] Top queue item country ({top_queue_item.get('country_code')}) does not match current country. No highlight.")
        # ==== DETAILED LOGGING FOR ISRAEL/IRAN END ====
        if top_queue_item.get('country_code') == country_code: # Only highlight if top item matches current map's country
            logging.info(f"Attempting to highlight top queue item for {country_code}: {top_queue_item.get('person_name')}")
            if country_code in ['israel', 'iran']:
                # Random Allocation: Highlight the 'next' hex
                if hex_map_gdf is not None and not hex_map_gdf.empty and 'id' in hex_map_gdf.columns:
                    num_hearts_already_plotted = len(prayed_for_items_list)
                    all_hex_ids = list(hex_map_gdf['id'].unique())
                    sorted_hex_ids = sorted(all_hex_ids)

                    # ==== DETAILED LOGGING FOR ISRAEL/IRAN START ====
                    logging.info(f"[plot_hex_map_with_hearts - {country_code}] num_hearts_already_plotted for highlight check: {num_hearts_already_plotted}")
                    logging.info(f"[plot_hex_map_with_hearts - {country_code}] Total hexes available for highlight check: {len(sorted_hex_ids)}")
                    # ==== DETAILED LOGGING FOR ISRAEL/IRAN END ====

                    if num_hearts_already_plotted < len(sorted_hex_ids):
                        hex_id_to_highlight = sorted_hex_ids[num_hearts_already_plotted]
                        # ==== DETAILED LOGGING FOR ISRAEL/IRAN START ====
                        logging.info(f"[plot_hex_map_with_hearts - {country_code}] Attempting to highlight hex_id: {hex_id_to_highlight}")
                        # ==== DETAILED LOGGING FOR ISRAEL/IRAN END ====
                        location_geom_q = hex_map_gdf[hex_map_gdf['id'] == hex_id_to_highlight]
                        if not location_geom_q.empty:
                            geom = location_geom_q.geometry.iloc[0]
                            if geom.geom_type == 'Polygon':
                                hex_patch = Polygon(geom.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.8, linewidth=2)
                                ax.add_patch(hex_patch)
                                logging.info(f"Highlighted next hex {hex_id_to_highlight} for {country_code} (random strategy).")
                            elif geom.geom_type == 'MultiPolygon':
                                for poly in list(geom.geoms):
                                    hex_patch = Polygon(poly.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.8, linewidth=2)
                                    ax.add_patch(hex_patch)
                                logging.info(f"Highlighted next (multi)hex {hex_id_to_highlight} for {country_code} (random strategy).")
                        else:
                            logging.warning(f"Could not find geometry for next hex ID {hex_id_to_highlight} in {country_code}.")
                    else:
                        logging.info(f"All hexes already prayed for in {country_code}, nothing to highlight for queue (random strategy).")
                else:
                    logging.warning(f"Hex map data missing or 'id' column absent for random queue highlighting in {country_code}.")
            else:
                # Specific Mapping Strategy (for other countries)
                if post_label_mapping_df is not None and not post_label_mapping_df.empty and \
                   'post_label' in post_label_mapping_df.columns and 'name' in post_label_mapping_df.columns and \
                   hex_map_gdf is not None and not hex_map_gdf.empty and 'name' in hex_map_gdf.columns:

                    top_queue_post_label = top_queue_item.get('post_label', "")
                    if top_queue_post_label: # Ensure there is a post_label to look up
                        location_code_series_q = post_label_mapping_df.loc[post_label_mapping_df['post_label'] == top_queue_post_label, 'name']
                        if not location_code_series_q.empty:
                            location_code_q = location_code_series_q.iloc[0]
                            location_geom_q = hex_map_gdf[hex_map_gdf['name'] == location_code_q]
                            if not location_geom_q.empty:
                                geom = location_geom_q.geometry.iloc[0]
                                if geom.geom_type == 'Polygon':
                                    hex_patch = Polygon(geom.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.8, linewidth=2)
                                    ax.add_patch(hex_patch)
                                    logging.info(f"Highlighted hex for {top_queue_post_label} in {country_code} (specific strategy).")
                                elif geom.geom_type == 'MultiPolygon':
                                    for poly in list(geom.geoms):
                                        hex_patch = Polygon(poly.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.8, linewidth=2)
                                        ax.add_patch(hex_patch)
                                    logging.info(f"Highlighted (multi)hex for {top_queue_post_label} in {country_code} (specific strategy).")
                            else:
                                logging.warning(f"No geometry for location code {location_code_q} in {country_code} for specific queue highlighting.")
                        else:
                            logging.warning(f"No mapping found for post_label {top_queue_post_label} in {country_code} for specific queue highlighting.")
                    else:
                        logging.info(f"Top queue item for {country_code} has no post_label for specific highlighting.")
                else:
                    logging.warning(f"Data missing for specific queue highlighting in {country_code} (map data or mapping df issues).")
        else:
            logging.debug(f"Top queue item country '{top_queue_item.get('country_code')}' does not match current map country '{country_code}'. No highlight.")
    else:
        logging.debug("Global queue is empty. Nothing to highlight.")

    save_path = os.path.join(APP_ROOT, 'static/hex_map.png')
    plt.savefig(save_path, bbox_inches='tight', pad_inches=0.5, dpi=100)
    plt.close(fig)  # Close the plot to free memory
    # ==== DETAILED LOGGING START ====
    if os.path.exists(save_path):
        logging.info(f"[plot_hex_map_with_hearts] Successfully saved map to {save_path}")
    else:
        logging.error(f"[plot_hex_map_with_hearts] Failed to save map to {save_path}")
    # ==== DETAILED LOGGING END ====
# Ensure logging is imported if not already # This line is now redundant due to import at top

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
