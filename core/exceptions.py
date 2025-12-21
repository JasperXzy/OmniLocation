"""Custom exception classes for OmniLocation.

Provides a hierarchical exception structure to distinguish between
user errors, device errors, and system errors.
"""


class OmniLocationError(Exception):
    """Base exception for all OmniLocation errors.
    
    Attributes:
        message: Human-readable error message.
        code: Error code for API responses.
        status_code: HTTP status code.
    """
    
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", status_code: int = 500):
        """Initializes the exception.
        
        Args:
            message: Error description.
            code: Machine-readable error code.
            status_code: HTTP status code for API responses.
        """
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(self.message)
    
    def to_dict(self):
        """Converts exception to dictionary for JSON responses."""
        return {
            'error': self.code,
            'message': self.message,
            'status': self.status_code
        }


# User Input Errors (4xx)
class ValidationError(OmniLocationError):
    """Raised when user input validation fails."""
    
    def __init__(self, message: str, field: str = None):
        self.field = field
        super().__init__(message, code="VALIDATION_ERROR", status_code=400)
    
    def to_dict(self):
        result = super().to_dict()
        if self.field:
            result['field'] = self.field
        return result


class ResourceNotFoundError(OmniLocationError):
    """Raised when a requested resource is not found."""
    
    def __init__(self, resource_type: str, resource_id: str):
        message = f"{resource_type} '{resource_id}' not found"
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(message, code="RESOURCE_NOT_FOUND", status_code=404)


class InvalidFileError(ValidationError):
    """Raised when an uploaded file is invalid."""
    
    def __init__(self, message: str, filename: str = None):
        self.filename = filename
        super().__init__(message, field="file")
        self.code = "INVALID_FILE"
    
    def to_dict(self):
        result = super().to_dict()
        if self.filename:
            result['filename'] = self.filename
        return result


# Device Errors (5xx but user-actionable)
class DeviceError(OmniLocationError):
    """Base class for device-related errors."""
    
    def __init__(self, message: str, device_udid: str = None, code: str = "DEVICE_ERROR"):
        self.device_udid = device_udid
        super().__init__(message, code=code, status_code=500)
    
    def to_dict(self):
        result = super().to_dict()
        if self.device_udid:
            result['device_udid'] = self.device_udid
        return result


class DeviceNotFoundError(DeviceError):
    """Raised when a device cannot be found."""
    
    def __init__(self, device_udid: str):
        message = f"Device {device_udid} not found or disconnected"
        super().__init__(message, device_udid=device_udid, code="DEVICE_NOT_FOUND")
        self.status_code = 404


class DeviceConnectionError(DeviceError):
    """Raised when unable to connect to a device."""
    
    def __init__(self, device_udid: str, reason: str = None):
        message = f"Failed to connect to device {device_udid}"
        if reason:
            message += f": {reason}"
        super().__init__(message, device_udid=device_udid, code="DEVICE_CONNECTION_ERROR")


class DeviceControlError(DeviceError):
    """Raised when unable to control a device (e.g., set location)."""
    
    def __init__(self, device_udid: str, action: str, reason: str = None):
        message = f"Failed to {action} on device {device_udid}"
        if reason:
            message += f": {reason}"
        self.action = action
        super().__init__(message, device_udid=device_udid, code="DEVICE_CONTROL_ERROR")


class NoDevicesAvailableError(DeviceError):
    """Raised when no devices are available for simulation."""
    
    def __init__(self):
        message = "No devices available for simulation. Please connect devices and try again."
        super().__init__(message, code="NO_DEVICES_AVAILABLE")


# GPX/File Processing Errors
class GPXParseError(OmniLocationError):
    """Raised when GPX file parsing fails."""
    
    def __init__(self, filename: str, reason: str = None):
        message = f"Failed to parse GPX file '{filename}'"
        if reason:
            message += f": {reason}"
        self.filename = filename
        super().__init__(message, code="GPX_PARSE_ERROR", status_code=400)


class GPXEmptyError(GPXParseError):
    """Raised when GPX file contains no track points."""
    
    def __init__(self, filename: str):
        message = f"GPX file '{filename}' contains no track points"
        super().__init__(filename, message)
        self.code = "GPX_EMPTY"


# Simulation Errors
class SimulationError(OmniLocationError):
    """Base class for simulation-related errors."""
    
    def __init__(self, message: str, code: str = "SIMULATION_ERROR"):
        super().__init__(message, code=code, status_code=500)


class SimulationAlreadyRunningError(SimulationError):
    """Raised when attempting to start a simulation that's already running."""
    
    def __init__(self):
        message = "Simulation is already running. Stop it before starting a new one."
        super().__init__(message, code="SIMULATION_ALREADY_RUNNING")
        self.status_code = 409  # Conflict


class SimulationNotRunningError(SimulationError):
    """Raised when attempting to stop a simulation that's not running."""
    
    def __init__(self):
        message = "No simulation is currently running"
        super().__init__(message, code="SIMULATION_NOT_RUNNING")
        self.status_code = 400


# Database Errors
class DatabaseError(OmniLocationError):
    """Raised when database operations fail."""
    
    def __init__(self, operation: str, reason: str = None):
        message = f"Database {operation} failed"
        if reason:
            message += f": {reason}"
        self.operation = operation
        super().__init__(message, code="DATABASE_ERROR", status_code=500)


# System Errors (5xx)
class ConfigurationError(OmniLocationError):
    """Raised when system configuration is invalid."""
    
    def __init__(self, message: str, config_key: str = None):
        self.config_key = config_key
        super().__init__(message, code="CONFIGURATION_ERROR", status_code=500)


class ServiceUnavailableError(OmniLocationError):
    """Raised when a required service is unavailable."""
    
    def __init__(self, service_name: str, reason: str = None):
        message = f"Service '{service_name}' is unavailable"
        if reason:
            message += f": {reason}"
        self.service_name = service_name
        super().__init__(message, code="SERVICE_UNAVAILABLE", status_code=503)
