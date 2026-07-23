# BLE GATT Proxy — Design

**Date:** 2026-07-20
**Branch:** `ble-gatt-proxy` (off `main`)
**Status:** Approved design; not yet implemented. Opt-in, unmerged until proven on boat hardware.

## Problem

The VVM engine-gateway hardware allows **only one BLE connection at a time**. When our
connector holds that connection (to stream engine data into SignalK), the native
SmartCraft / VesselView Mobile app can no longer connect to the engine. The user must
choose: run the connector, *or* use the native app — not both.

## Goal

Let the native app and the connector both use the engine **at the same time**, over the
single physical BLE link, by turning the connector into a **transparent BLE GATT proxy**:
our app emulates the VVM as a BLE peripheral, the native app connects to *us*, and we relay
every exchange to/from the real VVM (which we hold as a central). As a deliberate byproduct,
the proxy **captures all relayed BLE traffic** to disk, feeding the ongoing fault-code /
native-client protocol reverse-engineering effort.

## Key facts that make this feasible

- **Open GATT, no pairing/bonding/encryption.** The connector connects to the VVM over
  unauthenticated GATT today (no `pair`/`bond`/`encrypt` anywhere in the code). The proxy
  does not have to replicate any security handshake.
- **The native app selects the VVM by name, not a pinned MAC.** The user picks
  `VVM_84FD27D92CBE` from a scan list each time. So our peripheral can advertise the same
  name and service UUIDs on its **own** address — **no MAC-cloning required**, and a
  **single-radio** design is viable.
- **Only our peripheral will be visible.** Because we hold the VVM's single connection slot,
  the real VVM stops advertising, so the app's scan list shows only our peripheral (no
  confusing duplicate).
- **Controller supports both roles.** Boat Pi controller is Cypress/Broadcom **BT 5.0**;
  BlueZ reports `Roles: central` and `Roles: peripheral`, 5 advertising instances. The one
  thing still to prove empirically: advertising *while* the VVM link is held (first impl
  step).

## GATT surface to clone

Custom service base `0000XXXX-0000-1000-8000-ec55f9f5b963`, characteristics:
- `0x0302` startup, `0x0001` config, `0x0111` next, `0x0201` fault (indicate)
- standard device-info chars (Model Number, Firmware Revision, Manufacturer Name, Device Name)
- indicate control chars the app subscribes to: `0x0301 / 0x0302 / 0x0401 / 0x2a05`

## Approach chosen

**Single radio (`hci0`), concurrent central + peripheral, using `bless` for the peripheral
role alongside the existing `bleak` central.** No extra hardware. Chosen over the
dual-adapter option (add a USB BLE dongle) as the try-first approach; dual-adapter remains
the documented fallback if the onboard controller can't sustain concurrent roles, or if we
ever discover the app *does* pin the MAC (which would force two radios).

Rejected: off-the-shelf BLE-MITM tools (gattacker / btlejack-style) — Node-based/aging,
need two adapters anyway, and live outside our connector so they can't feed SignalK or reuse
our decode logic.

## Architecture

One process, two BLE roles on `hci0`. Everything is behind an opt-in `proxy` mode
(config flag, default off). With the flag off, the connector behaves **exactly as today**
— zero regression risk.

```
   native app ──BLE(peripheral)──▶  VvmProxyPeripheral (bless GATT server)
                                        │  writes / CCCD-subscribes / reads (app→VVM)
                                        ▼
                                    ProxyRelay ◀──────────┐ notifications (VVM→app)
                                        │                 │
                                        ▼                 │
   real VVM ◀──BLE(central)──  BleDeviceConnection (existing bleak central)
                                        │
                                        ├──▶ SignalK decode/publish  (unchanged, always runs)
                                        └──▶ TrafficCapture (timestamped hex, both directions)
```

## Components (each a small, independently-testable unit)

1. **`BleDeviceConnection` (existing central)** — connects to the VVM, does its normal
   bootstrap init so **SignalK streaming is independent of whether the app is connected**,
   and receives all notifications. Minimal additions: a hook to fan out each upstream
   notification, and methods to issue a proxied write/read *on behalf of the app*.
2. **`GattProfileMirror`** — at upstream connect, discovers the VVM's
   services/characteristics/descriptors and builds an identical `bless` profile (same UUIDs,
   same notify/indicate/write/read properties, same CCCDs). Static device-info chars are read
   once and served as fixed values.
3. **`VvmProxyPeripheral` (`bless`)** — advertises as `VVM_84FD27D92CBE` with the cloned
   services; the app connects here. Serves app reads from a value cache; surfaces app
   writes/subscribes as events; pushes notifications to the app.
4. **`ProxyRelay`** — the coordinator wiring central ↔ peripheral. Forwards VVM→app
   (notifications) and app→VVM (writes, CCCD subscribes, reads), and owns the advertising
   lifecycle.
5. **`TrafficCapture`** — append-only, timestamped record of every relayed op (direction,
   char UUID, operation, hex payload) → the protocol-capture file. Size-based rotation,
   same pattern as `data.csv` / log rotation.

## Data flow

- **VVM → app:** the connector already subscribes to all notify chars (for SignalK). Each
  notification is (a) decoded for SignalK *and* (b) forwarded to the matching peripheral
  char; `bless` delivers it to the app if the app subscribed. The app rides the stream the
  connector already pulls.
- **App → VVM:** app writes a char (streaming-enable, channel config, engine-identity reads,
  fault subscribe, CCCD) → relay forwards it verbatim to the VVM via the central. This is
  what lets the app's own handshake reach the engine.
- **Reads:** served from the value cache (device-info + last-notified values); on a cache
  miss, a live proxy-read to the VVM.

## Shared-session model (the main design tension)

There is genuinely **one** VVM session with **one** shared config state. Both the connector's
bootstrap init *and* the app's writes act on that single session, as if they were one client.
The connector's decoder already follows the channel map dynamically, so app reconfiguration
is tolerated. Model: **connector does a minimal bootstrap init so SignalK works with no app
present, then stays passive and lets the app drive when connected.** Write-arbitration between
the connector's init and the app's writes is the main risk area; the capture log is how we
observe and resolve any real conflict.

## Error handling / lifecycle

- **Advertising gated on upstream health.** Advertise the peripheral **only while the VVM
  link is up and streaming.** When the engine is off and the upstream link drops, stop
  advertising and disconnect any connected app (mirrors a real VVM going off the air). Resume
  advertising when upstream reconnects. Prevents the app connecting to a dead relay.
- **Indicate-subscribe risk (biggest unknown).** The #37 outage suggested subscribing to the
  indicate control chars (`0x301/0x302/0x401/0x2a05`) makes the VVM drop the link (ATT
  `0x0e`) — which is why today's connector subscribes to **notify only**. But the native app
  subscribes to those indicate chars and works, so the trigger was likely *how/when* our
  connector subscribed, not the act itself. In proxy mode we forward the app's **exact CCCD
  writes, in the app's exact order and timing**, replicating known-good behavior. Mitigation:
  relay indicate-subscribes faithfully but **watch for an upstream drop** immediately after;
  if a specific CCCD reproducibly kills the link, fall back to *not* forwarding that one (log
  it; app still gets data). The capture log records the app's real sequence and finally
  settles the #37 question.
- **Concurrent-role failure on `hci0`** (Approach-A core risk): if advertising-while-connected
  fails on real hardware, log loudly and **degrade to plain connector mode** (SignalK keeps
  working). This is why the first implementation step is a standalone spike before any real
  proxy code.
- **App write conflicts with connector init:** connector does minimal bootstrap init, then
  goes passive; capture surfaces any stomping to resolve iteratively.

## Testing

- **Unit (host, no hardware)**, following the existing `test_blelogic.py` fake-BLE style:
  - `GattProfileMirror` clones a fake discovered profile correctly.
  - `ProxyRelay` forwards notifications app-ward and writes/CCCD VVM-ward (fakes for both roles).
  - `TrafficCapture` output format.
  - Advertising is gated on upstream state.
  - Proxy-mode-**off** leaves today's behavior byte-for-byte unchanged.
- **Hardware spikes (on the boat, gated, in order):**
  1. **Concurrency spike** — advertise a dummy peripheral on `hci0` while the connector holds
     the VVM link. Go/no-go for Approach A.
  2. **End-to-end** — native app connects through the proxy; engine data shows in the app
     **and** SignalK keeps flowing **and** the capture file populates.
  3. **Indicate-subscribe** — forwarded app subscriptions don't drop the upstream link.

## Rollout

- Opt-in `proxy.enabled` config (default off).
- Deploy a `pr-<N>` image to the boat (never touching `:1`), iterate through the spikes.
- Consider a release only once proven on hardware. Everything stays on `ble-gatt-proxy`
  until then.

## New dependency

`bless` (BLE peripheral / GATT server over BlueZ D-Bus, asyncio). Pairs with the existing
`bleak` central. Added to `requirements.txt`.
