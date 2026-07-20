"""Tests for the notification policy (quiet-by-default with a critical allowlist)."""

from vvm_to_signalk import notification_policy as np


def test_method_by_state_mapping():
    assert np.METHOD_BY_STATE["alarm"] == ["visual", "sound"]
    assert np.METHOD_BY_STATE["alert"] == ["visual"]
    assert np.METHOD_BY_STATE["warn"] == ["visual"]
    assert np.METHOD_BY_STATE["normal"] == []


def test_method_for_returns_fresh_copy():
    a = np.method_for("alarm")
    a.append("mutated")
    assert np.method_for("alarm") == ["visual", "sound"]  # not mutated


def test_method_for_unknown_state_is_empty():
    assert np.method_for("bogus") == []


def test_inactive_is_always_normal():
    assert np.state_for("guardian", "GC_CHI", False) == "normal"
    assert np.state_for("bitfield", "Oil Fault", False) == "normal"
    assert np.state_for("fault", "946-6", False) == "normal"


def test_active_critical_guardian_is_alarm():
    assert np.state_for("guardian", "GC_CHI", True) == "alarm"
    assert np.state_for("guardian", "GC_LOW_OIL", True) == "alarm"


def test_active_noncritical_guardian_is_alert():
    assert np.state_for("guardian", "GC_BREAKIN", True) == "alert"


def test_active_critical_bitfield_is_alarm():
    assert np.state_for("bitfield", "Coolant Temperature Fault", True) == "alarm"


def test_active_noncritical_bitfield_is_alert():
    assert np.state_for("bitfield", "Guardian/Check Engine", True) == "alert"


def test_faults_policy_by_allowlist():
    # Non-critical / unknown fault keys stay silent alert when active.
    assert np.state_for("fault", "1111-Legacy", True) == "alert"
    assert np.state_for("fault", "946-6", True) == "alert"
    # Seeded critical codes are audible alarms.
    assert np.state_for("fault", "1109-23", True) == "alarm"
    assert np.state_for("fault", "4602-23", True) == "alarm"


def test_mil_kind_is_alert_when_active():
    assert np.state_for("mil", "MIL Constant On", True) == "alert"


def test_unknown_kind_is_alert_when_active():
    assert np.state_for("bogus", "whatever", True) == "alert"
