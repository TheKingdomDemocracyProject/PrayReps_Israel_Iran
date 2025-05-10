# PrayReps_Kosovo_2025

A tool to pray for those elected to serve Kosovo on 9th February 2025.

## Overview
PrayReps is a tool that will eventually help Christians to pray for any elected representative, anywhere in the world. This Python app is an MVP that has already been used to pray for newly elected governments in the United Kingdom, France and the USA. 

The app enqueues the details of elected representatives and displays the location they serve on a map. When you have prayed for them that location is marked with a heart. The app contains rudimentary logging functionality to provide statistics as well as the ability to return individuals to the queue to pray for them again.

This implementation retrieves data from a CSV and uses JSON logging to manage the different records.

If you want to purge the queue and start again use the route /purge and then /refresh.

## Contributing
Feel free to contribute by submitting pull requests or opening issues. If you're interested in the vision behind PrayReps then you might want to look at [the Kingdom Democracy Project's website](https://kingdomdemocracy.global/).
