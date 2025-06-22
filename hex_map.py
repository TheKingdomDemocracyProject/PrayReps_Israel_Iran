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
import time # Import time module

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
    # output_filename = "hex_map.png" # This can be defined later or stay if needed for path logging
    # output_path = os.path.join(APP_ROOT, 'static', output_filename) # Same as above

    logging.debug(f"Plotting hex map for country {country_code}. Prayed: {len(prayed_for_items_list)}, Queue: {len(queue_items_list)}") # Moved initial log up

    if hex_map_gdf is None or hex_map_gdf.empty:
        logging.error(f"Cannot plot map for {country_code}: hex_map_gdf is None or empty.")
        # Attempt to save a blank or placeholder image to avoid broken image links,
        # or ensure calling functions handle this. For now, just return.
        # To create a placeholder image:
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))
        ax.text(0.5, 0.5, f"Map data unavailable\nfor {country_code}", ha='center', va='center', fontsize=20, color='red')
        ax.set_axis_off()
        output_path_for_error = os.path.join(APP_ROOT, 'static', "hex_map.png") # Define here for error case
        try:
            plt.savefig(output_path_for_error, bbox_inches='tight', pad_inches=0.5, dpi=100)
            logging.info(f"Saved placeholder map to {output_path_for_error} due to missing map data for {country_code}.")
        except Exception as e_save_placeholder:
            logging.error(f"Failed to save placeholder map for {country_code}: {e_save_placeholder}")
        finally:
            plt.close(fig) # Ensure figure is closed
        return

    # Define output_filename and output_path earlier
    output_filename = "hex_map.png"
    output_path = os.path.join(APP_ROOT, 'static', output_filename)

    if os.path.exists(output_path):
        try:
            mod_time = os.path.getmtime(output_path)
            logging.debug(f"File {output_path} exists. Last modified: {time.ctime(mod_time)} (Timestamp: {mod_time})")
        except Exception as e_stat:
            logging.error(f"Error getting stat for {output_path}: {e_stat}")
    else:
        logging.debug(f"File {output_path} does not exist yet.")

    # Check for 'id' column if country is Israel or Iran (already implemented from previous step)
    # This check needs to happen before the main try block if it's going to save a base map and return.
    if country_code in ['israel', 'iran'] and (hex_map_gdf is None or 'id' not in hex_map_gdf.columns):
        # Note: The hex_map_gdf None check is already at the very top.
        # This specific check is if GDF exists BUT 'id' column is missing for these countries.
        if 'id' not in hex_map_gdf.columns:
            logging.error(f"'id' column missing in hex_map_gdf for {country_code}. Cannot apply random allocation. Saving base map.")
            fig_base = None
            try:
                fig_base, ax_base = plt.subplots(1, 1, figsize=(10, 10))
                fig_base.patch.set_facecolor('white')
                ax_base.set_facecolor('white')
                hex_map_gdf.plot(ax=ax_base, color='white', edgecolor='lightgrey')
                ax_base.set_axis_off()
                bounds_base = hex_map_gdf.geometry.total_bounds
                ax_base.set_xlim(bounds_base[0], bounds_base[2])
                ax_base.set_ylim(bounds_base[1], bounds_base[3])
                ax_base.set_aspect('equal')
                plt.savefig(output_path, bbox_inches='tight', pad_inches=0.5, dpi=100)
                logging.info(f"Saved base map for {country_code} without hearts/highlights due to missing 'id' column.")
            except Exception as e_save_no_id:
                logging.error(f"Failed to save base map for {country_code} (no 'id' column): {e_save_no_id}")
            finally:
                if fig_base is not None:
                    plt.close(fig_base)
            return

    fig = None # Initialize fig for the main plotting block
    try:
        fig, ax = plt.subplots(1, 1, figsize=(10, 10))
        fig_bg_color = 'white'
        hex_plot_color = 'white'
        fig.patch.set_facecolor(fig_bg_color)
        ax.set_facecolor(fig_bg_color)
        hex_map_gdf.plot(ax=ax, color=hex_plot_color, edgecolor='lightgrey')
        ax.set_axis_off()
        bounds = hex_map_gdf.geometry.total_bounds
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])
        ax.set_aspect('equal')

        logging.info(f"Plotting map for country: {country_code}. Prayed items: {len(prayed_for_items_list)}, Queue items: {len(queue_items_list)}")

        # Heart placement and queue highlighting logic (existing code)
        if country_code in ['israel', 'iran']:
            # Random Allocation Strategy
            # 'id' column existence is already checked and handled for these countries before this try block.
            num_hearts = len(prayed_for_items_list)
            all_hex_ids = list(hex_map_gdf['id'].unique())
            if not all_hex_ids:
                logging.warning(f"No hex IDs found in map data for {country_code}. Cannot place hearts.")
            else:
                sorted_hex_ids = sorted(all_hex_ids)
                hex_ids_to_color = sorted_hex_ids[:num_hearts]
                logging.debug(f"IR/ISR: Plotting {num_hearts} hearts on hex_ids: {hex_ids_to_color[:5]}...")
                for hex_id_to_color in hex_ids_to_color:
                    location_geom = hex_map_gdf[hex_map_gdf['id'] == hex_id_to_color]
                    if not location_geom.empty:
                        centroid = location_geom.geometry.centroid.iloc[0]
                        heart_img = load_random_heart_image()
                        if heart_img:
                            imagebox = OffsetImage(heart_img, zoom=0.6)
                            ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                            ax.add_artist(ab)
                        else:
                            logging.warning(f"Skipping heart placement for a hex in {country_code} due to missing heart image.")
                    else:
                        logging.warning(f"Geometry not found for hex ID {hex_id_to_color} in {country_code}.")
        else:
            # Specific Mapping Strategy
            if post_label_mapping_df is None or post_label_mapping_df.empty:
                logging.error(f"Post label mapping is missing or empty for {country_code}. Cannot map items to hexes.")
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
                            continue
                        location_geom = hex_map_gdf[hex_map_gdf['name'] == location_code]
                        if not location_geom.empty:
                            centroid = location_geom.geometry.centroid.iloc[0]
                            heart_img = load_random_heart_image()
                            if heart_img:
                                imagebox = OffsetImage(heart_img, zoom=0.6)
                                ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                                ax.add_artist(ab)
                            else:
                                logging.warning(f"Skipping heart placement for a hex in {country_code} due to missing heart image.")
                        else:
                            logging.debug(f"No geometry found for location code {location_code} (from label {location_label}) in {country_code}.")
                    else:
                        logging.debug(f"No mapping found for post_label {location_label} in {country_code}.")

        # Conditional Highlighting for Top Queue Item (common logic, adapted)
        if queue_items_list:
            top_queue_item = queue_items_list[0]
            if top_queue_item.get('country_code') == country_code:
                logging.info(f"Attempting to highlight top queue item for {country_code}: {top_queue_item.get('person_name')}")
                if country_code in ['israel', 'iran']:
                    # Random Allocation Highlighting
                    if 'id' in hex_map_gdf.columns: # Should be true due to earlier check
                        num_hearts_already_plotted = len(prayed_for_items_list)
                        all_hex_ids_list = list(hex_map_gdf['id'].unique()) # All unique IDs from the map

                        # Determine hexes that already have hearts
                        # Assuming heart placement logic uses sorted IDs:
                        sorted_all_hex_ids = sorted(all_hex_ids_list)
                        prayed_hex_ids_set = set(sorted_all_hex_ids[:num_hearts_already_plotted])

                        all_hex_ids_set = set(all_hex_ids_list)
                        available_ids_for_highlight = list(all_hex_ids_set - prayed_hex_ids_set)

                        logging.debug(f"For {country_code} highlight: All map IDs: {len(all_hex_ids_set)}, Prayed (heart) IDs: {len(prayed_hex_ids_set)}, Available for highlight: {len(available_ids_for_highlight)}")

                        if available_ids_for_highlight:
                            hex_id_to_highlight = random.choice(available_ids_for_highlight)
                            logging.info(f"Randomly selected hex ID {hex_id_to_highlight} for queue highlight in {country_code} from {len(available_ids_for_highlight)} available hexes.")

                            location_geom_q = hex_map_gdf[hex_map_gdf['id'] == hex_id_to_highlight]
                            if not location_geom_q.empty:
                                geom = location_geom_q.geometry.iloc[0]
                                if geom.geom_type == 'Polygon':
                                    hex_patch = Polygon(geom.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.8, linewidth=2)
                                    ax.add_patch(hex_patch)
                                elif geom.geom_type == 'MultiPolygon':
                                    for poly in list(geom.geoms): # Ensure iteration
                                        hex_patch = Polygon(poly.exterior.coords, closed=True, edgecolor='black', facecolor='yellow', alpha=0.8, linewidth=2)
                                        ax.add_patch(hex_patch)
                                logging.info(f"Highlighted hex {hex_id_to_highlight} for {country_code} (random strategy).")
                            else:
                                logging.warning(f"Highlight failed for {country_code}: Randomly selected hex ID {hex_id_to_highlight} found NO GEOMETRY in map data.")
                        else:
                            logging.info(f"All hexes already prayed for in {country_code}, nothing to highlight for queue (random strategy).")
                else:
                    # Specific Mapping Highlighting
                    if post_label_mapping_df is not None and not post_label_mapping_df.empty and \
                       all(col in post_label_mapping_df.columns for col in ['post_label', 'name']) and \
                       'name' in hex_map_gdf.columns:
                        top_queue_post_label = top_queue_item.get('post_label', "")
                        if top_queue_post_label:
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
                                        for poly in list(geom.geoms): # Ensure iteration
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

        plt.savefig(output_path, bbox_inches='tight', pad_inches=0.5, dpi=100)
        logging.info(f"Successfully saved map to {output_path}")

    except Exception as e_plot:
        logging.error(f"An unexpected error occurred during map plotting for {country_code}: {e_plot}", exc_info=True)
        if fig is not None: # If main fig exists, try to close it
            plt.close(fig)
            fig = None # Reset fig

        fig_err = None # Initialize fig_err
        try:
            fig_err, ax_err = plt.subplots(1, 1, figsize=(10, 10))
            ax_err.text(0.5, 0.5, f"Error generating map\nfor {country_code}.\nPlease check logs.", ha='center', va='center', fontsize=20, color='red')
            ax_err.set_axis_off()
            plt.savefig(output_path, bbox_inches='tight', pad_inches=0.5, dpi=100) # Save to the same output_path
            logging.info(f"Saved error placeholder map for {country_code} due to plotting exception.")
        except Exception as e_save_generic_error:
            logging.error(f"Failed to save generic error placeholder map for {country_code}: {e_save_generic_error}")
        finally:
            if fig_err is not None:
                plt.close(fig_err)
    finally:
        if fig is not None: # If main fig was successfully created and not closed by an error path
            plt.close(fig)


    # Log file details AFTER saving
    if os.path.exists(output_path):
        try:
            mod_time_after = os.path.getmtime(output_path)
            logging.debug(f"File {output_path} exists after save. Last modified: {time.ctime(mod_time_after)} (Timestamp: {mod_time_after})")
        except Exception as e_stat_after:
            logging.error(f"Error getting stat for {output_path} after save: {e_stat_after}")
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
