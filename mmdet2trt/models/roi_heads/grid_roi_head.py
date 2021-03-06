from mmdet2trt.models.builder import register_wraper, build_wraper
import torch
from torch import nn
import torch.nn.functional as F
from mmdet.core.bbox.coder.delta_xywh_bbox_coder import delta2bbox
from mmdet2trt.core.post_processing.batched_nms import BatchedNMS
from mmdet2trt.core.bbox.transforms import bbox2roi
import mmdet2trt.ops.util_ops as mm2trt_util
from .standard_roi_head import StandardRoIHeadWraper


@register_wraper("mmdet.models.roi_heads.grid_roi_head.GridRoIHead")
class GridRoIHeadWraper(StandardRoIHeadWraper):
    def __init__(self, module):
        super(GridRoIHeadWraper, self).__init__(module)

        self.grid_roi_extractor = build_wraper(module.grid_roi_extractor)
        self.grid_head = build_wraper(module.grid_head,
                                      test_cfg=module.test_cfg)

    def forward(self, feat, proposals, img_shape):
        batch_size = proposals.shape[0]
        num_proposals = proposals.shape[1]
        rois_pad = mm2trt_util.arange_by_input(proposals, 0).unsqueeze(1)
        rois_pad = rois_pad.repeat(1, num_proposals).view(-1, 1)
        proposals = proposals.view(-1, 4)
        rois = torch.cat([rois_pad, proposals], dim=1)

        # rcnn
        bbox_results = self._bbox_forward(feat, rois)

        cls_score = bbox_results['cls_score']
        bbox_pred = bbox_results['bbox_pred']

        num_detections, det_boxes, det_scores, det_classes = self.bbox_head.get_bboxes(
            rois, cls_score, bbox_pred, img_shape, batch_size, num_proposals,
            self.test_cfg)

        grid_rois = bbox2roi(det_boxes)
        grid_feats = self.grid_roi_extractor(
            feat[:len(self.grid_roi_extractor.featmap_strides)], grid_rois)

        grid_pred = self.grid_head(grid_feats)
        det_scores, det_boxes = self.grid_head.get_bboxes(
            det_scores.view(-1), det_boxes.view(-1, 4), grid_pred['fused'],
            img_shape)

        det_scores = det_scores.view(batch_size, -1)
        det_boxes = det_boxes.view(batch_size, -1, 4)
        return num_detections, det_boxes, det_scores, det_classes
