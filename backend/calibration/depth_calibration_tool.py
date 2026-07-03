#!/usr/bin/env python3
"""
Standalone tool pentru recalibrarea depth map cu click pe frame.

Ce face:
- Deschide un stream video (webcam implicit, sau URL/fișier).
- Rulează Depth Anything V2 pe frame.
- Afișează overlay RGB + depth colormap.
- La click stânga pe pixel cere distanța reală (metri) în terminal.
- Salvează calibrarea într-un fișier YAML separat.

Format YAML rezultat:
calibration_points:
  "0": 0.3
  "128": 1.0
timestamp: 1766922388.82
samples:
  - x: 320
    y: 180
    pixel_value: 128
    real_distance_m: 1.0
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import cv2
import matplotlib
import numpy as np
import torch


CURRENT_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
DEPTH_ANYTHING_ROOT = os.path.join(BACKEND_DIR, "Depth-Anything-V2")
if DEPTH_ANYTHING_ROOT not in sys.path:
    sys.path.insert(0, DEPTH_ANYTHING_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from depth_anything_v2.dpt import DepthAnythingV2

from tello_controller import TelloController


@dataclass
class Sample:
    x: int
    y: int
    pixel_value: int
    real_distance_m: float


class DepthCalibrationTool:
    def __init__(self, source: str, output_yaml: str, input_size: int = 384) -> None:
        self.source = self._parse_source(source)
        self.output_yaml = output_yaml
        self.input_size = input_size

        self.window_name = "Depth Calibration Tool"
        self.cap: Optional[cv2.VideoCapture] = None
        self.tello_controller: Optional[TelloController] = None
        self.using_tello = self.source == "tello"
        self.model: Optional[DepthAnythingV2] = None
        self.cmap = matplotlib.colormaps.get_cmap("Spectral_r")

        self.last_frame_bgr: Optional[np.ndarray] = None
        self.last_depth_raw: Optional[np.ndarray] = None
        self.last_depth_inv_u8: Optional[np.ndarray] = None

        self.calibration_points: Dict[int, float] = {}
        self.samples: List[Sample] = []
        self.last_click: Optional[tuple[int, int]] = None

        self.pending_click: Optional[Tuple[int, int]] = None
        self.is_frozen = False
        self.frozen_frame_bgr: Optional[np.ndarray] = None
        self.frozen_depth_raw: Optional[np.ndarray] = None
        self.frozen_depth_inv_u8: Optional[np.ndarray] = None

    @staticmethod
    def _safe_float(value: str) -> Optional[float]:
        try:
            return float(value.strip().replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _safe_int(value: str) -> Optional[int]:
        try:
            return int(value.strip())
        except ValueError:
            return None

    def load_existing_yaml(self) -> None:
        if not os.path.exists(self.output_yaml):
            return

        try:
            with open(self.output_yaml, "r", encoding="utf-8") as file_handle:
                lines = file_handle.readlines()
        except Exception as error:
            print(f"⚠️ Nu pot citi YAML existent: {error}")
            return

        section = ""
        parsed_points: Dict[int, float] = {}
        parsed_samples: List[Sample] = []
        current_sample: Dict[str, Optional[float]] = {}

        def flush_sample() -> None:
            if not current_sample:
                return
            x_val = current_sample.get("x")
            y_val = current_sample.get("y")
            pixel_val = current_sample.get("pixel_value")
            dist_val = current_sample.get("real_distance_m")
            if (
                isinstance(x_val, (int, float))
                and isinstance(y_val, (int, float))
                and isinstance(pixel_val, (int, float))
                and isinstance(dist_val, (int, float))
            ):
                parsed_samples.append(
                    Sample(
                        x=int(x_val),
                        y=int(y_val),
                        pixel_value=int(pixel_val),
                        real_distance_m=float(dist_val),
                    )
                )
            current_sample.clear()

        for raw_line in lines:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                continue

            if stripped == "calibration_points:":
                flush_sample()
                section = "points"
                continue

            if stripped == "samples:":
                flush_sample()
                section = "samples"
                continue

            if stripped.startswith("timestamp:"):
                continue

            if section == "points":
                candidate = stripped
                if candidate.startswith('"') and '":' in candidate:
                    key_part, value_part = candidate.split('":', 1)
                    pixel_key = self._safe_int(key_part.replace('"', ""))
                    distance_val = self._safe_float(value_part)
                    if pixel_key is not None and distance_val is not None:
                        parsed_points[pixel_key] = distance_val
                continue

            if section == "samples":
                if stripped.startswith("- "):
                    flush_sample()
                    stripped = stripped[2:].strip()

                if ":" not in stripped:
                    continue

                field, value = stripped.split(":", 1)
                field = field.strip()
                value = value.strip()

                if field in ("x", "y", "pixel_value"):
                    parsed_value = self._safe_int(value)
                    if parsed_value is not None:
                        current_sample[field] = parsed_value
                elif field == "real_distance_m":
                    parsed_value = self._safe_float(value)
                    if parsed_value is not None:
                        current_sample[field] = parsed_value

        flush_sample()

        if parsed_points:
            self.calibration_points.update(parsed_points)
        if parsed_samples:
            self.samples.extend(parsed_samples)

        if parsed_points or parsed_samples:
            print(
                "📥 Încărcat YAML existent: "
                f"{len(parsed_points)} puncte unice, {len(parsed_samples)} samples"
            )

    @staticmethod
    def _parse_source(source: str) -> Union[int, str]:
        normalized = source.strip().lower()
        if normalized in ("tello", "drone"):
            return "tello"
        if source.isdigit():
            return int(source)
        return source

    def init_model(self) -> None:
        print("🧠 Încărcare model Depth Anything V2...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"📱 Device: {device}")

        model_configs = {
            "vits": {
                "encoder": "vits",
                "features": 64,
                "out_channels": [48, 96, 192, 384],
            }
        }

        checkpoint_path = os.path.join(
            BACKEND_DIR,
            "Depth-Anything-V2",
            "checkpoints",
            "depth_anything_v2_vits.pth",
        )

        if not os.path.exists(checkpoint_path):
            raise FileNotFoundError(f"Checkpoint lipsă: {checkpoint_path}")

        model = DepthAnythingV2(**model_configs["vits"])
        model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        self.model = model.to(device).eval()

        print("✅ Model încărcat")

    def init_capture(self) -> None:
        if self.using_tello:
            print("🚁 Conectare la drona Tello...")
            try:
                self.tello_controller = TelloController()
            except Exception as error:
                raise RuntimeError(
                    "Nu mă pot conecta la Tello. Verifică să fii conectat la Wi-Fi-ul dronei "
                    "(ex: TELLO-XXXX), apoi reîncearcă. "
                    "Alternativ, rulează cu --source 0 pentru webcam local."
                ) from error
            print("✅ Camera dronei este activă")
            return

        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Nu pot deschide sursa video: {self.source}")

        print(f"🎥 Sursă video deschisă: {self.source}")

    def read_frame(self) -> Optional[np.ndarray]:
        if self.using_tello:
            if self.tello_controller is None:
                return None
            return self.tello_controller.get_frame_bgr()

        if self.cap is None:
            return None

        ok, frame = self.cap.read()
        if not ok:
            return None
        return frame

    def infer_depth(self, frame_bgr: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Modelul nu este inițializat")
        with torch.no_grad():
            depth = self.model.infer_image(frame_bgr, self.input_size)
        return depth.astype(np.float32)

    @staticmethod
    def normalize_depth_inverse_u8(depth: np.ndarray) -> np.ndarray:
        depth_min = float(depth.min())
        depth_max = float(depth.max())
        if depth_max - depth_min < 1e-6:
            return np.zeros_like(depth, dtype=np.uint8)
        depth_normalized = (depth - depth_min) / (depth_max - depth_min) * 255.0
        depth_inverse = 255.0 - depth_normalized
        return depth_inverse.astype(np.uint8)

    @staticmethod
    def depth_to_colormap(depth: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def depth_to_stream_colormap(self, depth_raw: np.ndarray) -> np.ndarray:
        depth_min = float(depth_raw.min())
        depth_max = float(depth_raw.max())
        if depth_max - depth_min < 1e-6:
            return np.zeros((depth_raw.shape[0], depth_raw.shape[1], 3), dtype=np.uint8)

        depth_normalized = (depth_raw - depth_min) / (depth_max - depth_min)
        return (self.cmap(depth_normalized)[:, :, :3] * 255)[:, :, ::-1].astype(np.uint8)

    def _prompt_distance_and_store(self, x: int, y: int) -> None:
        if self.frozen_depth_inv_u8 is None:
            return

        h, w = self.frozen_depth_inv_u8.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return

        pixel_value = int(self.frozen_depth_inv_u8[y, x])
        print(f"\n📍 Punct selectat: x={x}, y={y}, pixel_value={pixel_value}")
        typed = input("Introdu distanța reală (m), Enter=skip: ").strip()
        if not typed:
            print("ℹ️ Sample ignorat")
            return

        try:
            real_distance = float(typed.replace(",", "."))
        except ValueError:
            print("⚠️ Valoare invalidă, sample ignorat")
            return

        self.calibration_points[pixel_value] = real_distance
        self.samples.append(
            Sample(
                x=x,
                y=y,
                pixel_value=pixel_value,
                real_distance_m=real_distance,
            )
        )
        self.last_click = (x, y)

        print(
            f"✅ Adăugat: pixel {pixel_value} -> {real_distance:.3f}m "
            f"(total puncte unice: {len(self.calibration_points)})"
        )

    def on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            if self.last_frame_bgr is None or self.last_depth_raw is None or self.last_depth_inv_u8 is None:
                return

            self.pending_click = (x, y)
            self.last_click = (x, y)
            self.is_frozen = True
            self.frozen_frame_bgr = self.last_frame_bgr.copy()
            self.frozen_depth_raw = self.last_depth_raw.copy()
            self.frozen_depth_inv_u8 = self.last_depth_inv_u8.copy()

    def save_yaml(self) -> None:
        sorted_points = dict(sorted(self.calibration_points.items(), key=lambda kv: kv[0]))

        lines: List[str] = []
        lines.append("calibration_points:")
        for pixel, distance_m in sorted_points.items():
            lines.append(f'  "{pixel}": {distance_m}')
        lines.append(f"timestamp: {time.time()}")
        lines.append("samples:")
        for sample in self.samples:
            lines.append("  - x: {}".format(sample.x))
            lines.append("    y: {}".format(sample.y))
            lines.append("    pixel_value: {}".format(sample.pixel_value))
            lines.append("    real_distance_m: {}".format(sample.real_distance_m))

        out_dir = os.path.dirname(self.output_yaml)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(self.output_yaml, "w", encoding="utf-8") as file_handle:
            file_handle.write("\n".join(lines) + "\n")

        print(f"💾 Calibrare salvată în: {self.output_yaml}")

    def draw_overlay(self, frame_bgr: np.ndarray, depth_raw: np.ndarray) -> np.ndarray:
        depth_color = self.depth_to_stream_colormap(depth_raw)
        vis = depth_color.copy()

        info = [
            f"Puncte unice: {len(self.calibration_points)}",
            f"Samples totale: {len(self.samples)}",
            "Click stanga: freeze + select punct + input distanta",
            "Taste: s=save yaml, c=clear, q=quit",
        ]
        y0 = 25
        for text in info:
            cv2.putText(
                vis,
                text,
                (10, y0),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            y0 += 25

        if self.last_click is not None and self.last_depth_inv_u8 is not None:
            x, y = self.last_click
            if not (0 <= y < self.last_depth_inv_u8.shape[0] and 0 <= x < self.last_depth_inv_u8.shape[1]):
                return vis

            pixel_value = int(self.last_depth_inv_u8[y, x])
            real_distance = self.calibration_points.get(pixel_value)

            cv2.circle(vis, (x, y), 6, (0, 255, 0), -1)
            cv2.circle(vis, (x, y), 8, (255, 255, 255), 1)
            if real_distance is not None:
                label = f"pix={pixel_value} -> {real_distance:.2f}m"
                cv2.putText(
                    vis,
                    label,
                    (x + 10, max(20, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    2,
                )

        return vis

    def run(self) -> None:
        self.init_model()
        self.init_capture()
        self.load_existing_yaml()

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self.on_mouse)

        try:
            while True:
                if self.is_frozen and self.frozen_frame_bgr is not None and self.frozen_depth_raw is not None:
                    self.last_frame_bgr = self.frozen_frame_bgr
                    self.last_depth_raw = self.frozen_depth_raw
                    self.last_depth_inv_u8 = self.frozen_depth_inv_u8
                    vis = self.draw_overlay(self.frozen_frame_bgr, self.frozen_depth_raw)
                    cv2.putText(
                        vis,
                        "FRAME BLOCAT - introdu distanta in terminal",
                        (10, vis.shape[0] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 255, 255),
                        2,
                    )
                    cv2.imshow(self.window_name, vis)

                    if self.pending_click is not None:
                        x, y = self.pending_click
                        self.pending_click = None
                        self._prompt_distance_and_store(x, y)
                        self.is_frozen = False
                        self.frozen_frame_bgr = None
                        self.frozen_depth_raw = None
                        self.frozen_depth_inv_u8 = None

                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        break
                    if key == ord("c"):
                        self.calibration_points.clear()
                        self.samples.clear()
                        self.last_click = None
                        self.pending_click = None
                        self.is_frozen = False
                        self.frozen_frame_bgr = None
                        self.frozen_depth_raw = None
                        self.frozen_depth_inv_u8 = None
                        print("🧹 Calibrare curățată")
                    if key == ord("s"):
                        self.save_yaml()
                    continue

                frame = self.read_frame()
                if frame is None:
                    print("⚠️ Frame indisponibil")
                    time.sleep(0.05)
                    break

                depth_raw = self.infer_depth(frame)
                depth_inv_u8 = self.normalize_depth_inverse_u8(depth_raw)

                self.last_frame_bgr = frame
                self.last_depth_raw = depth_raw
                self.last_depth_inv_u8 = depth_inv_u8

                vis = self.draw_overlay(frame, depth_raw)
                cv2.imshow(self.window_name, vis)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("c"):
                    self.calibration_points.clear()
                    self.samples.clear()
                    self.last_click = None
                    print("🧹 Calibrare curățată")
                if key == ord("s"):
                    self.save_yaml()
        finally:
            if self.cap is not None:
                self.cap.release()
            if self.tello_controller is not None:
                try:
                    self.tello_controller.streamoff()
                except Exception:
                    pass
            cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone depth calibration (YAML output)")
    parser.add_argument(
        "--source",
        default="tello",
        help="Sursa video: tello (implicit), index webcam (ex: 0), URL stream sau path fișier video",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(CURRENT_DIR, "depth_calibration_new.yaml"),
        help="Fișier YAML de ieșire",
    )
    parser.add_argument(
        "--input-size",
        type=int,
        default=384,
        help="Input size pentru inferența Depth Anything",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = DepthCalibrationTool(
        source=args.source,
        output_yaml=args.output,
        input_size=args.input_size,
    )
    app.run()


if __name__ == "__main__":
    main()
