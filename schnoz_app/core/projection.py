"""NoseProjector: calibration-free nose ray-casting to screen coordinates."""

from __future__ import annotations

import math


class NoseProjector:
    """
    Maps nose position + head orientation to screen coordinates by
    ray-casting through a virtual screen plane. No calibration needed.
    """

    def __init__(
        self,
        screen_w: int,
        screen_h: int,
        cam_w: int = 640,
        cam_h: int = 480,
        sensitivity: float = 1.5,
        position_scale: float = 2.0,
    ):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.cam_w = cam_w
        self.cam_h = cam_h
        self.sensitivity = sensitivity
        self.position_scale = position_scale

    def project(
        self,
        raw_nose_x: float,
        raw_nose_y: float,
        yaw: float,
        pitch: float,
    ) -> tuple[float, float]:
        """Project nose ray onto screen plane."""
        nx = (raw_nose_x / self.cam_w) - 0.5
        ny = (raw_nose_y / self.cam_h) - 0.5

        pos_scale = self.position_scale * self.screen_w
        head_x = self.screen_w / 2 - nx * pos_scale
        head_y = self.screen_h / 2 + ny * pos_scale

        scale = self.sensitivity * self.screen_w
        offset_x = math.tan(pitch) * scale
        offset_y = math.tan(yaw) * scale

        cx = head_x + offset_x
        cy = head_y + offset_y

        cx = max(0.0, min(float(self.screen_w), cx))
        cy = max(0.0, min(float(self.screen_h), cy))

        return cx, cy
