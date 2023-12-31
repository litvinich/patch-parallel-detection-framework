import os
from typing import Any, Dict, Optional

import cv2
import numpy as np

from dronedet.base import SimpleRunnerManager  # type: ignore
from dronedet.utils import draw_bbox, scale_bboxes_numpy, unlink_dict  # type: ignore


class VisualizationRunnerManager(SimpleRunnerManager):
    def __init__(self, config: Dict[str, Any], global_config: Dict[str, Any], name: Optional[str] = None):
        super().__init__(name)
        self._load_cfg(config)
        self._load_global_cfg(global_config)

    def _load_cfg(self, config: Dict[str, Any]) -> None:
        self._resize = config.get("resize")
        self._detection_class_names = config["detection_class_names"]
        self._detection_class_colors = config["detection_class_colors"]
        self._save = config["save"]
        self._verbose = config.get("verbose", True)

    def _load_global_cfg(self, config: Dict[str, Any]) -> None:
        self._cameras = list(config["cameras"].values())  # cameras is list of dicts (e.g. video: {})
        self._detection_output_size = (self._cameras[0]["height"], self._cameras[0]["width"])

    def _get_number_of_mini_runners(self) -> int:
        return len(self._cameras)

    def _init_drawing(self, camera_index: int) -> None:
        camera_params = self._cameras[camera_index]
        if self._save.get("video") is None:
            self._video_writer = None
            return

        output_video = os.path.join(self._save["folder_path"], camera_params["name"], "video.mkv")
        os.makedirs(os.path.dirname(output_video), exist_ok=True)
        codec = cv2.VideoWriter_fourcc(*"XVID")
        fps = self._save["video"].get("fps", 10)
        width = camera_params["width"] if self._resize is None else self._resize[1]
        height = camera_params["height"] if self._resize is None else self._resize[0]
        self._video_writer = cv2.VideoWriter(output_video, codec, fps, (width, height), isColor=True)

    def _visualize_detection_results(
        self,
        image: np.ndarray,
        results: np.ndarray,
        tracks: Optional[np.ndarray] = None,
        font_scale: float = 0.75,
        font_thickness: int = 2,
        thickness: int = 2,
    ) -> np.ndarray:
        if self._detection_class_colors is None:
            raise ValueError("First choose colors")

        if image.shape[:2] != self._detection_output_size:
            results = scale_bboxes_numpy(
                bboxes=results, input_size=self._detection_output_size, output_size=image.shape[:2]
            )
        for index, bbox in enumerate(results):
            text = f"{self._detection_class_names[int(bbox[-1])]} {bbox[-2]:.2f}"
            if tracks is not None:
                text += f"(Track #{int(tracks[index])})"
            image = draw_bbox(
                image=image,
                left_top=(int(bbox[0]), int(bbox[1])),
                right_bottom=(int(bbox[2]), int(bbox[3])),
                text=text,
                text_color=self._detection_class_colors[int(bbox[-1])],
                bbox_color=self._detection_class_colors[int(bbox[-1])],
                font_scale=font_scale,
                font_thickness=font_thickness,
                thickness=thickness,
            )
        return image

    def _write_image(self, image: np.ndarray) -> None:
        if self._video_writer is not None:
            self._video_writer.write(image)

    def _init_run(self, camera_index: int) -> None:
        self._init_drawing(camera_index)

    def _process(self, share_data: Dict[str, Any], camera_index: int) -> None:
        image = share_data["images_cpu"]
        bboxes = share_data["bboxes_with_tracks"]
        debug_image = image.transpose(1, 2, 0)
        if self._resize is not None:
            debug_image = cv2.resize(debug_image, dsize=(self._resize[1], self._resize[0]))
        debug_image = self._visualize_detection_results(debug_image, bboxes, tracks=bboxes[:, 4])
        debug_image = cv2.cvtColor(debug_image, cv2.COLOR_RGB2BGR)
        self._write_image(image=debug_image)
        # it is final Runner, delete shared memory
        unlink_dict(share_data)
