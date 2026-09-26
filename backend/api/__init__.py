from .routes_intersection import router as intersection_router
from .routes_lights import router as lights_router
from .routes_control import router as control_router
from .routes_metrics import router as metrics_router
from .routes_vision import router as vision_router

__all__ = ["intersection_router", "lights_router", "control_router", "metrics_router", "vision_router"]
