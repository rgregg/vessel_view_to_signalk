# Vessel View Mobile to Signal K

This project is a reverse engineering effort for the Mercury Vessel View Mobile application. I wanted to be able
to receive the data from the VVM via Bluetooth into a Raspberry Pi 4 that I had installed as a boat computer.

The application integrates with the SignalK API to publish data received from the Vessel View Mobile devices
into a Signal K server, which can then send the data to other devices connected to the network.

** This is a work in progress -- while I have decoded some of the protocol I do not yet have a working implementation **


## Run with Docker

docker run --net=host --privileged \
  -e VVM_DEVICE_ADDRESS=84:FD:27:D9:2C:BE \
  -e VVM_SIGNALK_URL=ws://192.168.6.1:3000/signalk/v1/stream?subscribe=none \
  -e VVM_USERNAME=admin \
  -e VVM_PASSWORD=admin \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  vvm_monitor

