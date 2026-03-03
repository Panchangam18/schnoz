"""Kalman + EMA smoother for nose tracking."""

from __future__ import annotations

import cv2
import numpy as np


def make_kalman(
    process_var: float = 15.0,
    measurement_var: float = 5.0,
) -> cv2.KalmanFilter:
    state_dim, meas_dim, dt = 4, 2, 1.0
    kf = cv2.KalmanFilter(state_dim, meas_dim)

    kf.transitionMatrix = np.array(
        [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32,
    )
    kf.measurementMatrix = np.array(
        [[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32,
    )
    kf.processNoiseCov = np.eye(state_dim, dtype=np.float32) * process_var
    kf.measurementNoiseCov = np.eye(meas_dim, dtype=np.float32) * measurement_var
    kf.errorCovPost = np.eye(state_dim, dtype=np.float32)
    kf.statePre = np.zeros((state_dim, 1), np.float32)
    kf.statePost = np.zeros((state_dim, 1), np.float32)

    return kf


class KalmanEMASmoother:

    def __init__(self, kf: cv2.KalmanFilter | None = None, ema_alpha: float = 0.4):
        self.kf = kf if isinstance(kf, cv2.KalmanFilter) else make_kalman()
        if not 0.0 <= ema_alpha <= 1.0:
            raise ValueError(f"ema_alpha must be in [0.0, 1.0], got {ema_alpha}")
        self.ema_alpha = float(ema_alpha)
        self.ema_x: float | None = None
        self.ema_y: float | None = None

    def step(self, x: int, y: int) -> tuple[int, int]:
        meas = np.array([[float(x)], [float(y)]], dtype=np.float32)

        # Initialize state on first call
        if not np.any(self.kf.statePost):
            self.kf.statePre[:2] = meas
            self.kf.statePost[:2] = meas

        pred = self.kf.predict()
        self.kf.correct(meas)
        kx, ky = int(pred[0, 0]), int(pred[1, 0])

        # EMA on top of Kalman
        a = self.ema_alpha
        if a == 0.0:
            return kx, ky

        if self.ema_x is None or self.ema_y is None:
            self.ema_x = float(kx)
            self.ema_y = float(ky)
        else:
            self.ema_x = a * self.ema_x + (1.0 - a) * float(kx)
            self.ema_y = a * self.ema_y + (1.0 - a) * float(ky)

        return int(self.ema_x), int(self.ema_y)
