from flask import current_app
import os
import logging  # Using current_app.logger
import pandas as pd

# Assuming hex_map.py is moved into the project structure or its functions are accessible
# For now, let's assume it's in the project root, and we might need to adjust paths or import strategy.
# If hex_map.py is also moved to project/hex_map_utils.py for example:
# from ..hex_map_utils import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
# For now, relative import from project root:
# import sys
# Add project root to sys.path to allow importing hex_map
# This is a common pattern when scripts in subdirectories need to access modules in the parent.
# PROJECT_ROOT_FOR_HEX_MAP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if PROJECT_ROOT_FOR_HEX_MAP not in sys.path:
#     sys.path.append(PROJECT_ROOT_FOR_HEX_MAP)

try:
    # import hex_map as hex_map_plotter # hex_map.py from the root
    from ..map_utils import hex_map_plotter  # Corrected import
except ImportError as e:
    # current_app.logger.error(f"Could not import hex_map_plotter from map_utils: {e}. Ensure it's accessible.")
    # Define dummy functions or raise an error to indicate critical failure
    # This logging might fail if current_app is not available at import time.
    # It's better to log this failure where current_app is guaranteed.
    logging.getLogger(__name__).error(
        f"Could not import hex_map_plotter from map_utils: {e}. Ensure it's accessible."
    )

    class DummyHexMapPlotter:
        def load_hex_map_data(self, path):
            return None  # Updated method name

        def load_post_label_mapping_data(self, path):
            return None  # Updated method name

        def plot_hex_map_with_hearts(self, *args, **kwargs):
            pass

    hex_map_plotter = DummyHexMapPlotter()


# --- Map Data Loading (called during app initialization) ---


def load_all_map_data(app_context):
    """
    Loads all necessary map data (GeoJSON, post label mappings) into app context stores.
    This replaces the global loading in the original app.py.
    """
    with app_context:  # Ensures current_app is available
        current_app.logger.info("Loading all map data...")
        countries_config = current_app.config["COUNTRIES_CONFIG"]

        for country_code, config in countries_config.items():
            # Load map shape data (GeoJSON)
            map_path = config["map_shape_path"]
            if os.path.exists(map_path):
                current_app.hex_map_data_store[country_code] = (
                    hex_map_plotter.load_hex_map_data(map_path)
                )  # Updated function call
                if (
                    current_app.hex_map_data_store[country_code] is not None
                    and not current_app.hex_map_data_store[country_code].empty
                ):  # Added empty check
                    current_app.logger.info(
                        f"Successfully loaded hex map for {country_code} with "
                        f"{len(current_app.hex_map_data_store[country_code])} features."
                    )
                elif (
                    current_app.hex_map_data_store[country_code] is not None
                    and current_app.hex_map_data_store[country_code].empty
                ):
                    current_app.logger.warning(
                        f"Loaded hex map for {country_code} from {map_path} is an empty GeoDataFrame."
                    )
                else:  # is None
                    current_app.logger.error(
                        f"Failed to load hex map for {country_code} from {map_path} (returned None)."
                    )
            else:
                current_app.logger.error(
                    f"Map file not found: {map_path} for country {country_code}"
                )
                current_app.hex_map_data_store[country_code] = (
                    None  # Ensure it's None if file not found
                )

            # Load post label mapping data (CSV for non-random countries)
            post_label_path = config.get("post_label_mapping_path")
            if post_label_path and os.path.exists(post_label_path):
                current_app.post_label_mappings_store[country_code] = (
                    hex_map_plotter.load_post_label_mapping_data(post_label_path)
                )  # Updated function call
                if not current_app.post_label_mappings_store[country_code].empty:
                    current_app.logger.info(
                        f"Successfully loaded post label mapping for {country_code} with "
                        f"{len(current_app.post_label_mappings_store[country_code])} entries."
                    )
                else:  # Loaded but empty
                    current_app.logger.warning(
                        f"Post label mapping for {country_code} from {post_label_path} is empty."
                    )
            elif post_label_path:  # Path specified but not found
                current_app.logger.error(
                    f"Post label mapping file not found: {post_label_path} for country {country_code}"
                )
                current_app.post_label_mappings_store[country_code] = (
                    pd.DataFrame()
                )  # Assign empty DataFrame
            else:  # No path specified (e.g., for Israel, Iran using random hex allocation)
                current_app.logger.debug(
                    f"No post label mapping file specified for {country_code}. Using empty DataFrame."
                )
                current_app.post_label_mappings_store[country_code] = (
                    pd.DataFrame()
                )  # Assign empty DataFrame
        current_app.logger.info("Finished loading all map data.")


# --- Map Plotting ---


def generate_country_map_image(country_code, prayed_for_items_list, queue_items_list):
    """
    Generates and saves the hex map image for a given country.
    Uses data from app context stores (hex_map_data_store, etc.).
    The output path is fixed for now to 'static/hex_map.png'.
    Could be made country-specific e.g., 'static/hex_map_<country_code>.png'.
    """
    current_app.logger.info(f"Generating map image for country: {country_code}")

    hex_map_gdf = current_app.hex_map_data_store.get(country_code)
    post_label_df = current_app.post_label_mappings_store.get(country_code)

    # Define output path - this is where plot_hex_map_with_hearts will save the image.
    # hex_map.py saves to os.path.join(APP_ROOT, 'static', "hex_map.png")
    # Ensure hex_map.py's APP_ROOT is correctly pointing to the project's root where static/ is.
    # For now, assume hex_map.py handles its own pathing correctly to 'static/hex_map.png'.
    # The output_path here is more for reference or if we want to override.
    # map_image_filename = "hex_map.png" # Could be f"hex_map_{country_code}.png"
    # output_image_path = os.path.join(current_app.config['STATIC_FOLDER'], map_image_filename)

    if hex_map_gdf is None or hex_map_gdf.empty:
        current_app.logger.error(
            f"Cannot plot map for {country_code}: GeoDataFrame is missing or empty."
        )
        # plot_hex_map_with_hearts in hex_map.py already handles saving a placeholder if GDF is empty.
        # We just need to call it.
        hex_map_plotter.plot_hex_map_with_hearts(
            hex_map_gdf,  # Will be None or empty
            post_label_df,  # Could be None or empty
            prayed_for_items_list,
            queue_items_list,
            country_code,
            # heart_img_path is handled by hex_map.py's load_random_heart_image
        )
        return False  # Indicate failure or that a placeholder was made

    # For countries like Israel/Iran, post_label_df might be empty, which is fine.
    # hex_map_plotter.plot_hex_map_with_hearts should handle this.

    try:
        hex_map_plotter.plot_hex_map_with_hearts(
            hex_map_gdf,
            post_label_df,
            prayed_for_items_list,
            queue_items_list,
            country_code,
            # heart_img_path is handled by hex_map.py's load_random_heart_image
        )
        current_app.logger.info(
            f"Successfully generated and saved map image for {country_code}."
        )
        return True  # Indicate success
    except Exception as e:
        current_app.logger.error(
            f"Error during map plotting for {country_code}: {e}", exc_info=True
        )
        # hex_map.py's plot_hex_map_with_hearts has its own try-except to save an error placeholder.
        return False


# Note: The original app.py directly modified global variables like HEX_MAP_DATA_STORE.
# In this refactored version, these are attributes of `current_app` (e.g., `current_app.hex_map_data_store`),
# initialized in `create_app` and populated by `load_all_map_data`.
# The `hex_map.py` script itself, if it uses global variables for paths like APP_ROOT,
# needs to be aware of its execution context when called from this service.
# The sys.path manipulation above is a common way to handle this for scripts not in packages.
# A cleaner way would be to make hex_map.py's functions accept all necessary paths as arguments
# or make hex_map.py a proper part of the 'project' package.
# For now, the sys.path append is a pragmatic first step.

# We also need to ensure that hex_map.py's internal APP_ROOT is correctly set.
# Original hex_map.py: APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# If hex_map.py is in the project root, this APP_ROOT is correct for finding 'static/heart_icons'.
# If hex_map.py were moved into 'project/utils/', its APP_ROOT would point to 'project/utils/',
# and it would fail to find 'static/heart_icons' unless paths were adjusted.
# The current structure (hex_map.py in root) with sys.path append for the service to find it is workable.
