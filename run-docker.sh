#!/bin/bash
docker run --net=host --privileged --restart always  -e VVM_DEVICE_ADDRESS=84:FD:27:D9:2C:BE -e VVM_SIGNALK_URL=ws://192.168.6.1:3000/signalk/v1/stream?subscribe=none -it -v ./:/src -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket -e VVM_USERNAME=admin -e VVM_PASSWORD=evka7bVDUitn6WPdtMd9 vvm_monitor

