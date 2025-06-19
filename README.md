# PrayReps_Israel_Iran

A tool to pray for those representatives serving the countries of Israel and Iran.

## Overview
PrayReps is a tool that will eventually help Christians to pray for any elected representative, anywhere in the world. This Python app is an MVP that has already been used to pray for newly elected governments in the United Kingdom, France and the USA. 

The app enqueues the details of elected representatives and displays the location they serve on a map. When you have prayed for them that location is marked with a heart. The app contains rudimentary logging functionality to provide statistics as well as the ability to return individuals to the queue to pray for them again.

This implementation retrieves data from a CSV and uses JSON logging to manage the different records.

If you want to purge the queue and start again use the route /purge and then /refresh.

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

*   The application now generates more detailed logs in the `data/logs/` directory within the deployment. This includes:
    *   `app.log`: General application logs.
    *   `prayed_for_israel.json`, `prayed_for_iran.json` (etc.): JSON files storing the state of prayed-for items for each country. These are critical for the application's state.
*   **Important for Render/PaaS Deployments:** The persistence of the `data/logs/` directory (and therefore the application's state stored in the JSON files) depends on the platform's filesystem behavior. On ephemeral filesystems, which are common, this data may be lost upon application restarts or redeployments.
*   If you observe that the queue is always empty or previously prayed-for items are not remembered after a redeploy or restart on Render, it is likely due to the ephemeral nature of the filesystem where these state files are stored.
*   For true persistence of the prayed-for state, a database or a platform-specific persistent storage solution (like Render Disks) would be necessary. This would involve:
    1.  Configuring the persistent storage on the platform (e.g., adding a Disk in `render.yaml`).
    2.  Updating the `LOG_DIR` variable in `app.py` to point to the mount path of this persistent storage.
*   The current setup prioritizes simple deployment. If state loss is problematic, adapting the application to use a persistent storage solution is the recommended next step.
