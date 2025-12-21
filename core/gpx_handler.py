"""Handles parsing of GPX files for location simulation."""

import logging
from pathlib import Path
from typing import Any, Dict, List, TypedDict

import gpxpy

from core.exceptions import GPXParseError, GPXEmptyError

logger = logging.getLogger(__name__)


class TrackPoint(TypedDict):
    """Represents a single GPS track point."""
    lat: float
    lon: float
    ele: float
    time: Any  # datetime object


class GPXData(TypedDict):
    """Represents parsed GPX data with metadata."""
    points: List[TrackPoint]
    total_distance: float  # in meters
    total_duration: float  # in seconds


class GPXHandler:
    """Parses GPX files to extract track points and metadata.

    Attributes:
        file_path: A Path object pointing to the GPX file.
    """

    def __init__(self, file_path: str) -> None:
        """Initializes the GPXHandler with a file path.

        Args:
            file_path: The string path to the .gpx file.
        """
        self.file_path = Path(file_path)

    def parse(self) -> GPXData:
        """Parses the GPX file and extracts track points and metadata.

        Returns:
            A dictionary containing:
            - points: List of track points.
            - total_distance: Total track length in meters.
            - total_duration: Total duration in seconds.

        Raises:
            GPXParseError: If the GPX file cannot be parsed.
            GPXEmptyError: If the GPX file contains no track points.
        """
        logger.info("Parsing GPX file: %s", self.file_path)
        
        if not self.file_path.exists():
            raise GPXParseError(str(self.file_path), "File not found")
        
        points: List[TrackPoint] = []
        try:
            with self.file_path.open('r', encoding='utf-8') as gpx_file:
                gpx = gpxpy.parse(gpx_file)

                # 1. Extract Metadata using gpxpy's built-in methods
                total_distance = gpx.length_2d()  # Meters
                total_duration = gpx.get_duration() or 0.0  # Seconds

                # 2. Extract Points
                for track in gpx.tracks:
                    for segment in track.segments:
                        for point in segment.points:
                            points.append({
                                'lat': point.latitude,
                                'lon': point.longitude,
                                'ele': point.elevation,
                                'time': point.time
                            })

            if not points:
                logger.warning("No track points found in %s", self.file_path)
                raise GPXEmptyError(str(self.file_path))
            
            logger.info(
                "Loaded %d points. Dist: %.2fm, Dur: %.2fs",
                len(points), total_distance, total_duration
            )

            return {
                "points": points,
                "total_distance": total_distance,
                "total_duration": total_duration
            }

        except (GPXParseError, GPXEmptyError):
            raise
        except gpxpy.gpx.GPXException as e:
            logger.error("Invalid GPX format: %s", e)
            raise GPXParseError(str(self.file_path), f"Invalid GPX format: {str(e)}")
        except Exception as e:
            logger.error("Error parsing GPX file: %s", e)
            raise GPXParseError(str(self.file_path), str(e))
            raise
