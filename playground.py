def to_cubic_meters(value):
    # Conversion factors
    gallons_to_cubic_meters = 0.00378541
    hours_to_seconds = 3600

    # raw value
    gallons_per_hour = value * 0.00267
    print(f"GPH: {gallons_per_hour}")

    # conversion
    cubic_meters_per_second = gallons_per_hour * (gallons_to_cubic_meters / hours_to_seconds)
    return cubic_meters_per_second


def decode_parameter_configuration(array_of_data):
        
    # Make sure the data is sorted correctly before decoding, they could
    # arrive out of order.
    sorted_data = sorted(array_of_data, key=lambda x: x[0])

    # Data appears to be formatted accordingly:
    # Each line starts with a two byte value indicating the order of this segment 00, 01, 02, 03 -> 09

    # strip the first two bytes
    clean_data = [ d[1:] for d in sorted_data ]
    combined_data = bytearray()
    for b in clean_data:
        combined_data.extend(b)

    parameters = dict()
    header = combined_data[:5]
    parameters["header"] = header.hex()
    
    data = combined_data[5:]
    chunks = [data[i:i + 4] for i in range(0, len(data), 4)]
    for value in chunks:
        if int.from_bytes(value[2:]) != 0:
            parameters[value[:2].hex()] = value[2:].hex()

    return parameters

hex_strings = [
            "0028b6000100000001000001d2000002e8000003",
            "0170170004960000050a000006401f0007102700",
            "0208b5000009d400000ab600000bfb00000c0000",
            "0400010300000104000001050000010600000107",
            "03000d0000000e00000100000001010000010200",
            
            "0500000108000001090000010a0000010b000001",
            "060c0000010d0000010e00000200000002010000",
            "0702020000020300000204000002050000020600",
            "0800020700000208000002090000020a0000020b",
            "090000020c0000020d0000020e0000",
]


raw_data = [bytes.fromhex(h) for h in hex_strings]
print(f"Original data: {raw_data}")

data = decode_parameter_configuration(raw_data)

print(f"{data}")


fuel = "b518"
int_value = int.from_bytes(bytes.fromhex(fuel), byteorder="little")
print(f"Fuel data: {int_value}")
result = to_cubic_meters(int_value)
print(f"M^2/S: {result}")


"""
Header = 5 bytes, 28 b6 00 01 00

Values are in the form of 4 bytes:
    00 11 22 33

where 0011 is a reference to the data type
  and 2233 are the header value on the value received on the charactieristic notification

For example, 0000 seems to be engine RPM, and returns:
    0000 0100
which aligns to the Engine RPM notifications which arrive with a header of 0100

For example, 0001 seems to be coolant temperature, and returns:
    0001 d200
which aligns to the Coolant Temperature notifications, which arrive with a header of d200

This makes me think that my encoding my be wrong - instead of the characteristic UUIDs that are 
the key factor - it's the header bytes on each notification that indicate the value being received

"""
