# Vessel View Mobile to Signal K

This project is a reverse engineering effort for the Mercury Vessel View Mobile application and bluetooth device.
I was looking for an easy way to connect my MerCrusier engine to SignalK so I can bring together all the information
for navigating, performance, and running my boat on one screen.

To achieve this, I'm using the [SignalK server](http://signalk.org) on a Raspberry Pi 4 with this module
running as a docker container and exporting signals to the SignalK API.

**NOTE:** This project is not affiliated with Mercury or MerCruiser.

## Supported Configuration

My boat is a relatively new SmartCraft boat with a single MerCrusier gasoline engine. I've been using the data
I can observe from this configuration to build this setup, so support is limited to the parameters I can observe
and decode.

Currently supported:

- Single engine connected to the Vessel View Mobile device
- Parameters:
  - Engine RPM
  - Coolant Temperature
  - Battery / Alternator Voltage
  - Engine Run Time
  - Current Fuel Flow
  - Oil Pressure

So far there are four other parameters which I can see data for but
I have been unable to determine what they map back to. I'll continue to investigate and update accordingly.

## Run with Docker

To run, I'm using the docker image - you can also run the 
python script directly using Python3.

The app reads configurmation from `/app/config/vvm_monitor.yaml` which you can map in from a volume mount in Docker. You can 
also configure values through environment variables, or on the command line.

To start the container on a Raspberry Pi or other Linux system:

```bash
docker run  \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v ./config:/app/config \
  rgregg/vvm_monitor:latest
```

You can also provide configuration via environment variables:

```bash
docker run  \
  -e "VVM_DEVICE_ADDRESS=11:22:33:44:55:66" \
  -e "VVM_SIGNALK_URL=ws://127.0.0.1:3000/signalk/v1/stream?subscribe=none" \
  -e "VVM_USERNAME=admin" \
  -e "VVM_PASSWORD=admin" \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  --network=host \
  --priviledged \
  vvm_monitor
```

### Example configuration file

Copy the text and place it into a folder which is mapped to `/app/config` in the container.
The filename must be `vvm_monitor.yaml`.

Only the device address or name is required - if you provide both any device that matches either
value will be used.

```yaml
ble-device:
  address: 11:22:33:44:55:66
  name: "VVM 1234123123"
  retry-interval-seconds: 30
  data-recording:
    enabled: true
    file: ./logs/data.csv
    keep: 0
signalk:
  websocket-url: ws://127.0.0.1:3000/signalk/v1/stream?subscribe=none
  username: admin
  password: pass
  retry-interval-seconds: 30
logging:
  level: INFO
  file: ./logs/vvm_monitor.log
  keep: 5
```
