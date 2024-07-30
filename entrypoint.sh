#!/bin/bash

# start services
#service dbus start
service bluetooth start

# start application
python vvm_monitor.py
