import os
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=True)

    # Mode
    hardware_mode: Literal["mock", "raspberry"] = Field(default="mock")
    camera_mode: Literal["simulation", "usb", "file", "network"] = Field(default="simulation")
    run_mode: Literal["development", "simulation", "raspberry"] = Field(default="simulation")

    # Paths
    intersection_config_path: str = Field(default="config/intersection.json")
    yolo_model_path: str = Field(default="models/yolov8n.pt")
    video_source: str = Field(default="0")

    # Simulation
    simulation_speed: float = Field(default=1.0)
    simulation_spawn_rate: float = Field(default=0.3)

    # Traffic controller
    default_green_duration: int = Field(default=30)
    default_yellow_duration: int = Field(default=3)
    default_red_duration: int = Field(default=30)
    min_green_duration: int = Field(default=10)
    max_green_duration: int = Field(default=60)
    pedestrian_priority_threshold: int = Field(default=5)
    pedestrian_priority_weight: float = Field(default=1.3)

    # YOLO
    yolo_confidence: float = Field(default=0.5)
    yolo_device: str = Field(default="cpu")

    # Camera
    camera_fps: int = Field(default=10)
    camera_width: int = Field(default=640)
    camera_height: int = Field(default=480)

    # Vision
    vision_enabled: bool = Field(default=True)
    vision_config_path: str = Field(default="config/cameras.yaml")
    si_base_url: str = Field(default="http://127.0.0.1:8001")
    vision_push_to_simulation: bool = Field(default=True)

    # CORS
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"])

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
