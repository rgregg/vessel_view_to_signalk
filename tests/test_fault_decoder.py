from vvm_to_signalk.fault_decoder import parse_fault, Fault

def test_legacy_fault():
    # byte0: type=2 (Legacy) low nibble, engine=1 high nibble -> 0x12
    # byte1: active bit -> 0x01 ; bytes2-3: fault id 0x0457 = 1111 (LE 57 04)
    f = parse_fault(bytes.fromhex("12" "01" "5704"))
    assert f.fault_type == "Legacy"
    assert f.engine_position == 1
    assert f.is_active is True
    assert f.fault_id == 1111
    assert f.fault_key == "1111-Legacy"

def test_legacy_fault_cleared():
    f = parse_fault(bytes.fromhex("12" "00" "5704"))
    assert f.is_active is False

def test_universal_fault_bitfields():
    # Construct a uint64 with known fields, take 7 LE bytes after the 2-byte header.
    severity, action, longid, shortid, failure, fault_id = 5, 300, 1000, 1500, 12, 2222
    packed = (severity & 0x7) | ((action & 0x1FF) << 3) | ((longid & 0x7FF) << 12) \
        | ((shortid & 0x7FF) << 23) | ((failure & 0x7F) << 35) | ((fault_id & 0xFFFF) << 42)
    body = packed.to_bytes(8, "little")[:7]
    data = bytes([0x21, 0x01]) + body  # type=1 Universal, engine=2, active
    f = parse_fault(data)
    assert f.fault_type == "Universal"
    assert f.engine_position == 2
    assert f.severity == 5
    assert f.failure_type_id == 12
    assert f.fault_id == 2222
    assert f.fault_key == "2222-12"

def test_bad_length_returns_none():
    assert parse_fault(bytes.fromhex("0000")) is None

def test_known_fault_description():
    # 946-6 is a known code (native app: "Emissions Control Fault").
    f = Fault("Universal", 1, True, 946, failure_type_id=6)
    assert f.fault_key == "946-6"
    assert f.description == "Emissions Control Fault"

def test_unknown_fault_description_is_none():
    f = Fault("Legacy", 1, True, 1111)
    assert f.fault_key == "1111-Legacy"
    assert f.description is None

def test_str_includes_description_only_when_known():
    known = Fault("Universal", 1, True, 946, failure_type_id=6)
    assert 'desc="Emissions Control Fault"' in str(known)
    unknown = Fault("Legacy", 1, True, 1111)
    assert "desc=" not in str(unknown)
