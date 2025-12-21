"""Test script to verify the unified error handling system.

This script demonstrates how the new exception classes work and can be used
to test API error responses.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.exceptions import (
    ValidationError,
    ResourceNotFoundError,
    InvalidFileError,
    DeviceNotFoundError,
    DeviceConnectionError,
    DeviceControlError,
    NoDevicesAvailableError,
    GPXParseError,
    GPXEmptyError,
    SimulationAlreadyRunningError,
    SimulationNotRunningError,
    DatabaseError,
    ConfigurationError,
)


def test_validation_error():
    """Test ValidationError exception."""
    print("\n=== Testing ValidationError ===")
    try:
        raise ValidationError("Invalid email format", field="email")
    except ValidationError as e:
        print(f"Status Code: {e.status_code}")
        print(f"Error Dict: {e.to_dict()}")


def test_resource_not_found():
    """Test ResourceNotFoundError exception."""
    print("\n=== Testing ResourceNotFoundError ===")
    try:
        raise ResourceNotFoundError("GPX file", "route_test.gpx")
    except ResourceNotFoundError as e:
        print(f"Status Code: {e.status_code}")
        print(f"Error Dict: {e.to_dict()}")


def test_device_errors():
    """Test device-related exceptions."""
    print("\n=== Testing Device Errors ===")
    
    # DeviceNotFoundError
    try:
        raise DeviceNotFoundError("abc123def")
    except DeviceNotFoundError as e:
        print(f"DeviceNotFoundError: {e.to_dict()}")
    
    # DeviceConnectionError
    try:
        raise DeviceConnectionError("abc123def", "Connection timeout")
    except DeviceConnectionError as e:
        print(f"DeviceConnectionError: {e.to_dict()}")
    
    # DeviceControlError
    try:
        raise DeviceControlError("abc123def", "set location", "Service unavailable")
    except DeviceControlError as e:
        print(f"DeviceControlError: {e.to_dict()}")
    
    # NoDevicesAvailableError
    try:
        raise NoDevicesAvailableError()
    except NoDevicesAvailableError as e:
        print(f"NoDevicesAvailableError: {e.to_dict()}")


def test_gpx_errors():
    """Test GPX-related exceptions."""
    print("\n=== Testing GPX Errors ===")
    
    # GPXParseError
    try:
        raise GPXParseError("bad_file.gpx", "Invalid XML format")
    except GPXParseError as e:
        print(f"GPXParseError: {e.to_dict()}")
    
    # GPXEmptyError
    try:
        raise GPXEmptyError("empty_track.gpx")
    except GPXEmptyError as e:
        print(f"GPXEmptyError: {e.to_dict()}")


def test_simulation_errors():
    """Test simulation-related exceptions."""
    print("\n=== Testing Simulation Errors ===")
    
    # SimulationAlreadyRunningError
    try:
        raise SimulationAlreadyRunningError()
    except SimulationAlreadyRunningError as e:
        print(f"SimulationAlreadyRunningError: {e.to_dict()}")
    
    # SimulationNotRunningError
    try:
        raise SimulationNotRunningError()
    except SimulationNotRunningError as e:
        print(f"SimulationNotRunningError: {e.to_dict()}")


def test_system_errors():
    """Test system-level exceptions."""
    print("\n=== Testing System Errors ===")
    
    # DatabaseError
    try:
        raise DatabaseError("connection", "Unable to connect to SQLite database")
    except DatabaseError as e:
        print(f"DatabaseError: {e.to_dict()}")
    
    # ConfigurationError
    try:
        raise ConfigurationError("Missing API key: TIANDITU_KEY", config_key="TIANDITU_KEY")
    except ConfigurationError as e:
        print(f"ConfigurationError: {e.to_dict()}")


def main():
    """Run all error handling tests."""
    print("=" * 60)
    print("OmniLocation Error Handling System Test")
    print("=" * 60)
    
    test_validation_error()
    test_resource_not_found()
    test_device_errors()
    test_gpx_errors()
    test_simulation_errors()
    test_system_errors()
    
    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
