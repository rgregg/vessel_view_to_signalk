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
1. App reads UUID: 00000302-0000-1000-8000-ec55f9f5b963 (handle 6B)
    Received: 63b9f5f955ec-0080-0010-0000-00040000            

        // This looks like a UUID in litten-endian encoding: 00000400-0000-1000-8000-ec55f9f5b963


// Check 001
2. Enables indication on 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x16)

// Turn off streaming
3. Writes a value to UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 0d00
4. Receives indication on UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 000d01

5. Writes to UUID 00000001-0000-1000-8000-ec55f9f5b963 (handle 0x15)
        Value: 28000301
6. Receives indications on handle 0x0015:
        Value: 00 28b6000100000001000001d2000002e8000003
        Value: 01 70170004960000050a000006401f0007102700
        Value: 02 08b5000009d400000ab600000bfb00000c0000
        Value: 03 000d0000000e00000100000001010000010200
        Value: 04 00010300000104000001050000010600000107
        Value: 05 00000108000001090000010a0000010b000001
        Value: 06 0c0000010d0000010e00000200000002010000
        Value: 07 02020000020300000204000002050000020600
        Value: 08 00020700000208000002090000020a0000020b
        Value: 09 0000020c0000020d0000020e0000

28b6000100000001000001d2000002e800000370170004960000050a000006401f000710270008b5000009d400000ab600000bfb00000c0000000d0000000e000001000000010100000102000001030000010400000105000001060000010700000108000001090000010a0000010b0000010c0000010d0000010e000002000000020100000202000002030000020400000205000002060000020700000208000002090000020a0000020b0000020c0000020d0000020e0000

        Value: 28b6000100  0000-0100 0001-d200 0002-e800 0003-7017 0004-9600 0005-0a00 0006-401f 0007-1027
                           0008-b500 0009-d400 000a-b600 000b-fb00 000c-0000 000d-0000 000e-0000 0100-0000
                           0101-0000 0102-0000 0103-0000 0104-0000 0105-0000 0106-0000 0107-0000 0108-0000
                           0109-0000 010a-0000 010b-0000 010c-0000 010d-0000 010e-0000 0200-0000 0201-0000
                           0202-0000 0203-0000 0204-0000 0205-0000 0206-0000 0207-0000 0208-0000 0209-0000
                           020a-0000 020b-0000 020c-0000 020d-0000 020e-0000




        Value: 28b600010000 00010000 01d20000 02e80000 03701700 04960000 050a0000 06401f00 07102700
                            08b50000 09d40000 0ab60000 0bfb0000 0c000000 0d000000 0e000000 10000000
                            10100000 10200000 10300000 10400000 10500000 10600000 10700000 10800000
                            10900000 10a00000 10b00000 10c00000 10d00000 10e00000 20000000 20100000
                            20200000 20300000 20400000 20500000 20600000 20700000 20800000 20900000 
                            20a00000 20b00000 20c00000 20d00000 20e0000        

7. Turns off notifications/indications on UUID: 00000201-0000-1000-8000-ec55f9f5b963 (handle 0x005f)

// Check 111
8. Turns on Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x005a)
9. Writes to UUID: 00000111-0000-1000-8000-ec55f9f5b963 (Handle 0x59): 
        Value: 102700
10. Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x59)
        Value: 00102701 010001

11. Turns on Indication on UUID 00000111-0000-1000-8000-ec55f9f5b963, handle: 0x005a
12. Writes to UUID 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x0059)
        Value: ca0f00
13. Indication on 0x0059
        Value: 00ca0f01 010000 (confirmed)

14. Turns on Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle: 0x005a)
15. Turns on Indication on UUID: 00000111-0000-1000-8000-ec55f9f5b963 (handle: 0x005a) - does this twice??
16. Writes to UUID 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x0059)
        Value: c80f00
17. Receives indication UUID 00000111-0000-1000-8000-ec55f9f5b963 (handle 0x0059)
        Value: 00c80f01 040000000000

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


### Coolant Temperature (00000103-0000-1000-8000-ec55f9f5b963)

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

Data is centiliters per hour (e.g. liters * 100). This can be converted to GPH by multiplying by 0.00267

6325 = 63.25 Liters per hour = 16.7088823.. GPH = 0.000017569444444444444 cubic meters per second
5617 = 15.0 GPH
     = 56.17 LPH
100  = 1 LPH


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

Looks like the data is stored as deca-pascals (10s) of Pascals. To convert to PSI value / 689.476. To convert to Pascals * 10.


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


