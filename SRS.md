# Software Requirements Specification (SRS) for PrayReps_Israel_Iran

## Table of Contents
1.  [Introduction](#introduction)
    1.1. [Purpose](#purpose)
    1.2. [Scope](#scope)
    1.3. [Definitions, Acronyms, and Abbreviations](#definitions-acronyms-and-abbreviations)
    1.4. [References](#references)
    1.5. [Overview](#overview)
2.  [Overall Description](#overall-description)
    2.1. [Product Perspective](#product-perspective)
    2.2. [Product Functions](#product-functions)
    2.3. [User Characteristics](#user-characteristics)
    2.4. [Constraints](#constraints)
    2.5. [Assumptions and Dependencies](#assumptions-and-dependencies)
3.  [System Features](#system-features)
    3.1. [Praying for Representatives](#praying-for-representatives)
    3.2. [Viewing Prayer Queue](#viewing-prayer-queue)
    3.3. [Viewing Prayed-For Representatives](#viewing-prayed-for-representatives)
    3.4. [Viewing Statistics](#viewing-statistics)
    3.5. [Switching Between Countries](#switching-between-countries)
    3.6. [Administrative Data Management](#administrative-data-management)
4.  [External Interface Requirements](#external-interface-requirements)
    4.1. [User Interfaces](#user-interfaces)
    4.2. [Hardware Interfaces](#hardware-interfaces)
    4.3. [Software Interfaces](#software-interfaces)
    4.4. [Communication Interfaces](#communication-interfaces)
5.  [Other Nonfunctional Requirements](#other-nonfunctional-requirements)
    5.1. [Performance Requirements](#performance-requirements)
    5.2. [Safety Requirements](#safety-requirements)
    5.3. [Security Requirements](#security-requirements)
    5.4. [Software Quality Attributes](#software-quality-attributes)

---

## 1. Introduction

### 1.1. Purpose
The purpose of this Software Requirements Specification (SRS) document is to provide a detailed description of the "PrayReps_Israel_Iran" web application. It will outline the functionalities, features, constraints, and goals of the system. This document is intended for stakeholders, developers, and testers to ensure a common understanding of the product.

### 1.2. Scope
The "PrayReps_Israel_Iran" application is a web-based tool designed to help users systematically pray for elected representatives in Israel and Iran. Key functionalities include:
*   Displaying representative information (name, party, photo if available).
*   Managing a prayer queue of representatives.
*   Tracking which representatives have been prayed for.
*   Visualizing representatives' locations on hexagonal maps.
*   Providing statistics on prayer activity.
*   Allowing users to switch between praying for representatives in Israel and Iran.
*   Administrative functions for data purging and refreshing.

This version focuses specifically on representatives from Israel and Iran, utilizing CSV data sources and GeoJSON for map layouts. Future versions might expand to include other countries or more complex data management.

### 1.3. Definitions, Acronyms, and Abbreviations
*   **SRS**: Software Requirements Specification
*   **MVP**: Minimum Viable Product
*   **UI**: User Interface
*   **CSV**: Comma-Separated Values
*   **JSON**: JavaScript Object Notation
*   **GeoJSON**: A format for encoding a variety of geographic data structures.
*   **Flask**: A micro web framework written in Python.
*   **Gunicorn**: A Python WSGI HTTP Server for UNIX.
*   **HTMX**: A library that allows access to AJAX, CSS Transitions, WebSockets and Server Sent Events directly in HTML.
*   **Representative**: An elected official or public servant in Israel or Iran.
*   **Prayer Queue**: A list of representatives waiting to be prayed for.
*   **Hex Map**: A hexagonal grid map used to visualize geographical areas or entities.
*   **PostgreSQL**: An open-source relational database system.

### 1.4. References
*   Project `README.md`: Provides an overview of the project, setup instructions, and user journeys.
*   Project `app.py` and related modules in the `project/` directory: Source code defining the application's logic and structure.
*   Flask Documentation: [https://flask.palletsprojects.com/](https://flask.palletsprojects.com/)
*   HTMX Documentation: [https://htmx.org/](https://htmx.org/)

### 1.5. Overview
This SRS document is organized into five main sections:
*   **Section 1 (Introduction)**: Provides the purpose, scope, definitions, references, and overview of the document.
*   **Section 2 (Overall Description)**: Describes the product from a high-level perspective, including its functions, user characteristics, constraints, and dependencies.
*   **Section 3 (System Features)**: Details the specific functional requirements of the application, broken down by feature.
*   **Section 4 (External Interface Requirements)**: Specifies the interfaces with users, hardware, other software, and communication protocols.
*   **Section 5 (Other Nonfunctional Requirements)**: Outlines nonfunctional aspects such as performance, safety, security, and software quality.

---

## 2. Overall Description

### 2.1. Product Perspective
"PrayReps_Israel_Iran" is a self-contained web application. It is an iteration of a broader "PrayReps" concept aimed at facilitating prayer for elected representatives globally. This specific instance is tailored for Israel and Iran. The application is built using Python (Flask framework) and relies on a PostgreSQL database for data persistence. It is designed to be deployed on platforms like Render.

### 2.2. Product Functions
The main functions of the application are:
1.  **Representative Data Management**: Loads representative data from CSV files.
2.  **Prayer Queue Management**: Maintains a list of representatives to be prayed for, allowing users to pick the next one.
3.  **Prayer Tracking**: Records when a user has prayed for a representative.
4.  **Map Visualization**: Displays hexagonal maps of Israel and Iran, highlighting the location/hex of the current representative and marking prayed-for representatives.
5.  **Statistics Reporting**: Shows data on prayer activity, such as counts by party and prayer timelines.
6.  **User Interaction**: Provides a web interface for users to interact with the prayer queue, view maps, and access statistics.
7.  **Data Persistence**: Stores prayer queue status and prayed-for information in a PostgreSQL database.
8.  **Administrative Functions**: Allows for purging and refreshing the prayer queue data.

### 2.3. User Characteristics
The primary users of this application are individuals or groups (e.g., Christians) who wish to systematically pray for political leaders in Israel and Iran. Users are expected to have basic web browsing skills. Some users might have administrative privileges or knowledge to use specific URLs for data management tasks (e.g., `/purge`).

### 2.4. Constraints
*   **Data Source**: The application currently relies on predefined CSV files for representative data. The format and content of these CSVs are critical.
*   **Map Data**: GeoJSON files define the hexagonal map layouts. Changes to these may require code adjustments.
*   **Deployment Environment**: The application is designed with deployment platforms like Render in mind, which influences considerations for environment variables, build processes (`pip install -r requirements.txt`), and start commands (`gunicorn app:app`).
*   **Database**: The system uses PostgreSQL. Persistent storage must be configured for the database file (`queue.db` within the `data/` directory) in cloud deployment environments to avoid data loss.
*   **Technology Stack**: The application is built with Python, Flask, HTMX, Pandas, and other libraries specified in `requirements.txt`.
*   **Internet Connectivity**: Required for users to access the web application and for the application to potentially fetch external resources if any (though current design primarily uses local data files).
*   **Specific Countries**: The current version is hardcoded/configured primarily for Israel and Iran.

### 2.5. Assumptions and Dependencies
*   **Data Accuracy**: The data provided in the CSV files for representatives is assumed to be accurate and up-to-date at the time of loading.
*   **GeoJSON Validity**: The GeoJSON files used for map generation are assumed to be correctly formatted and representative of the intended geographical layouts.
*   **Python Environment**: A compatible Python environment with all dependencies listed in `requirements.txt` installed is required for the application to run.
*   **Browser Compatibility**: Users are assumed to use modern web browsers that support HTML5, CSS3, and JavaScript (for HTMX functionality).
*   **Persistent Storage**: For deployed instances, it's assumed that persistent storage is correctly configured for the `data/` directory to ensure the `queue.db` and logs persist across restarts and deployments.

---

## 3. System Features

### 3.1. Praying for Representatives
*   **FR3.1.1**: The system shall display one representative from the prayer queue on the home page.
*   **FR3.1.2**: The displayed information for a representative shall include their name, photo (if available), political party, and the country/location they serve.
*   **FR3.1.3**: The system shall display a hex map of the representative's country.
*   **FR3.1.4**: The hex on the map corresponding to the current representative shall be highlighted (e.g., in yellow).
*   **FR3.1.5**: Hexes on the map corresponding to previously prayed-for representatives shall be marked with a heart icon.
*   **FR3.1.6**: The user shall be able to indicate they have prayed for the current representative (e.g., by clicking a "Prayed" button).
*   **FR3.1.7**: Upon marking a representative as prayed for, the system shall update the database to reflect this status and record the timestamp.
*   **FR3.1.8**: After a representative is marked as prayed for, the hex map shall refresh, showing a heart icon on the hex of the just-prayed-for representative.
*   **FR3.1.9**: The home page shall then display the next available representative from the queue.
*   **FR3.1.10**: Interactions like marking as prayed shall use HTMX for partial page updates to enhance user experience.

### 3.2. Viewing Prayer Queue
*   **FR3.2.1**: The system shall provide a dedicated page (e.g., `/queue_page`) to list all representatives currently in the 'queued' state.
*   **FR3.2.2**: The queue page shall display details for each queued representative, such as name, party, and country.

### 3.3. Viewing Prayed-For Representatives
*   **FR3.3.1**: The system shall provide a dedicated page (e.g., `/prayed_list_page` or country-specific like `/prayed/<country_code>`) to list all representatives who have been prayed for.
*   **FR3.3.2**: The prayed-for list shall display representative details and the timestamp of when they were prayed for.
*   **FR3.3.3**: From the prayed-for list, the user shall have an option to "put back" a representative into the prayer queue.
*   **FR3.3.4**: Putting a representative back into the queue shall change their status from 'prayed' to 'queued' in the database and update map visualizations accordingly.
*   **FR3.3.5**: The "put back" action shall use HTMX for partial page updates.

### 3.4. Viewing Statistics
*   **FR3.4.1**: The system shall provide a statistics page (e.g., `/statistics_page` or country-specific `/statistics/<country_code>`).
*   **FR3.4.2**: For a specific country, statistics shall include a breakdown of prayed-for representatives by political party.
*   **FR3.4.3**: For a specific country, statistics shall include a timeline of prayer entries.
*   **FR3.4.4**: Overall statistics (across all configured countries) shall include the total count of prayers.
*   **FR3.4.5**: Overall statistics shall include an aggregated timeline of prayers.
*   **FR3.4.6**: Statistics pages may provide data via JSON endpoints for rendering charts (e.g., `/data/...`, `/timedata/...`).

### 3.5. Switching Between Countries
*   **FR3.5.1**: On pages displaying country-specific information (home page, prayed list, statistics), the user shall be able to select a different configured country (e.g., Israel or Iran).
*   **FR3.5.2**: Upon country selection, the page content (current representative, map display, data lists, statistics) shall dynamically update to reflect the chosen country.
*   **FR3.5.3**: The map image shall be regenerated if necessary (e.g., via an endpoint like `/generate_map_for_country/<country_code>`) when the country is switched.

### 3.6. Administrative Data Management
*   **FR3.6.1**: The system shall provide an administrative endpoint (e.g., `/purge`) to clear all existing prayer data (queued and prayed-for items) from the `prayer_candidates` table in the database.
*   **FR3.6.2**: After purging, the system shall automatically repopulate the prayer queue by reprocessing the source CSV files for all configured countries.
*   **FR3.6.3**: The system shall redirect the user to the home page after a purge operation, displaying a fresh prayer queue.
*   **FR3.6.4**: The system includes logic for a one-time migration from old JSON log files to the SQLite database if the relevant database tables are empty. (Note: `README.md` mentions SQLite for `queue.db`, `app.py` shows PostgreSQL connection logic. This SRS assumes the current implementation uses PostgreSQL as per `app.py`.)

---

## 4. External Interface Requirements

### 4.1. User Interfaces
*   **UI4.1.1**: The application shall provide a web-based user interface accessible through standard web browsers.
*   **UI4.1.2**: The UI shall be composed of HTML pages, styled with CSS, and enhanced with JavaScript (HTMX) for dynamic interactions.
*   **UI4.1.3**: Key UI elements include:
    *   Display area for representative information and photo.
    *   Interactive buttons for "Prayed" and "Put Back".
    *   Hexagonal map display.
    *   Navigation links/menus for Home, Queue, Prayed List, Statistics, About.
    *   Country selection mechanism (e.g., dropdown or links).
    *   Tables for displaying lists of representatives.
    *   Charts for visualizing statistics.
*   **UI4.1.4**: The UI should be intuitive and easy to navigate for users with basic web literacy.

### 4.2. Hardware Interfaces
*   There are no direct hardware interfaces for this application beyond standard web server and client hardware.

### 4.3. Software Interfaces
*   **SI4.3.1 Web Server**: The application interfaces with a WSGI HTTP server like Gunicorn for production deployment.
*   **SI4.3.2 Web Browser**: Users interact with the application via standard web browsers (e.g., Chrome, Firefox, Safari, Edge).
*   **SI4.3.3 Database**: The application interfaces with a PostgreSQL database to store and retrieve prayer queue data, prayed-for status, and timestamps. This interaction is managed through Python libraries like `psycopg2`.
*   **SI4.3.4 Data Files**:
    *   Reads representative data from CSV files using the Pandas library.
    *   Reads map layout data from GeoJSON files, likely using a library like GeoPandas (inferred from `hex_map_plotter.py`'s purpose).
*   **SI4.3.5 Python Libraries**: The application utilizes various Python libraries listed in `requirements.txt`, including Flask, Pandas, NumPy, etc.
*   **SI4.3.6 Operating System**: The application runs on an operating system that supports Python and the necessary server software (e.g., Linux).

### 4.4. Communication Interfaces
*   **CI4.4.1 HTTP/HTTPS**: The application uses the HTTP protocol (HTTPS recommended for production) for communication between the user's web browser and the web server.
*   **CI4.4.2 Database Protocol**: The application communicates with the PostgreSQL database server using the standard PostgreSQL wire protocol.

---

## 5. Other Nonfunctional Requirements

### 5.1. Performance Requirements
*   **PERF5.1.1**: Web pages should generally load within 3-5 seconds under normal operating conditions.
*   **PERF5.1.2**: HTMX partial updates (e.g., after clicking "Prayed") should complete within 1-2 seconds.
*   **PERF5.1.3**: Map generation should be efficient enough not to cause significant delays in page rendering.
*   **PERF5.1.4**: Database queries for fetching queue items, prayed lists, and statistics should be optimized for responsiveness.
*   **PERF5.1.5**: The application should be able to handle a moderate number of concurrent users (e.g., 10-20) without significant degradation in performance for a small-scale deployment.

### 5.2. Safety Requirements
*   **SAFE5.2.1 Data Integrity**: The system must ensure the integrity of the prayer data stored in the database. Changes (e.g., marking as prayed, putting back) must be accurately reflected.
*   **SAFE5.2.2 Data Backup**: While not explicitly implemented in the application code, for persistent deployments, regular backups of the PostgreSQL database are crucial to prevent data loss. This is an operational concern.
*   **SAFE5.2.3 Error Handling**: The application should gracefully handle common errors (e.g., file not found for CSV/GeoJSON, database connection issues) and provide informative (but not overly technical) messages to the user or log them appropriately.

### 5.3. Security Requirements
*   **SEC5.3.1 Data Protection**: Sensitive data, if any were to be collected in the future (currently, representative data is public), must be protected. For the current scope, this is less critical as data is publicly available information about representatives.
*   **SEC5.3.2 Input Validation**: Inputs from users or administrative actions (e.g., via URLs) should be validated to prevent common web vulnerabilities (e.g., XSS, CSRF - Flask provides some protection).
*   **SEC5.3.3 Dependency Management**: Dependencies (Python libraries) should be kept up-to-date to mitigate known vulnerabilities.
*   **SEC5.3.4 Administrative Access**: Access to administrative functions like `/purge` should ideally be restricted, though the current implementation relies on obscurity of the URL.
*   **SEC5.3.5 HTTPS**: For production deployment, HTTPS should be enforced to encrypt data in transit.

### 5.4. Software Quality Attributes
*   **SQA5.4.1 Maintainability**:
    *   Code should be well-organized (e.g., using Flask Blueprints, service layers).
    *   Code should be commented where necessary to explain complex logic.
    *   Configuration (e.g., country details, file paths) should be managed in a clear and centralized way (e.g., `project/config.py`).
*   **SQA5.4.2 Usability**:
    *   The application should be easy to learn and use for the target audience.
    *   Navigation should be clear and consistent.
    *   Visual feedback should be provided for user actions (e.g., after clicking "Prayed").
*   **SQA5.4.3 Reliability**:
    *   The application should operate without frequent crashes or unexpected behavior.
    *   Data persistence should be reliable, ensuring that prayer progress is saved correctly.
*   **SQA5.4.4 Testability**:
    *   The codebase should be structured to allow for unit testing of components (as evidenced by the `tests/` directory).
*   **SQA5.4.5 Scalability (Limited)**:
    *   While not designed for massive scale, the application should handle data for a few countries and a growing list of prayed-for items efficiently for its intended use. The use of a PostgreSQL database supports better scalability than file-based storage.
*   **SQA5.4.6 Extensibility**:
    *   The design should allow for future enhancements, such as adding more countries, with reasonable effort. Configuration-driven aspects (like in `COUNTRIES_CONFIG`) support this.
