from typing import Any, Dict, Optional

import numpy as np
import torch

import shared_numpy as snp
from dronedet.base import SimpleRunner
from dronedet.utils import get_index, import_object, nms_all_bboxes


class DetectionBatchRunner(SimpleRunner):
    def __init__(self, config: Dict[str, Any], global_config: Dict[str, Any], name: Optional[str] = None):
        super().__init__(name)
        self._load_cfg(config)
        self._load_global_cfg(global_config)

        self._last_time_empty = {index: 0 for index in range(len(self._cameras))}

    def _load_cfg(self, config: Dict[str, Any]) -> None:
        self._config = config
        self._model_class = import_object(config["class"])
        self._after_merge_iou_threshold = config["after_merge_iou_threshold"]
        self._lazy_mode_time = config.get("lazy_mode_time", 0)
        self._verbose = config.get("verbose", True)

    def _load_global_cfg(self, config: Dict[str, Any]) -> None:
        self._cameras = list(config["cameras"].values())  # cameras is list of dicts (e.g. video: {})

    def _init_run(self) -> None:
        self._model = self._model_class(self._config["params"])

    def _process(self, share_data: Dict[str, Any]) -> Dict[str, Any]:
        crop_batch_tensor = share_data["images_gpu"]  # [B, N_crops, 3, H_new, W_new]
        crop_meta = share_data["crop_meta"]
        meta = share_data["meta"]

        # leave images for run: drop image if lazy_time is not over
        leave_images_for_model = [
            index
            for index in range(crop_batch_tensor.size(0))
            if meta[index]["success"] and meta[index]["time"] - self._last_time_empty[index] > self._lazy_mode_time
        ]
        subbatch_crop_tensor = crop_batch_tensor[leave_images_for_model]
        crop_forwarded_bboxes = []
        if subbatch_crop_tensor.size(0) > 0:
            # [B, N_crops, 3, H_new, W_new] -> [B * N_crops, 3, H_new, W_new]
            subbatch_tensor = crop_batch_tensor.view(-1, *subbatch_crop_tensor.shape[2:])
            crop_forwarded_bboxes = self._model(subbatch_tensor)

        forwarded_bboxes = []
        # now merge predictions from crop to image level
        for image_index in range(len(crop_forwarded_bboxes) // crop_batch_tensor.size(1)):
            image_bboxes = torch.empty((0, 6), dtype=self._model.dtype, device=self._model.device)
            for crop_index in range(crop_batch_tensor.size(1)):
                crop_bboxes = crop_forwarded_bboxes[image_index * crop_batch_tensor.size(1) + crop_index]
                if crop_bboxes.size(0) == 0:
                    continue
                height_bias = crop_meta[image_index][crop_index].height_start
                width_bias = crop_meta[image_index][crop_index].width_start
                bias_tensor = torch.tensor([width_bias, height_bias, width_bias, height_bias]).view(1, -1)
                crop_bboxes[:, :4] += bias_tensor.to(crop_bboxes.device)
                image_bboxes = torch.cat([image_bboxes, crop_bboxes])
            image_bboxes = nms_all_bboxes(image_bboxes, self._after_merge_iou_threshold)
            forwarded_bboxes.append(image_bboxes)

        # if image has no predictions then lazy time starts
        bboxes = []
        for index in range(crop_batch_tensor.size(0)):
            index_in_forwarded_bboxes = get_index(element=index, element_list=leave_images_for_model)
            if index_in_forwarded_bboxes is not None:
                image_bboxes = forwarded_bboxes[index_in_forwarded_bboxes].cpu().numpy()
                if len(image_bboxes) == 0:
                    self._last_time_empty[index] = meta[index]["time"]
            else:
                image_bboxes = np.empty((0, 6))  # type: ignore
            bboxes.append(image_bboxes)

        # add bboxes to shared memory to avoid extra pickles-unpickles.
        share_data["bboxes"] = [
            snp.from_array(image_bboxes) if len(image_bboxes) > 0 else image_bboxes for image_bboxes in bboxes
        ]
        return share_data
