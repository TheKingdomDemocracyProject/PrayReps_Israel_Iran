# PrayReps_Israel_Iran

A tool to pray for those representatives serving the countries of Israel and Iran.

## Overview
PrayReps is a tool that will eventually help Christians to pray for any elected representative, anywhere in the world. This Python app is an MVP that has already been used to pray for newly elected governments in the United Kingdom, France and the USA. 

The app enqueues the details of elected representatives and displays the location they serve on a map. When you have prayed for them that location is marked with a heart. The app contains rudimentary logging functionality to provide statistics as well as the ability to return individuals to the queue to pray for them again.

This implementation retrieves data from a CSV and uses JSON logging to manage the different records.

If you want to purge the queue and start again use the route /purge and then /refresh.

## Software Overview and Functionality

### Purpose
"PrayReps_Israel_Iran" is a Flask web application designed to help users systematically pray for elected representatives in Israel and Iran. It aims to provide a focused tool for individuals or groups wanting to engage in prayer for political leaders. The application manages a list of representatives, tracks who has been prayed for, and visualizes this information on interactive hexagonal maps.

### Core Components
The application is structured around several key Python files and directories:

*   **`run.py`**: The entry point for running the Flask application (e.g., via Gunicorn). It imports and runs the app created by the application factory.
*   **`project/` directory**: Contains the core application package.
    *   **`project/__init__.py`**: Implements the application factory pattern (`create_app`). It initializes the Flask app, loads configuration, sets up logging, initializes database connections, registers blueprints, and loads initial data.
    *   **`project/config.py`**: Defines configuration classes for different environments (e.g., Development, Production), holding settings like database paths, static folder locations, and application-specific data like country configurations and party information.
    *   **`project/database.py`**: Manages SQLite database connections (`get_db`, `close_db`) and schema initialization (`init_db_schema`, `init_db_command`). It might also contain basic data access helper functions.
    *   **`project/data_initializer.py`**: Handles the sequence of setting up application data on startup, including database schema creation, data migrations (from old formats if necessary), loading static data like GeoJSON maps and CSVs into memory, and seeding the initial prayer queue.
    *   **`project/services/` directory**: Contains modules that encapsulate the application's business logic.
        *   `prayer_service.py`: Handles logic related to fetching representative data, managing the prayer queue (getting next items, marking as prayed, putting items back), calculating statistics, and purging data.
        *   `map_service.py`: Coordinates the loading of map data (GeoJSONs, mappings) and calls the plotting functions to generate map images.
    *   **`project/blueprints/` directory**: Organizes the application into modular components using Flask Blueprints. Each blueprint handles routes for a specific feature set.
        *   `main.py`: Routes for general pages like home (`/`), about (`/about`), purge (`/purge`), and map image generation for JSON responses.
        *   `prayer.py`: Routes related to prayer actions, including HTMX endpoints for processing prayers (`/process_item_htmx`) and putting items back in the queue (`/put_back_htmx`), as well as pages for viewing the queue (`/queue_page`) and prayed lists (`/prayed_list_page`).
        *   `stats.py`: Routes for displaying statistics pages (`/statistics_page`) and providing data via JSON endpoints for charts (`/data/...`, `/timedata/...`).
    *   **`project/map_utils/hex_map_plotter.py`** (formerly `hex_map.py`): This module is responsible for all aspects of hex map generation:
        *   Loading geographical data for maps from GeoJSON files.
        *   Loading CSV files that map administrative posts to specific hex regions (for countries not using random hex allocation).
        *   Loading heart icon images.
        *   Drawing the hex maps, plotting heart icons on hexes corresponding to prayed-for representatives, and highlighting the hex for the current representative in the queue. It supports two main strategies:
            *   *Random Allocation (Israel, Iran):* Representatives are assigned a `hex_id` which determines their location on the map.
            *   *Specific Mapping:* Representatives are mapped to map regions via their `post_label` (used if other countries were configured with this system).
    *   **`project/utils.py`**: Contains utility functions, such as `format_pretty_timestamp` for displaying date-time information in a user-friendly format.

*   **`generate_multicoloured_a0_map.py`**: A standalone utility script (outside the `project` package) for generating large, high-resolution A0-sized prayer maps, likely for printing.

*   **`data/` directory**:
    *   Contains CSV files (e.g., `20221101_israel.csv`, `20240510_iran.csv`) which store the lists of representatives and their details.
    *   Stores GeoJSON files (e.g., `ISR_Parliament_120.geojson`) that define the shapes and layout of the hexagonal maps.
    *   Houses the SQLite database file (`queue.db`) where all persistent application state (queue, prayed-for status) is stored.

*   **`static/` directory**:
    *   Stores static web assets such as CSS stylesheets (`style.css`).
    *   Contains image files, including various heart icons (`static/heart_icons/`) used on the maps, and the dynamically generated hex map (`hex_map.png`).

*   **`templates/` directory**:
    *   Contains Jinja2 HTML templates used to render the web pages presented to the user (e.g., `index.html`, `queue.html`, `prayed.html`, `statistics.html`).

### User Journeys
The application supports several key user interactions:

1.  **Primary Journey: Praying for Representatives**
    *   The user visits the home page (`/`).
    *   The system displays a representative from the prayer queue, showing their name, photo (if available), party, and the country/location they serve.
    *   A hex map of the representative's country is displayed. The specific hex corresponding to the current representative is highlighted (e.g., in yellow). Hexes for previously prayed-for representatives are marked with heart icons.
    *   After praying, the user clicks a "Prayed" button (or equivalent action), which triggers the `/process_item` endpoint.
    *   The application updates its database, marking the representative as 'prayed'.
    *   The hex map is refreshed: the previously highlighted hex now receives a heart icon.
    *   The home page updates to show the next representative from the queue, along with their relevant map.

2.  **Viewing the Prayer Queue**
    *   The user navigates to the Queue page (e.g., via a link, accessing `/queue`).
    *   The page lists all representatives currently in the 'queued' state, waiting to be prayed for, along with their details.

3.  **Viewing Prayed-For Representatives**
    *   The user navigates to the Prayed List page (e.g., `/prayed/<country_code>` for a specific country, or `/prayed/overall` for all).
    *   This page displays a list of all representatives who have already been prayed for, including the timestamp of when they were prayed for.
    *   From this list, the user has an option to "put back" a representative into the prayer queue. This action (via `/put_back`) changes their status from 'prayed' back to 'queued' and updates the map accordingly.

4.  **Viewing Statistics**
    *   The user accesses the Statistics page (e.g., `/statistics/<country_code>` or `/statistics/overall`).
    *   This section provides visualizations and data related to prayer activity:
        *   For a specific country: A breakdown of prayed-for representatives by political party and a timeline of prayer entries.
        *   Overall: The total count of prayers across all configured countries and an aggregated timeline of these prayers.

5.  **Switching Between Countries**
    *   On pages displaying country-specific information (like the home page, prayed list, or statistics page), the user can typically select a different country (e.g., Israel or Iran).
    *   Upon selection, the page content (current representative, map display, data lists, statistics) dynamically updates to reflect the newly chosen country. The map image is regenerated if necessary via `/generate_map_for_country/<country_code>`.

6.  **Administrative Journey: Purging and Refreshing Data**
    *   A user with knowledge of the specific URL can navigate to `/purge`.
    *   This action clears all existing data from the `prayer_candidates` table in the database (both queued and prayed-for items).
    *   The system then automatically repopulates the prayer queue by reprocessing the source CSV files for all configured countries.
    *   The user is redirected to the home page, which will display a fresh prayer queue.
    *   The `/refresh` route is also mentioned but its primary function is to redirect to home, as the queue is managed by `update_queue` (called by `/purge` or on startup).
    *   **User Experience Enhancement**: Key interactions, such as marking a representative as prayed for or putting them back in the queue, are now handled using HTMX. This allows for partial page updates, providing a smoother and faster user experience by avoiding full page reloads for these actions.

## Contributing
Feel free to contribute by submitting pull requests or opening issues. If you're interested in the vision behind PrayReps then you might want to look at [the Kingdom Democracy Project's website](https://kingdomdemocracy.global/).

## Deploy to Render

You can deploy this application to Render by clicking the button below:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

Alternatively, you can manually deploy by following these steps:

1.  Fork this repository.
2.  Create a new Web Service on Render and connect your Fork.
3.  Ensure the Environment is set to `Python`.
4.  Use `pip install -r requirements.txt` as the build command.
5.  Use `gunicorn app:app` as the start command.
6.  Configure any necessary environment variables (e.g., `PYTHON_VERSION`).

## Logging and Persistence

*   The application generates general operational logs in `data/logs/app.log`.
*   **State Persistence:** The application's primary state (prayer queue, prayed-for status) is stored in a SQLite database file: `data/queue.db`.
*   **Important for Render/PaaS Deployments:** For the `data/queue.db` (and logs) to persist across deployments or restarts on platforms like Render, you must configure persistent storage (e.g., Render Disks).
    *   The `data/` directory, containing `queue.db`, needs to be mounted to this persistent storage.
    *   Without persistent storage, the `queue.db` file will be ephemeral and all prayer progress will be lost upon application restart or redeployment.
*   The old JSON-based logging for prayed-for items (e.g., `prayed_for_israel.json`) has been deprecated and replaced by the SQLite database. The application includes a one-time migration logic (`migrate_json_logs_to_db` in `app.py`) to transfer data from these old JSON files into the SQLite database if the `prayed_items` table (an older schema table, data from which is then migrated to `prayer_candidates`) is empty.

*   **Recommendation for Persistent Deployments:**
    1.  Set up a persistent disk on your deployment platform (e.g., Render).
    2.  Ensure the `data/` directory of your application is configured to use this persistent disk as its storage volume. This will preserve `queue.db` and `data/logs/app.log`.
    3.  The `DATABASE_URL` in `app.py` is already set to `os.path.join(DATA_DIR, 'queue.db')`, so as long as `DATA_DIR` (which is `data/`) is persistent, the database will be too.
