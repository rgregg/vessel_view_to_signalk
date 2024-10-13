#!/bin/bash

# start services
#service dbus start
service bluetooth start

# start application
python -m vvm_to_signalk
