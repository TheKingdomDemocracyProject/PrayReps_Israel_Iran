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
