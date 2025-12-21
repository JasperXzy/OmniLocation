"""Flask application factory for the OmniLocation Web UI."""

import asyncio
import logging
import os
from typing import Any, Dict, List

from flask import Flask, Response, current_app, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.utils import secure_filename

from core.device_manager import DevicePool
from core.exceptions import (
    OmniLocationError,
    ValidationError,
    ResourceNotFoundError,
    InvalidFileError,
    GPXParseError,
)
from core.gpx_handler import GPXHandler
from core.simulator import Simulator

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'gpx'}

logger = logging.getLogger(__name__)


def allowed_file(filename: str) -> bool:
    """Checks if the file extension is allowed.

    Args:
        filename: The name of the file.

    Returns:
        True if the file extension is 'gpx'.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app(
    device_pool: DevicePool,
    simulator: Simulator,
    background_loop: asyncio.AbstractEventLoop,
) -> Flask:
    """Creates and configures the Flask application.

    Args:
        device_pool: The shared DevicePool instance.
        simulator: The shared Simulator instance.
        background_loop: The asyncio loop running in the background thread.

    Returns:
        The configured Flask application instance.
    """
    app = Flask(__name__, static_folder='static', static_url_path='')
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

    # Ensure upload folder exists
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # Store references
    # Note: Storing objects on 'app' is a common Flask pattern for simple DI.
    app.device_pool = device_pool  # type: ignore
    app.simulator = simulator      # type: ignore
    app.bg_loop = background_loop  # type: ignore

    # Error Handlers
    @app.errorhandler(OmniLocationError)
    def handle_omnilocation_error(error: OmniLocationError) -> tuple:
        """Handles all custom OmniLocation exceptions."""
        logger.warning("OmniLocation error: %s [%s]", error.message, error.code)
        return jsonify(error.to_dict()), error.status_code
    
    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(error: RequestEntityTooLarge) -> tuple:
        """Handles file upload size limit exceeded."""
        return jsonify({
            'error': 'FILE_TOO_LARGE',
            'message': 'File size exceeds 16MB limit',
            'status': 413
        }), 413
    
    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException) -> tuple:
        """Handles standard HTTP exceptions."""
        return jsonify({
            'error': error.name.upper().replace(' ', '_'),
            'message': error.description,
            'status': error.code
        }), error.code or 500
    
    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> tuple:
        """Handles all unexpected errors."""
        logger.exception("Unexpected error: %s", str(error))
        return jsonify({
            'error': 'INTERNAL_SERVER_ERROR',
            'message': 'An unexpected error occurred. Please try again later.',
            'status': 500
        }), 500

    # Routes
    @app.route('/')
    def index() -> str:
        """Renders the main dashboard page."""
        tianditu_key = os.getenv("TIANDITU_KEY", "")
        return render_template('index.html', tianditu_key=tianditu_key)

    @app.route('/api/devices', methods=['GET'])
    def list_devices() -> Response:
        """API endpoint to list connected devices.

        Triggers a device scan before returning the list.

        Returns:
            JSON response containing a list of device details.
        """
        # Trigger a scan first
        devices = current_app.device_pool.scan_usb_devices()  # type: ignore
        dev_list: List[Dict[str, Any]] = []
        for d in devices:
            # Determine device type
            device_type = 'iOS' if d.__class__.__name__ == 'IOSDevice' else 'Android'
            dev_list.append({
                'udid': d.udid,
                'name': d.name,
                'real_name': d.real_name,
                'device_type': device_type,
                'connection_type': d.connection_type,
                'connected': d.connected
            })
        return jsonify(dev_list)

    @app.route('/api/devices/rename', methods=['POST'])
    def rename_device() -> Any:
        """API endpoint to rename a device.

        Expects JSON payload with 'udid' and 'name'.
        """
        data = request.json
        if not data:
            raise ValidationError('Request body must be valid JSON')

        udid = data.get('udid')
        new_name = data.get('name')

        if not udid:
            raise ValidationError('Missing required field: udid', field='udid')
        if not new_name:
            raise ValidationError('Missing required field: name', field='name')

        success = current_app.device_pool.rename_device(udid, new_name)  # type: ignore
        if success:
            return jsonify({'message': 'Device renamed successfully'})
        else:
            raise ResourceNotFoundError('Device', udid)

    @app.route('/api/upload', methods=['POST'])
    def upload_file() -> Any:
        """API endpoint to handle GPX file uploads.

        Returns:
            JSON response indicating success or failure.
        """
        if 'file' not in request.files:
            raise ValidationError('No file provided in request', field='file')
        
        file = request.files['file']
        if file.filename == '':
            raise ValidationError('No file selected', field='file')
        
        if not file or not file.filename:
            raise InvalidFileError('Invalid file upload')
        
        if not allowed_file(file.filename):
            raise InvalidFileError('Only .gpx files are allowed', filename=file.filename)
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(filepath)
        except Exception as e:
            logger.error("Failed to save file %s: %s", filename, e)
            raise InvalidFileError(f'Failed to save file: {str(e)}', filename=filename)
        
        return jsonify({
            'message': 'File uploaded successfully',
            'filename': filename
        })

    @app.route('/api/gpx_files', methods=['GET'])
    def list_gpx_files() -> Response:
        """API endpoint to list available GPX files.

        Returns:
            JSON list of filenames.
        """
        files: List[str] = []
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            files = [
                f for f in os.listdir(app.config['UPLOAD_FOLDER'])
                if f.endswith('.gpx')
            ]
        return jsonify(files)

    @app.route('/api/gpx_files/<filename>', methods=['DELETE'])
    def delete_gpx_file(filename: str) -> Response:
        """API endpoint to delete a GPX file.

        Args:
            filename: The GPX file to delete.

        Returns:
            JSON response with success status.
        """
        filename = secure_filename(filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            raise ResourceNotFoundError('GPX file', filename)
        
        try:
            os.remove(filepath)
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        except Exception as e:
            logger.error("Failed to delete file %s: %s", filename, e)
            raise InvalidFileError(f'Failed to delete file: {str(e)}', filename=filename)

    @app.route('/api/gpx_files/<filename>/details', methods=['GET'])
    def get_gpx_details(filename: str) -> Response:
        """API endpoint to get metadata for a specific GPX file.

        Returns:
            JSON containing total_distance (m), total_duration (s), and points list.
        """
        filename = secure_filename(filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            raise ResourceNotFoundError('GPX file', filename)

        try:
            handler = GPXHandler(filepath)
            data = handler.parse()
            
            # Serialize points: Convert datetime objects to ISO strings
            serialized_points = []
            for p in data['points']:
                point_dict = p.copy()
                if point_dict.get('time'):
                    point_dict['time'] = point_dict['time'].isoformat()
                serialized_points.append(point_dict)

            return jsonify({
                'filename': filename,
                'total_distance': data['total_distance'],
                'total_duration': data['total_duration'],
                'point_count': len(data['points']),
                'points': serialized_points
            })
        except Exception as e:
            logger.error("Failed to parse GPX file %s: %s", filename, e)
            raise GPXParseError(filename, str(e))

    @app.route('/api/start', methods=['POST'])
    def start_simulation() -> Any:
        """API endpoint to start the simulation.

        Expects JSON payload with 'filename', 'udids', 'loop'.
        Optional: 'speed' (multiplier) OR 'target_duration' (seconds).
        """
        data = request.json
        if not data:
            raise ValidationError('Request body must be valid JSON')

        filename = data.get('filename')
        udids = data.get('udids', [])
        loop = data.get('loop', False)
        
        # Speed control logic
        speed_multiplier = float(data.get('speed', 1.0))
        target_duration = data.get('target_duration')  # Optional, in seconds

        if not filename:
            raise ValidationError('Missing required field: filename', field='filename')
        if not udids:
            raise ValidationError('No devices selected for simulation', field='udids')

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(filepath):
            raise ResourceNotFoundError('GPX file', filename)

        # Parse GPX
        try:
            handler = GPXHandler(filepath)
            gpx_data = handler.parse()
            points = gpx_data['points']
            original_duration = gpx_data['total_duration']
            
            # Recalculate speed if target_duration is provided
            if target_duration is not None:
                target_duration = float(target_duration)
                if target_duration > 0 and original_duration > 0:
                    speed_multiplier = original_duration / target_duration
                    logger.info("Calculated speed %.2f based on target duration %.2fs", 
                                speed_multiplier, target_duration)

        except Exception as e:
            logger.error("Failed to parse GPX: %s", e)
            raise GPXParseError(filename, str(e))

        # Run start in background loop
        async def schedule_start() -> None:
            await current_app.simulator.start(  # type: ignore
                points, udids, loop_track=loop, speed_multiplier=speed_multiplier
            )

        asyncio.run_coroutine_threadsafe(
            schedule_start(),
            current_app.bg_loop  # type: ignore
        )

        return jsonify({
            'message': 'Simulation started',
            'device_count': len(udids),
            'speed_multiplier': speed_multiplier
        })

    @app.route('/api/stop', methods=['POST'])
    def stop_simulation() -> Response:
        """API endpoint to stop (pause) the simulation."""
        async def schedule_stop() -> None:
            await current_app.simulator.stop()  # type: ignore
        
        asyncio.run_coroutine_threadsafe(
            schedule_stop(),
            current_app.bg_loop  # type: ignore
        )
        return jsonify({'message': 'Simulation paused'})

    @app.route('/api/reset', methods=['POST'])
    def reset_simulation() -> Response:
        """API endpoint to reset the simulation and clear device location."""
        async def schedule_reset() -> None:
            await current_app.simulator.reset()  # type: ignore
        
        asyncio.run_coroutine_threadsafe(
            schedule_reset(),
            current_app.bg_loop  # type: ignore
        )
        return jsonify({'message': 'Simulation reset and location cleared'})

    @app.route('/api/status', methods=['GET'])
    def get_status() -> Response:
        """API endpoint to get real-time simulation status."""
        return jsonify(current_app.simulator.status)  # type: ignore

    return app
