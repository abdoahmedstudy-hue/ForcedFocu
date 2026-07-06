import pytest

def test_validate_settings_preserves_defaults(mock_daemon):
    # Pass empty dict
    valid_flag, msg, valid_dict = mock_daemon._validate_settings({})
    
    assert valid_flag is True
    # Check that defaults are merged
    assert "sound_start" in valid_dict
    assert "intent_notification_enabled" in valid_dict
    assert valid_dict["prayer_block_enabled"] is False

def test_validate_settings_type_rejection(mock_daemon):
    valid_flag, msg, valid_dict = mock_daemon._validate_settings({
        "prayer_latitude": "34.05",  # String instead of float
    })
    assert valid_flag is False
    assert "must be a number" in msg

    valid_flag, msg, valid_dict = mock_daemon._validate_settings({
        "intent_notification_interval": "30" # String instead of int
    })
    assert valid_flag is False
    assert "must be an integer" in msg

def test_validate_settings_bounds(mock_daemon):
    valid_flag, msg, valid_dict = mock_daemon._validate_settings({
        "intent_notification_interval": -1 # Too small
    })
    
    assert valid_flag is False
    assert "must be positive" in msg
