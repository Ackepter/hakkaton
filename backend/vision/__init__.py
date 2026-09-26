"""Computer-vision subsystem: camera sources -> detectors -> traffic analysis -> pipeline (independent of GPIO and the controller)."""
from .analysis import CentroidTracker, TrafficAnalyzer, TrafficSnapshot, perception_payload, to_traffic_data
from .config import CameraConfig, Zone, load_cameras
from .detectors import Detector, NullDetector, VirtualDetector, YoloDetector
from .pipeline import CameraPipeline, VisionManager, build_manager
from .sources import CameraSource, discover_usb_cameras
from .types import CameraError, Detection, DetectorUnavailable, Frame

__all__ = [
    "CameraConfig", "Zone", "load_cameras", "CameraSource", "discover_usb_cameras", "Detector", "VirtualDetector",
    "YoloDetector", "NullDetector", "CentroidTracker", "TrafficAnalyzer", "TrafficSnapshot", "perception_payload",
    "to_traffic_data", "CameraPipeline", "VisionManager", "build_manager", "Detection", "Frame", "CameraError",
    "DetectorUnavailable",
]
