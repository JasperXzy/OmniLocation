"""GPX file upload, listing, and inspection endpoints."""

import logging
import os
import shutil
from typing import Any, Dict

from fastapi import APIRouter, File, UploadFile

from core.exceptions import (
    GPXParseError,
    InvalidFileError,
    ResourceNotFoundError,
    ValidationError,
)
from core.gpx_handler import GPXHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["gpx"])

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'gpx'}


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _safe_path(filename: str) -> str:
    return os.path.join(UPLOAD_FOLDER, os.path.basename(filename))


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handles GPX file uploads."""
    if not file.filename:
        raise ValidationError('No file selected', field='file')

    if not _allowed_file(file.filename):
        raise InvalidFileError('Only .gpx files are allowed', filename=file.filename)

    filename = os.path.basename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    try:
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error("Failed to save file %s: %s", filename, e)
        raise InvalidFileError(f'Failed to save file: {str(e)}', filename=filename)

    return {'message': 'File uploaded successfully', 'filename': filename}


@router.get("/gpx_files")
async def list_gpx_files():
    """Lists available GPX files with metadata in a single response."""
    if not os.path.exists(UPLOAD_FOLDER):
        return []

    results = []
    for filename in sorted(os.listdir(UPLOAD_FOLDER)):
        if not filename.endswith('.gpx'):
            continue
        entry: Dict[str, Any] = {'filename': filename}
        try:
            handler = GPXHandler(os.path.join(UPLOAD_FOLDER, filename))
            data = handler.parse()
            entry.update({
                'total_distance': data['total_distance'],
                'total_duration': data['total_duration'],
                'point_count': len(data['points']),
            })
        except Exception as e:
            logger.warning("Failed to parse GPX %s: %s", filename, e)
            entry['error'] = str(e)
        results.append(entry)
    return results


@router.delete("/gpx_files/{filename}")
async def delete_gpx_file(filename: str):
    """Deletes a GPX file."""
    filepath = _safe_path(filename)

    if not os.path.exists(filepath):
        raise ResourceNotFoundError('GPX file', filename)

    try:
        os.remove(filepath)
        return {'success': True, 'message': f'Deleted {os.path.basename(filename)}'}
    except Exception as e:
        logger.error("Failed to delete file %s: %s", filename, e)
        raise InvalidFileError(f'Failed to delete file: {str(e)}', filename=filename)


@router.get("/gpx_files/{filename}/details")
async def get_gpx_details(filename: str):
    """Gets metadata + points for a specific GPX file."""
    filepath = _safe_path(filename)

    if not os.path.exists(filepath):
        raise ResourceNotFoundError('GPX file', filename)

    try:
        handler = GPXHandler(filepath)
        data = handler.parse()

        serialized_points = []
        for p in data['points']:
            point_dict = p.copy()
            if point_dict.get('time'):
                point_dict['time'] = point_dict['time'].isoformat()
            serialized_points.append(point_dict)

        return {
            'filename': os.path.basename(filename),
            'total_distance': data['total_distance'],
            'total_duration': data['total_duration'],
            'point_count': len(data['points']),
            'points': serialized_points,
        }
    except Exception as e:
        logger.error("Failed to parse GPX file %s: %s", filename, e)
        raise GPXParseError(filename, str(e))
