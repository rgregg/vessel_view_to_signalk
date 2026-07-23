# BLE GATT Proxy — Hardware Test Plan (boat runbook)

Self-contained procedure to validate the BLE GATT proxy on the boat. Pick this up
when the engine/VVM is **powered on**; nothing here depends on the session that wrote it.

- Feature: single-radio transparent BLE GATT proxy so the native SmartCraft app and the
  connector can both use the VVM over its one BLE connection slot.
- Design: [`docs/superpowers/specs/2026-07-20-ble-gatt-proxy-design.md`](superpowers/specs/2026-07-20-ble-gatt-proxy-design.md)
- Plan: [`docs/superpowers/plans/2026-07-20-ble-gatt-proxy.md`](superpowers/plans/2026-07-20-ble-gatt-proxy.md)
- Branch / PR: `ble-gatt-proxy` / **PR #52 (draft)**. All host-testable code is done + reviewed;
  196 unit tests green. **Do not mark the PR ready or merge until both gates below pass.**
- Test image (already built + smoke-tested by CI): **`rgregg/vvm_monitor:pr-52`** (multi-arch, incl. arm64).
- VVM BLE address used below: `84:FD:27:D9:2C:BE` (substitute your device's address if different).

Deployment specifics (how to reach the Pi, the compose stack path/service name) are intentionally
not in this public doc — use your normal boat deployment process. The steps below say *what* to
change; apply them with your usual `docker compose` workflow for the connector service.

---

## Prerequisites

- [ ] Engine / VVM **powered on** and advertising (this whole plan is meaningless with it off).
- [ ] Boat Pi reachable; connector currently running on `:1` (= v1.3.0).
- [ ] A phone with the native SmartCraft / VesselView Mobile app, logged in, near the boat.
- [ ] The Pi's Bluetooth controller supports concurrent roles — already confirmed via BlueZ
      (`bluetoothctl show` → `Roles: central` + `Roles: peripheral`). Gate 1 proves it holds
      *while a VVM connection is open*, which is the part that can't be confirmed off-hardware.

---

## Gate 1 — Concurrency spike (single-radio go/no-go)

**Goal:** prove the onboard radio can advertise a peripheral *while* holding the VVM central
connection. This isolates "the radio can't do concurrent roles" (→ dual-adapter fallback) from
"a bug in the proxy logic" — run it before the full E2E so a failure is unambiguous.

The spike must be the only thing using the radio, so **stop the connector first** (it would
otherwise hold the VVM's single slot and fight the spike).

```bash
# 1) Stop the connector so it releases the VVM BLE connection.
#    (your normal: docker compose stop <connector service>)

# 2) Fetch the spike tool from the public branch (it is NOT baked into the image).
curl -fsSL -o /tmp/proxy_concurrency_spike.py \
  https://raw.githubusercontent.com/rgregg/signalk-vvm-ble-connector/ble-gatt-proxy/tools/proxy_concurrency_spike.py

# 3) Run it inside the pr-52 image (has bleak + bless + bluez), with host D-Bus + networking
#    so it talks to the host bluetoothd exactly like the connector does.
docker run --rm -it --net host \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v /tmp/proxy_concurrency_spike.py:/app/spike.py:ro \
  rgregg/vvm_monitor:pr-52 \
  python -u /app/spike.py --address 84:FD:27:D9:2C:BE --hold 60
```

**Expected GO output:**
```
... CENTRAL connected to VVM 84:FD:27:D9:2C:BE
... PERIPHERAL advertising as VVM_SPIKE_TEST -- both roles now live
... Holding both for 60s; watch for disconnects/errors...
... GO: both roles held for the full window with no error
```
While it holds, confirm on the phone (a generic BLE scanner, e.g. nRF Connect) that
`VVM_SPIKE_TEST` is visible **at the same time** the central is connected.

**Decision:**
- **GO** — both roles held 60s, no error, `VVM_SPIKE_TEST` seen while connected → proceed to Gate 2.
- **NO-GO** — advertising rejected while connected, or the VVM link drops when advertising starts,
  or an HCI/BlueZ error → **stop.** Single-radio (Approach A) is not viable on this hardware;
  switch to the **dual-adapter fallback** documented in the design spec (add a USB BLE dongle;
  central on `hci0`, peripheral on `hci1`). Do not merge the PR. Record the exact error.

Afterward, restart the connector on `:1` if you want data flowing before Gate 2, or go straight
into Gate 2 (which replaces the running image anyway).

---

## Gate 2 — End-to-end proxy on the boat

**Goal:** with the proxy actually running, confirm (a) the connector still feeds SignalK,
(b) the native app connects **through the proxy** and shows live engine data, (c) all relayed
traffic is captured, and (d) the forwarded indicate-subscribes don't drop the upstream link.

### Deploy the test image with the proxy enabled

1. Point the connector service's image at **`rgregg/vvm_monitor:pr-52`** (back up the current
   compose first; today it's `:1`).
2. Add this block to the connector's `config/vvm_monitor.yaml` (the proxy is **off** unless present):
   ```yaml
   proxy:
     enabled: true
     capture-file: ./logs/ble_capture.log
     # advertised-name defaults to ble-device.name; set explicitly if you want:
     # advertised-name: "VVM_84FD27D92CBE"
   ```
3. Pull + recreate the connector (`docker compose pull` + `up -d` for the service), then tail its log.

### Checks

- [ ] **(a) Proxy came up.** Connector log shows, on connect:
      `BLE GATT proxy enabled (advertising as VVM_...)` then `Proxy relay active (advertising VVM_...)`.
- [ ] **(b) SignalK still flowing.** On the Pi: `curl -s http://localhost:3000/signalk/v1/api/vessels/self/propulsion | head`
      shows values updating (RPM/temp/etc.) — the proxy must not have starved the connector's own feed.
- [ ] **(c) App connects through the proxy.** On the phone, open the native app, pick `VVM_...`
      from the scan list (only our peripheral should appear — the real VVM isn't advertising while
      we hold its slot), and confirm it connects and shows **live** engine data (RPM changing,
      temps, fuel). Device-info fields (model/firmware) should be populated, not blank.
- [ ] **(d) Capture populating.** `logs/ble_capture.log` grows with both `app->vvm` and `vvm->app`
      lines (timestamped hex). This is the protocol-capture deliverable.

### Indicate-subscribe check (settles the #37 question)

The native app subscribes (CCCD) to the indicate control chars `0x0301 / 0x0302 / 0x0401 / 0x2a05`.
Those subscribes historically dropped the link for *our* connector (issue #37) but the app does
them fine. The proxy forwards the app's exact sequence.

- [ ] Right after the app connects, watch the connector log for an upstream drop
      (`BLE device disconnected` / return to scan loop) coinciding with the app's subscribes.
- [ ] In `logs/ble_capture.log`, find the app's `write`/`subscribe` lines to `...0301/0302/0401/2a05`.
      If the VVM link drops immediately after one specific CCCD, **note which UUID** — the follow-up
      is to add a deny-list in `ProxyRelay._forward_write` that stops forwarding just that one
      (the app still gets data). If nothing drops, #37 was a client-side ordering quirk, now moot.

### Data to capture (paste back / save to `~/vvm-fault-docs/` or the PR)

1. Gate 1 spike output (GO / exact NO-GO error).
2. Connector log excerpt covering one full connect (proxy-active line through steady streaming),
   and any disconnects.
3. First ~200 lines of `logs/ble_capture.log` (the app's connect handshake — useful for the
   fault-code / native-client RE effort regardless of outcome).
4. Whether the native app showed live data (y/n) and whether any field was blank.
5. Whether/which forwarded CCCD dropped the link.

---

## Rollback (return the boat to stable at any point)

1. Repoint the connector image from `:pr-52` back to **`:1`** (= v1.3.0 — this is safe; `:1`
   already contains everything in main incl. #49).
2. Remove (or set `enabled: false` in) the `proxy:` block in `config/vvm_monitor.yaml`.
3. `docker compose pull` + `up -d` the connector. Confirm normal streaming + SignalK.

---

## On GO (both gates pass)

1. Save the captured artifacts and note results in the PR (#52) and the design spec.
2. Mark **PR #52 ready for review** and merge to `main`.
3. Cut a semver tag (e.g. `v1.4.0`) on `main` → CI publishes `1.4.0/1.4/1/latest`.
4. Repoint the boat from the `pr-52` test image to the released `:1` and keep `proxy.enabled: true`.
5. Follow-ups noted in the design/plan (non-blocking): parallelize connect-time pre-reads;
   add regression tests for the off-loop/`main()` wiring branches; harden write-arbitration once
   the capture shows real app behavior.
