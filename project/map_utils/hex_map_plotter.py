import matplotlib
import logging
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from PIL import Image, ImageFile
import random
import os
import time

# must select backend before importing pyplot
matplotlib.use("Agg")

ImageFile.LOAD_TRUNCATED_IMAGES = True
logger = logging.getLogger(__name__)

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(MODULE_DIR)
PROJECT_ROOT_DIR = os.path.dirname(PROJECT_DIR)

STATIC_FOLDER_PATH = os.path.join(PROJECT_ROOT_DIR, "static")
HEART_ICONS_DIR = os.path.join(STATIC_FOLDER_PATH, "heart_icons")
DEFAULT_MAP_OUTPUT_FILENAME = "hex_map.png"


def load_hex_map_data(hex_map_geojson_path):
    try:
        hex_map = gpd.read_file(hex_map_geojson_path)
        logger.debug(f"Successfully loaded GeoJSON from: {hex_map_geojson_path}")
        return hex_map
    except Exception as e:
        logger.error(
            f"Error reading GeoJSON file at {hex_map_geojson_path}: {e}", exc_info=True
        )
        return None


def load_post_label_mapping_data(post_label_mapping_csv_path):
    try:
        post_label_mapping = pd.read_csv(post_label_mapping_csv_path)
        logger.debug(
            f"Successfully loaded post label mapping CSV from: {post_label_mapping_csv_path}"
        )
        return post_label_mapping
    except Exception as e:
        logger.error(
            f"Error reading post label mapping CSV at {post_label_mapping_csv_path}: {e}",
            exc_info=True,
        )
        return pd.DataFrame()


def _load_random_heart_image(size=(25, 25)):
    if not os.path.isdir(HEART_ICONS_DIR):
        logger.error(f"Heart icons directory not found: {HEART_ICONS_DIR}")
        return None

    heart_pngs = [f for f in os.listdir(HEART_ICONS_DIR) if f.endswith(".png")]
    if not heart_pngs:
        logger.error(f"No PNG images found in heart icons directory: {HEART_ICONS_DIR}")
        return None

    chosen_heart_path = os.path.join(HEART_ICONS_DIR, random.choice(heart_pngs))
    logger.debug(f"Loading random heart image from: {chosen_heart_path}")
    try:
        heart_img = Image.open(chosen_heart_path).convert("RGBA")
        heart_img.thumbnail(size)
        return heart_img
    except FileNotFoundError:
        logger.error(f"Heart image file not found: {chosen_heart_path}")
        return None
    except Exception as e:
        logger.error(f"Error loading heart image {chosen_heart_path}: {e}")
        return None


def plot_hex_map_with_hearts(
    hex_map_gdf,
    post_label_mapping_df,
    prayed_for_items_list,
    queue_items_list,
    country_code,
    output_dir=STATIC_FOLDER_PATH,
    output_filename=DEFAULT_MAP_OUTPUT_FILENAME,
):
    output_path = os.path.join(output_dir, output_filename)
    logger.debug(
        f"Plotting hex map for country {country_code}. "
        f"Prayed: {len(prayed_for_items_list)}, Queue: {len(queue_items_list)}. "
        f"Output: {output_path}"
    )

    if hex_map_gdf is None or hex_map_gdf.empty:
        logger.error(
            f"Cannot plot map for {country_code}: hex_map_gdf is None or empty."
        )
        fig_err_placeholder, ax_err_placeholder = plt.subplots(
            1, 1, figsize=(10, 10)
        )  # Renamed variables
        ax_err_placeholder.text(
            0.5,
            0.5,
            f"Map data unavailable\nfor {country_code}",
            ha="center",
            va="center",
            fontsize=16,
            color="red",
        )
        ax_err_placeholder.set_axis_off()
        try:
            plt.savefig(output_path, bbox_inches="tight", pad_inches=0.5, dpi=100)
            logger.info(
                f"Saved placeholder map to {output_path} due to missing map data for {country_code}."
            )
        except Exception as e_save_placeholder:
            logger.error(
                f"Failed to save placeholder map for {country_code}: {e_save_placeholder}"
            )
        finally:
            plt.close(fig_err_placeholder)
        return

    is_random_allocation_country = country_code in ["israel", "iran"]

    if is_random_allocation_country and "id" not in hex_map_gdf.columns:
        logger.error(
            f"'id' column missing in hex_map_gdf for random allocation country {country_code}. Saving base map."
        )
        fig_base_map = None  # Renamed variable
        try:
            fig_base_map, ax_base_map = plt.subplots(
                1, 1, figsize=(10, 10)
            )  # Renamed variables
            fig_base_map.patch.set_facecolor("white")
            ax_base_map.set_facecolor("white")
            hex_map_gdf.plot(ax=ax_base_map, color="white", edgecolor="lightgrey")
            ax_base_map.set_axis_off()
            bounds_base = hex_map_gdf.geometry.total_bounds
            ax_base_map.set_xlim(bounds_base[0], bounds_base[2])
            ax_base_map.set_ylim(bounds_base[1], bounds_base[3])
            ax_base_map.set_aspect("equal")
            plt.savefig(output_path, bbox_inches="tight", pad_inches=0.5, dpi=100)
        except Exception as e_save_no_id:
            logger.error(
                f"Failed to save base map for {country_code} (no 'id' column): {e_save_no_id}"
            )
        finally:
            if fig_base_map is not None:
                plt.close(fig_base_map)
        return

    fig_main_plot = None  # Renamed variable
    try:
        fig_main_plot, ax_main_plot = plt.subplots(
            1, 1, figsize=(10, 10)
        )  # Renamed variables
        fig_main_plot.patch.set_facecolor("white")
        ax_main_plot.set_facecolor("white")
        hex_map_gdf.plot(ax=ax_main_plot, color="white", edgecolor="lightgrey")
        ax_main_plot.set_axis_off()

        bounds = hex_map_gdf.geometry.total_bounds
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]

        # Define a padding factor to adjust perceived size.
        # Larger padding makes the content appear smaller within the frame.
        padding_factor_x = 0.1  # Default 10% horizontal padding
        padding_factor_y = 0.1  # Default 10% vertical padding

        if country_code == "israel":
            logger.debug(f"Applying increased padding for Israel map to reduce its relative size.")
            padding_factor_x = 0.25  # Increase horizontal padding for Israel
            padding_factor_y = 0.25  # Increase vertical padding for Israel
        elif country_code == "iran":
            # Optionally, slightly reduce padding for Iran if it needs to appear larger
            # For now, keep it at the default or slightly less if Israel is the main concern
            padding_factor_x = 0.05
            padding_factor_y = 0.05
            logger.debug(f"Applying standard/reduced padding for Iran map.")

        ax_main_plot.set_xlim(bounds[0] - width * padding_factor_x, bounds[2] + width * padding_factor_x)
        ax_main_plot.set_ylim(bounds[1] - height * padding_factor_y, bounds[3] + height * padding_factor_y)
        ax_main_plot.set_aspect("equal")

        placed_heart_count = 0
        for prayed_item_iter in prayed_for_items_list:  # Renamed loop variable
            if prayed_item_iter.get("country_code") != country_code:
                continue
            location_geom = None
            item_identifier_for_log = prayed_item_iter.get(
                "person_name", "Unknown Person"
            )

            if is_random_allocation_country:
                assigned_hex_id = prayed_item_iter.get("hex_id")
                if assigned_hex_id and "id" in hex_map_gdf.columns:
                    geom_series = hex_map_gdf[hex_map_gdf["id"] == assigned_hex_id]
                    if not geom_series.empty:
                        location_geom = geom_series.geometry.iloc[0]
                    else:
                        logger.warning(
                            f"Geometry not found for assigned hex ID {assigned_hex_id} "
                            f"for {item_identifier_for_log} in {country_code}."
                        )
                else:
                    logger.warning(
                        f"Prayed item {item_identifier_for_log} for {country_code} "
                        f"(random alloc) has no/invalid assigned hex_id."
                    )
            else:
                if post_label_mapping_df is None or post_label_mapping_df.empty:
                    logger.error(
                        f"Post label mapping is missing/empty for {country_code} "
                        f"(specific mapping). Cannot place heart for {item_identifier_for_log}."
                    )
                    continue
                if not all(
                    col in post_label_mapping_df.columns
                    for col in ["post_label", "name"]
                ):
                    logger.error(
                        f"Required columns ('post_label', 'name') not in post_label_mapping_df for {country_code}."
                    )
                    continue
                if "name" not in hex_map_gdf.columns:
                    logger.error(
                        f"'name' column (for hex region ID) missing in hex_map_gdf "
                        f"for {country_code} (specific mapping)."
                    )
                    continue
                item_post_label = prayed_item_iter.get("post_label")
                if item_post_label:
                    code_series = post_label_mapping_df.loc[
                        post_label_mapping_df["post_label"] == item_post_label, "name"
                    ]
                    if not code_series.empty:
                        hex_region_name = code_series.iloc[0]
                        geom_series = hex_map_gdf[
                            hex_map_gdf["name"] == hex_region_name
                        ]
                        if not geom_series.empty:
                            location_geom = geom_series.geometry.iloc[0]
                        else:
                            logger.debug(
                                f"No geometry for hex region name {hex_region_name} "
                                f"(from label {item_post_label}) in {country_code}."
                            )
                    else:
                        logger.debug(
                            f"No mapping found for post_label {item_post_label} in {country_code}."
                        )
                else:
                    logger.debug(
                        f"Prayed item {item_identifier_for_log} has no post_label "
                        f"for specific mapping in {country_code}."
                    )

            if location_geom:
                centroid = location_geom.centroid
                heart_img = _load_random_heart_image(size=(25, 25))
                if heart_img:
                    imagebox = OffsetImage(heart_img, zoom=0.6)
                    ab = AnnotationBbox(
                        imagebox, (centroid.x, centroid.y), frameon=False
                    )
                    ax_main_plot.add_artist(ab)  # Use ax_main_plot
                    placed_heart_count += 1
                else:
                    logger.warning(
                        f"Skipping heart for {item_identifier_for_log} in {country_code} "
                        f"(heart image load failed)."
                    )
        logger.debug(f"Placed {placed_heart_count} hearts for {country_code}.")

        if queue_items_list:
            top_queue_item = queue_items_list[0]
            if top_queue_item.get("country_code") == country_code:
                logger.info(
                    f"Attempting to highlight top queue item for {country_code}: {top_queue_item.get('person_name')}"
                )
                highlight_geom = None
                item_identifier_for_log_q = top_queue_item.get(
                    "person_name", "Unknown Queued Person"
                )

                if is_random_allocation_country:
                    assigned_hex_id_q = top_queue_item.get("hex_id")
                    if assigned_hex_id_q and "id" in hex_map_gdf.columns:
                        geom_series_q = hex_map_gdf[
                            hex_map_gdf["id"] == assigned_hex_id_q
                        ]
                        if not geom_series_q.empty:
                            highlight_geom = geom_series_q.geometry.iloc[0]
                        else:
                            logger.warning(
                                f"Highlight failed for {country_code}: Assigned hex ID "
                                f"{assigned_hex_id_q} for {item_identifier_for_log_q} "
                                f"found NO GEOMETRY."
                            )
                    else:
                        logger.warning(
                            f"Top queue item {item_identifier_for_log_q} for {country_code} "
                            f"(random alloc) has no/invalid assigned hex_id for highlighting."
                        )
                else:
                    if (
                        post_label_mapping_df is not None
                        and not post_label_mapping_df.empty
                        and all(
                            col in post_label_mapping_df.columns
                            for col in ["post_label", "name"]
                        )
                        and "name" in hex_map_gdf.columns
                    ):
                        top_queue_post_label = top_queue_item.get("post_label")
                        if top_queue_post_label:
                            code_series_q = post_label_mapping_df.loc[
                                post_label_mapping_df["post_label"]
                                == top_queue_post_label,
                                "name",
                            ]
                            if not code_series_q.empty:
                                hex_region_name_q = code_series_q.iloc[0]
                                geom_series_q = hex_map_gdf[
                                    hex_map_gdf["name"] == hex_region_name_q
                                ]
                                if not geom_series_q.empty:
                                    highlight_geom = geom_series_q.geometry.iloc[0]
                                else:
                                    logger.warning(
                                        f"No geometry for hex region name {hex_region_name_q} "
                                        f"for specific queue highlighting in {country_code}."
                                    )
                            else:
                                logger.warning(
                                    f"No mapping for post_label {top_queue_post_label} "
                                    f"for specific queue highlighting in {country_code}."
                                )
                        else:
                            logger.info(
                                f"Top queue item {item_identifier_for_log_q} for {country_code} "
                                f"has no post_label for specific highlighting."
                            )
                    else:
                        logger.warning(
                            f"Data missing for specific queue highlighting in {country_code} "
                            f"(map data or mapping df issues)."
                        )

                if highlight_geom:

                    def add_geometry_patches(
                        ax_to_plot_on, geometry, **kwargs
                    ):  # Renamed ax argument
                        if geometry.geom_type == "Polygon":
                            ax_to_plot_on.add_patch(
                                Polygon(geometry.exterior.coords, closed=True, **kwargs)
                            )
                        elif geometry.geom_type == "MultiPolygon":
                            for poly_geom_iter in list(
                                geometry.geoms
                            ):  # Renamed loop variable
                                ax_to_plot_on.add_patch(
                                    Polygon(
                                        poly_geom_iter.exterior.coords,
                                        closed=True,
                                        **kwargs,
                                    )
                                )

                    add_geometry_patches(
                        ax_main_plot,
                        highlight_geom,
                        edgecolor="black",
                        facecolor="yellow",
                        alpha=0.7,
                        linewidth=2.5,
                    )  # Use ax_main_plot
                    logger.info(
                        f"Successfully highlighted hex for {item_identifier_for_log_q} in {country_code}."
                    )
            else:
                logger.debug(
                    f"Top queue item country '{top_queue_item.get('country_code')}' "
                    f"does not match current map country '{country_code}'. No highlight."
                )
        else:
            logger.debug("Queue is empty. Nothing to highlight.")

        plt.savefig(output_path, bbox_inches="tight", pad_inches=0.5, dpi=100)
        logger.info(f"Successfully saved map to {output_path}")

    except Exception as e_plot:
        logger.error(
            f"An unexpected error occurred during map plotting for {country_code}: {e_plot}",
            exc_info=True,
        )
        if fig_main_plot is not None:
            plt.close(fig_main_plot)
        fig_err_handling = None  # Renamed variable
        try:
            fig_err_handling, ax_err_handling = plt.subplots(
                1, 1, figsize=(10, 10)
            )  # Renamed variables
            ax_err_handling.text(
                0.5,
                0.5,
                f"Error generating map\nfor {country_code}.\nPlease check logs.",
                ha="center",
                va="center",
                fontsize=16,
                color="red",
            )
            ax_err_handling.set_axis_off()
            plt.savefig(output_path, bbox_inches="tight", pad_inches=0.5, dpi=100)
            logger.info(
                f"Saved error placeholder map for {country_code} to {output_path} due to plotting exception."
            )
        except Exception as e_save_generic_error:
            logger.error(
                f"Failed to save generic error placeholder map for {country_code}: {e_save_generic_error}"
            )
        finally:
            if fig_err_handling is not None:
                plt.close(fig_err_handling)
    finally:
        if fig_main_plot is not None:
            plt.close(fig_main_plot)

    if os.path.exists(output_path):
        try:
            mod_time_after = os.path.getmtime(output_path)
            logger.debug(
                f"File {output_path} exists after save attempt. "
                f"Last modified: {time.ctime(mod_time_after)} (Timestamp: {mod_time_after})"
            )
        except Exception as e_stat_after:  # Renamed variable
            logger.error(
                f"Error getting stat for {output_path} after save: {e_stat_after}"
            )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Running hex_map_plotter.py standalone example...")
    # Standalone test code as before, ensuring paths are correct if run directly.
    logger.info(
        "Standalone example finished. "
        "Full plotting requires valid data paths and GeoPandas setup."
    )
