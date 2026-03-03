"""NoseFeatureExtractor: MediaPipe face landmarker → nose feature vector.

Adapted from schnoz/feature_extractor.py with squint calibration/detection removed.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from collections import deque, namedtuple
from pathlib import Path

import cv2
import numpy as np

NosePose = namedtuple("NosePose", ["raw_nose_x", "raw_nose_y", "yaw", "pitch", "double_blink"])

# --- Nose landmarks ---
NOSE_TIP = 1
NOSE_BRIDGE_TOP = 6
NOSE_LEFT_ALAR = 98
NOSE_RIGHT_ALAR = 327

# --- Scaffold landmarks (blink-immune rigid face structure) ---
SCAFFOLD_INDICES = [
    234,   # left ear tragus
    454,   # right ear tragus
    10,    # forehead / top of head
    152,   # chin
    127,   # left cheekbone
    356,   # right cheekbone
    93,    # left jaw (mid)
    323,   # right jaw (mid)
    175,   # lower chin edge
    151,   # upper chin / mentalis
]

# --- Eye landmarks for blink detection (EAR method) ---
LEFT_EYE_INNER = 133
LEFT_EYE_OUTER = 33
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145
RIGHT_EYE_INNER = 362
RIGHT_EYE_OUTER = 263
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374

_DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)


def _download_model(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "schnoz"})
        with urllib.request.urlopen(req, timeout=30) as resp, tmp.open("wb") as fh:
            total = resp.headers.get("Content-Length")
            total_i = int(total) if total and total.isdigit() else None
            downloaded = 0
            last_report = 0.0
            start = time.time()
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if sys.stderr.isatty() and now - last_report >= 0.2:
                    last_report = now
                    if total_i:
                        pct = 100.0 * (downloaded / max(total_i, 1))
                        sys.stderr.write(
                            f"\r[schnoz] Downloading FaceLandmarker model: "
                            f"{pct:5.1f}% ({downloaded / 1e6:.1f}/{total_i / 1e6:.1f} MB)"
                        )
                    else:
                        sys.stderr.write(
                            f"\r[schnoz] Downloading FaceLandmarker model: "
                            f"{downloaded / 1e6:.1f} MB"
                        )
                    sys.stderr.flush()
            if sys.stderr.isatty():
                dur = time.time() - start
                sys.stderr.write(
                    f"\r[schnoz] Downloaded FaceLandmarker model "
                    f"({downloaded / 1e6:.1f} MB) in {dur:.1f}s\n"
                )
                sys.stderr.flush()
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)


def _ensure_model(model_path: str | os.PathLike[str] | None) -> Path:
    if model_path:
        p = Path(model_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"FaceLandmarker model not found: {p}")
        return p

    env = os.environ.get("SCHNOZ_FACE_LANDMARKER_MODEL")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(
                f"SCHNOZ_FACE_LANDMARKER_MODEL points to missing file: {p}"
            )
        return p

    cache_path = (
        Path.home() / ".cache" / "schnoz" / "mediapipe" / "face_landmarker.task"
    )
    if cache_path.exists():
        return cache_path

    print(
        f"[schnoz] FaceLandmarker model missing; downloading to {cache_path}",
        file=sys.stderr,
    )
    _download_model(_DEFAULT_MODEL_URL, cache_path)
    return cache_path


def _create_face_landmarker(*, model_path: str | os.PathLike[str] | None):
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions

    task_path = _ensure_model(model_path)
    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(task_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )
    return mp, vision.FaceLandmarker.create_from_options(options)


class NoseFeatureExtractor:
    """
    Extracts nose-tracking features from webcam frames via MediaPipe.

    Uses a median centroid of 10 rigid-structure scaffold landmarks for
    normalization. Includes blink detection via EAR and double-blink
    detection for clicking.
    """

    def __init__(
        self,
        face_landmarker_model: str | os.PathLike[str] | None = None,
        ear_history_len: int = 50,
        blink_threshold_ratio: float = 0.75,
        min_history: int = 15,
    ):
        self._mp, self._face_landmarker = _create_face_landmarker(
            model_path=face_landmarker_model,
        )
        self._mp_last_ts_ms = 0

        # Blink detection state
        self._ear_history: deque[float] = deque(maxlen=ear_history_len)
        self._blink_ratio = blink_threshold_ratio
        self._min_history = min_history

        # Double-blink detection
        self._was_blinking = False
        self._blink_end_times: list[float] = []
        self._last_double_blink_time = 0.0

    def _compute_ear(self, all_points: np.ndarray) -> float:
        """Compute Eye Aspect Ratio (EAR) from face landmarks."""
        left_inner = all_points[LEFT_EYE_INNER, :2]
        left_outer = all_points[LEFT_EYE_OUTER, :2]
        left_top = all_points[LEFT_EYE_TOP, :2]
        left_bottom = all_points[LEFT_EYE_BOTTOM, :2]

        right_inner = all_points[RIGHT_EYE_INNER, :2]
        right_outer = all_points[RIGHT_EYE_OUTER, :2]
        right_top = all_points[RIGHT_EYE_TOP, :2]
        right_bottom = all_points[RIGHT_EYE_BOTTOM, :2]

        left_w = np.linalg.norm(left_outer - left_inner)
        left_h = np.linalg.norm(left_top - left_bottom)
        left_ear = left_h / (left_w + 1e-9)

        right_w = np.linalg.norm(right_outer - right_inner)
        right_h = np.linalg.norm(right_top - right_bottom)
        right_ear = right_h / (right_w + 1e-9)

        return (left_ear + right_ear) / 2.0

    def _detect_blink(self, all_points: np.ndarray) -> bool:
        """Detect blinks using Eye Aspect Ratio (EAR)."""
        ear = self._compute_ear(all_points)
        self._ear_history.append(ear)

        if len(self._ear_history) >= self._min_history:
            threshold = float(np.mean(self._ear_history)) * self._blink_ratio
        else:
            threshold = 0.2

        return ear < threshold

    def _detect_double_blink(self, is_blinking: bool) -> bool:
        """Detect double-blink pattern from blink timing."""
        now = time.time()

        # Detect blink-end (was blinking, now not)
        if self._was_blinking and not is_blinking:
            self._blink_end_times.append(now)
        self._was_blinking = is_blinking

        # Prune old timestamps
        self._blink_end_times = [t for t in self._blink_end_times if now - t < 0.8]

        # Two blink-ends within 600ms = double blink (with 1s cooldown)
        if len(self._blink_end_times) >= 2 and now - self._last_double_blink_time > 1.0:
            gap = self._blink_end_times[-1] - self._blink_end_times[-2]
            if gap < 0.6:
                self._last_double_blink_time = now
                self._blink_end_times.clear()
                return True
        return False

    def extract_features(self, image: np.ndarray) -> tuple[np.ndarray | None, bool]:
        """
        Extract nose features from a BGR image.

        Returns:
            (feature_vector, is_blinking)
            feature_vector is None if no face is detected.
        """
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image_rgb = np.ascontiguousarray(image_rgb)
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=image_rgb,
        )

        ts_ms = int(time.time() * 1000)
        if ts_ms <= self._mp_last_ts_ms:
            ts_ms = self._mp_last_ts_ms + 1
        self._mp_last_ts_ms = ts_ms

        result = self._face_landmarker.detect_for_video(mp_image, ts_ms)
        if not result.face_landmarks:
            return None, False

        landmarks = result.face_landmarks[0]
        h, w = image.shape[:2]

        all_points = np.array(
            [(lm.x, lm.y, lm.z) for lm in landmarks], dtype=np.float32,
        )

        is_blinking = self._detect_blink(all_points)

        # --- Scaffold centroid (median of 10 rigid face-structure points) ---
        scaffold_pts = all_points[SCAFFOLD_INDICES]
        centroid = np.median(scaffold_pts, axis=0)

        # --- Orthonormal basis from scaffold ---
        left_ear = all_points[SCAFFOLD_INDICES[0]]
        right_ear = all_points[SCAFFOLD_INDICES[1]]
        forehead = all_points[SCAFFOLD_INDICES[2]]

        x_axis = right_ear - left_ear
        x_axis /= np.linalg.norm(x_axis) + 1e-9

        y_approx = forehead - centroid
        y_approx /= np.linalg.norm(y_approx) + 1e-9
        y_axis = y_approx - np.dot(y_approx, x_axis) * x_axis
        y_axis /= np.linalg.norm(y_axis) + 1e-9

        z_axis = np.cross(x_axis, y_axis)
        z_axis /= np.linalg.norm(z_axis) + 1e-9

        R = np.column_stack((x_axis, y_axis, z_axis))

        # --- Scale factor ---
        scaffold_shifted = scaffold_pts - centroid
        scaffold_dists = np.linalg.norm(scaffold_shifted, axis=1)
        scale = np.median(scaffold_dists)
        if scale < 1e-7:
            scale = 1.0

        # --- Nose landmarks in normalized scaffold space ---
        nose_tip = all_points[NOSE_TIP]
        nose_bridge = all_points[NOSE_BRIDGE_TOP]
        nose_left = all_points[NOSE_LEFT_ALAR]
        nose_right = all_points[NOSE_RIGHT_ALAR]

        def to_norm(pt):
            return (R.T @ (pt - centroid)) / scale

        tip_norm = to_norm(nose_tip)
        left_alar_norm = to_norm(nose_left)
        right_alar_norm = to_norm(nose_right)

        bridge_norm = to_norm(nose_bridge)
        bridge_vec = tip_norm - bridge_norm
        bridge_vec = bridge_vec / (np.linalg.norm(bridge_vec) + 1e-9)

        # --- Head pose from rotation matrix ---
        yaw = np.arctan2(R[1, 0], R[0, 0])
        pitch = np.arctan2(-R[2, 0], np.sqrt(R[2, 1] ** 2 + R[2, 2] ** 2))
        roll = np.arctan2(R[2, 1], R[2, 2])

        # --- Raw pixel positions ---
        raw_nose_x = nose_tip[0] * w
        raw_nose_y = nose_tip[1] * h
        raw_centroid_x = centroid[0] * w
        raw_centroid_y = centroid[1] * h

        # --- Triangulation ---
        nose_to_scaffold = np.linalg.norm(
            scaffold_pts - nose_tip, axis=1,
        ) / scale

        scale_px = scale * w

        features = np.concatenate([
            tip_norm,                          # 3
            left_alar_norm,                    # 3
            right_alar_norm,                   # 3
            bridge_vec,                        # 3
            [yaw, pitch, roll],                # 3
            [raw_nose_x, raw_nose_y],          # 2
            [raw_centroid_x, raw_centroid_y],   # 2
            nose_to_scaffold,                  # 10
            [scale_px],                        # 1
        ])                                     # total: 30

        return features, is_blinking

    def extract_pose(self, image: np.ndarray) -> tuple[NosePose | None, bool]:
        """
        Extract lightweight pose data needed for projection.

        Returns:
            (NosePose, is_blinking) or (None, is_blinking) if no face detected.
        """
        features, is_blinking = self.extract_features(image)
        if features is None:
            double_blink = self._detect_double_blink(is_blinking)
            return None, is_blinking

        double_blink = self._detect_double_blink(is_blinking)

        # Indices in the 30D feature vector:
        #   [12]=yaw, [13]=pitch, [15]=raw_nose_x, [16]=raw_nose_y
        return NosePose(
            raw_nose_x=features[15],
            raw_nose_y=features[16],
            yaw=features[12],
            pitch=features[13],
            double_blink=double_blink,
        ), is_blinking

    def close(self):
        self._face_landmarker.close()
