import logging
from typing import Dict
from .base import HardwareInterface

logger = logging.getLogger(__name__)


class RaspberryPiGPIO(HardwareInterface):
    """Real GPIO implementation for Raspberry Pi.

    Pin mapping is loaded from config — never hardcoded here.
    """

    def __init__(self, pin_config: Dict[str, Dict[str, int]]):
        """
        pin_config: {
            "TL-01": {"red": 17, "yellow": 27, "green": 22},
            ...
        }
        """
        self._pin_config = pin_config
        self._gpio = None

    def initialize(self) -> None:
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for light_id, pins in self._pin_config.items():
                for color, pin in pins.items():
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            logger.info(f"RaspberryPiGPIO initialized with {len(self._pin_config)} lights")
        except ImportError:
            raise RuntimeError("RPi.GPIO not available. Use MockGPIO on non-Raspberry Pi systems.")

    def set_light(self, light_id: str, red: bool, yellow: bool, green: bool) -> None:
        if self._gpio is None:
            raise RuntimeError("GPIO not initialized")
        pins = self._pin_config.get(light_id)
        if not pins:
            logger.warning(f"No pin config for light {light_id}")
            return
        self._gpio.output(pins["red"], self._gpio.HIGH if red else self._gpio.LOW)
        self._gpio.output(pins["yellow"], self._gpio.HIGH if yellow else self._gpio.LOW)
        self._gpio.output(pins["green"], self._gpio.HIGH if green else self._gpio.LOW)

    def get_light_state(self, light_id: str) -> Dict[str, bool]:
        if self._gpio is None:
            return {"red": False, "yellow": False, "green": False}
        pins = self._pin_config.get(light_id, {})
        return {
            "red": bool(self._gpio.input(pins.get("red", 0))) if "red" in pins else False,
            "yellow": bool(self._gpio.input(pins.get("yellow", 0))) if "yellow" in pins else False,
            "green": bool(self._gpio.input(pins.get("green", 0))) if "green" in pins else False,
        }

    def cleanup(self) -> None:
        if self._gpio:
            self._gpio.cleanup()
            logger.info("RaspberryPiGPIO cleaned up")
