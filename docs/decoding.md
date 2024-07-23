# Decoding

## Data from app

Engine Hours: 96.7
Serial Number: 2A690578
Software ID: BRZ15_AAY
Calibration ID: BRZ15_AAY25_300dBOE_G2P26_000
VVM Module ID: 84:FD:27:D9:2C:BE
Firmware Verson: 1.0.3-2


## Notes


Bluetooth LE - Indications and Notifications

- Indications are notifications which need to be acknoledged by the client before the next indication is sent
- Notifications steam without needing to be acknoledged

## Data Pattern


### Initial detection / configuration / initalization of the VVM


// Check 300
1. App reads UUID: 00000300-0000-1000-8000-ec55f9f5b963 (handle 6B)
    Received: 63b9f5f955ec00800010000000040000

// Check 001
2. Enables indication on 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x16)
3. Writes a value to UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 0d00
4. Receives indication on UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 000d01
5. Writes to UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 28000301
6. Receives indications on handle 0x0015, which are confirmed:
        Value: 0028b6000100000001000001d2000002e8000003
        Value: 0170170004960000050a000006401f0007102700
        Value: 0208b5000009d400000ab600000bfb00000c0000
        Value: 03000d0000000e00000100000001010000010200
        Value: 0400010300000104000001050000010600000107
        Value: 0500000108000001090000010a0000010b000001
        Value: 060c0000010d0000010e00000200000002010000
        Value: 0702020000020300000204000002050000020600
        Value: 0800020700000208000002090000020a0000020b
        Value: 090000020c0000020d0000020e0000

7. Turns off notifications/indications on UUID: 00000201-0000-1000-8000-ec55f9f5b963 (handle 0x005f)

// Check 111
8. Turns on Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x005a)
9. Writes to UUID: 00000111-0000-1000-8000-ec55f9f5b963 (Handle 0x59): 
        Value: 102700
10. Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x59)
        Value: 00102701010001

11. Turns on Indication on UUID 00000111-0000-1000-8000-ec55f9f5b963, handle: 0x005a
12. Writes to UUID 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x0059)
        Value: ca0f00
13. Indication on 0x0059
        Value: 00ca0f01010000 (confirmed)

14. Turns on Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle: 0x005a)
15. Turns on Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle: 0x005a) - does this twice??
16. Writes to UUID 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x0059)
        Value: c80f00
17. Receives indication UUID 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x0059)
        Value: 00c80f01040000000000

// Enable notifications on key characteristics

18. Enables notifications on:
    - 00000102-0000-1000-8000-ec55f9f5b963 (0x001e)
    - 00000103-0000-1000-8000-ec55f9f5b963 (0x0022)
    - 00000104-0000-1000-8000-ec55f9f5b963 (0x0026)
    - 00000105-0000-1000-8000-ec55f9f5b963 (0x002a)
    - 00000106-0000-1000-8000-ec55f9f5b963 (0x002e)
    - 00000107-0000-1000-8000-ec55f9f5b963 (0x0032)
    - 00000108-0000-1000-8000-ec55f9f5b963 (0x0036)
    - 00000109-0000-1000-8000-ec55f9f5b963 (0x003a)
    - 0000010a-0000-1000-8000-ec55f9f5b963 (0x003e)
    - 0000010b-0000-1000-8000-ec55f9f5b963 (0x0042)
    - 0000010c-0000-1000-8000-ec55f9f5b963 (0x0046)
    - 0000010d-0000-1000-8000-ec55f9f5b963 (0x004a)

19. Enables indications on:
    - 00000201-0000-1000-8000-ec55f9f5b963 (0x005f)

/// Enable streaming
20. Writes to UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 0d01
21. Receives indication on 0x0015
        Value: 000d01

23. Notification stream starts streaming properties above
24. Repeats enable notifications routine (no obvious trigger for why it did this...)
29. Data streams for a very long time...




## DISCOVERED VALUES


### Engine RPM (00000102-0000-1000-8000-ec55f9f5b963)

UUID: 00000102-0000-1000-8000-ec55f9f5b963
Handle: 0x001d
Size: 10-byte attribute (8-byte value)
Header: 0x0100

Value is expressed as rotations per minute (RPM).


### Cooleant Temperature (00000103-0000-1000-8000-ec55f9f5b963)

UUID: 00000103-0000-1000-8000-ec55f9f5b963
Handle: 0x0021
Size: 10-byte attribute (8 byte value)
Header: 0xd200

Value is expressed as temperature in Celsius. It can be converted to F by value x (9/5.0) + 32.


### Battery Voltage (00000104-0000-1000-8000-ec55f9f5b963)

UUID: 00000104-0000-1000-8000-ec55f9f5b963
Handle: 0x0025
Size: 10-byte attribute (8-byte value)
Header: 0xe800

Value is the battery voltage * 1000, so 14000 = 14.00 volts


### Unknown (00000105-0000-1000-8000-ec55f9f5b963)

UUID: 00000105-0000-1000-8000-ec55f9f5b963
Handle: 0x0029
Size: 18-byte attribute (16-byte value)
Header: 0x7017

Range: 204557 - 208986

Data spikes up around 17:21, then increases linearly until approaching the max value
Oil Temperature??


### Engine Run Time (00000105-0000-1000-8000-ec55f9f5b963)

UUID: 00000106-0000-1000-8000-ec55f9f5b963
Handle: 0x002d
Size: 18-byte attribute (16-byte value)
Header: 0x9600

Data is stored as minutes - value / 60.0 to get hours


### Current Fuel Flow (00000107-0000-1000-8000-ec55f9f5b963)

UUID: 00000107-0000-1000-8000-ec55f9f5b963
Handle: 0x0031
Size: 10 byte attribute (8 byte value)
Header: 0x0a00

Data is Liters per Hour * 100. This can be converted to GPH by multiplying by 0.00267

### Unknown (00000108-0000-1000-8000-ec55f9f5b963)

UUID: 00000108-0000-1000-8000-ec55f9f5b963
Handle: 0x0035
Size: 10 byte attribute (8 byte value)
Header: 0x401f

Observed data was always fixed at 8000.


### Unknown (00000109-0000-1000-8000-ec55f9f5b963)

UUID: 00000109-0000-1000-8000-ec55f9f5b963
Handle: 0x0039
Size: 3 byte attribute

Observed value was always 0x012710

### Oil Pressure (0000010a-0000-1000-8000-ec55f9f5b963)

UUID: 0000010a-0000-1000-8000-ec55f9f5b963
Handle: 0x003d
Size: 10-byte attribute (8-byte value)
Header: 0xb500

Looks like the data is stored as 10s of Pascals. To convert to PSI value / 689.5


### Unknown (0000010b-0000-1000-8000-ec55f9f5b963)

UUID: 0000010b-0000-1000-8000-ec55f9f5b963
Handle: 0x0041
Size: 10-byte attribute (8-byte value)
Header: 0xd400

Observed values: 0 - 19247

Observed data:
- Value is 0 before ignition
- jumping to 3548 at ignition
- then slowly ramping down to 1734
- when the boat is put into geer, it moves up to 13801
- the data is very noisy initially, jumping between 12000-19000
- finally settles down and follows engine RPM pattern very closely
- slowly moves from (low value) to zero with engine off

Intake Manifold Pressure? Fuel Pressure?
Values between 0-27.9 PSI using the conversion from Oil Pressure


### Unknown (0000010c-0000-1000-8000-ec55f9f5b963)

UUID: 0000010c-0000-1000-8000-ec55f9f5b963
Handle: 0x0045
Size: 10-byte attribute (8-byte value)
Header: 0xb600

No data observed - value is always 0

### Unknown (0000010d-0000-1000-8000-ec55f9f5b963)

UUID: 0000010d-0000-1000-8000-ec55f9f5b963
Handle: 0x0049
Size: 10-byte attribute (8-byte value)
Header: 0xfb00

No data observed - value is always 0


