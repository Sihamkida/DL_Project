# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
"""
Train and eval functions used in main.py
"""
import math
import os
#import cv2
import sys
import argparse
from pathlib import Path
from typing import Iterable
from PIL import Image
import numpy as np

import torch

import util.misc as utils

from models import build_model
#from datasets.face import make_face_transforms

import matplotlib.pyplot as plt
import time

from mros_data.datamodule import SleepEventDataModule
from mros_data.datamodule.transforms import STFTTransform
from librosa.display import specshow


def box_cxcywh_to_xyxy(x):
    x_c, y_c, w, h = x.unbind(1)
    b = [(x_c - 0.5 * w), (y_c - 0.5 * h),
         (x_c + 0.5 * w), (y_c + 0.5 * h)]
    return torch.stack(b, dim=1)

def rescale_bboxes(out_bbox, size):
    img_w, img_h = size
    b = box_cxcywh_to_xyxy(out_bbox)
    b = b * torch.tensor([img_w, img_h,
                          img_w, img_h
                          ], dtype=torch.float32)
    return b


def get_args_parser():
    parser = argparse.ArgumentParser("Set transformer detector", add_help=False)
    parser.add_argument("--overfit", action="store_true")
    parser.add_argument("--lr", default=1e-4, type=float)
    parser.add_argument("--lr_backbone", default=1e-5, type=float)
    parser.add_argument("--batch_size", default=2, type=int)
    parser.add_argument("--weight_decay", default=1e-4, type=float)
    parser.add_argument("--epochs", default=1, type=int)
    parser.add_argument("--lr_drop", default=200, type=int)
    parser.add_argument("--clip_max_norm", default=0.1, type=float, help="gradient clipping max norm")

    # Model parameters
    parser.add_argument(
        "--frozen_weights",
        type=str,
        default=None,
        help="Path to the pretrained model. If set, only the mask head will be trained",
    )
    # * Backbone
    parser.add_argument("--backbone", default="resnet50", type=str, help="Name of the convolutional backbone to use")
    parser.add_argument(
        "--dilation",
        action="store_true",
        help="If true, we replace stride with dilation in the last convolutional block (DC5)",
    )
    parser.add_argument(
        "--position_embedding",
        default="sine",
        type=str,
        choices=("sine", "learned"),
        help="Type of positional embedding to use on top of the image features",
    )

    # * Transformer
    parser.add_argument("--enc_layers", default=6, type=int, help="Number of encoding layers in the transformer")
    parser.add_argument("--dec_layers", default=6, type=int, help="Number of decoding layers in the transformer")
    parser.add_argument(
        "--dim_feedforward",
        default=2048,
        type=int,
        help="Intermediate size of the feedforward layers in the transformer blocks",
    )
    parser.add_argument(
        "--hidden_dim", default=256, type=int, help="Size of the embeddings (dimension of the transformer)"
    )
    parser.add_argument("--dropout", default=0.1, type=float, help="Dropout applied in the transformer")
    parser.add_argument(
        "--nheads", default=8, type=int, help="Number of attention heads inside the transformer's attentions"
    )
    parser.add_argument("--num_queries", default=100, type=int, help="Number of query slots")
    parser.add_argument("--pre_norm", action="store_true")

    # * Segmentation
    parser.add_argument("--masks", action="store_true", help="Train segmentation head if the flag is provided")

    # Loss
    parser.add_argument(
        "--no_aux_loss",
        dest="aux_loss",
        action="store_false",
        help="Disables auxiliary decoding losses (loss at each layer)",
    )
    # * Matcher
    parser.add_argument("--set_cost_class", default=1, type=float, help="Class coefficient in the matching cost")
    parser.add_argument("--set_cost_bbox", default=5, type=float, help="L1 box coefficient in the matching cost")
    parser.add_argument("--set_cost_giou", default=2, type=float, help="giou box coefficient in the matching cost")
    # * Loss coefficients
    parser.add_argument("--mask_loss_coef", default=1, type=float)
    parser.add_argument("--dice_loss_coef", default=1, type=float)
    parser.add_argument("--bbox_loss_coef", default=5, type=float)
    parser.add_argument("--giou_loss_coef", default=2, type=float)
    parser.add_argument(
        "--eos_coef", default=0.1, type=float, help="Relative classification weight of the no-object class"
    )

    # dataset parameters
    parser.add_argument("--dataset_file", default="coco")
    parser.add_argument("--coco_path", type=str)
    parser.add_argument("--coco_panoptic_path", type=str)
    parser.add_argument("--remove_difficult", action="store_true")

    parser.add_argument("--output_dir", default="", help="path where to save, empty for no saving")
    parser.add_argument("--device", default="cpu", help="device to use for training / testing")
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--resume", default="", help="resume from checkpoint")
    parser.add_argument("--start_epoch", default=0, type=int, metavar="N", help="start epoch")
    parser.add_argument("--eval", action="store_true")
    parser.add_argument("--num_workers", default=2, type=int)

    # distributed training parameters
    parser.add_argument("--world_size", default=1, type=int, help="number of distributed processes")
    parser.add_argument("--dist_url", default="env://", help="url used to set up distributed training")
    return parser

# ~ def get_args_parser():
    # ~ parser = argparse.ArgumentParser('Set transformer detector', add_help=False)
    # ~ parser.add_argument('--lr', default=1e-4, type=float)
    # ~ parser.add_argument('--lr_backbone', default=1e-5, type=float)
    # ~ parser.add_argument('--batch_size', default=6, type=int)
    # ~ parser.add_argument('--weight_decay', default=1e-4, type=float)
    # ~ parser.add_argument('--epochs', default=300, type=int)
    # ~ parser.add_argument('--lr_drop', default=200, type=int)
    # ~ parser.add_argument('--clip_max_norm', default=0.1, type=float,
                        # ~ help='gradient clipping max norm')

    # ~ # Model parameters
    # ~ parser.add_argument('--frozen_weights', type=str, default=None,
                        # ~ help="Path to the pretrained model. If set, only the mask head will be trained")
    # ~ # * Backbone
    # ~ parser.add_argument('--backbone', default='resnet50', type=str,
                        # ~ help="Name of the convolutional backbone to use")
    # ~ parser.add_argument('--dilation', action='store_true',
                        # ~ help="If true, we replace stride with dilation in the last convolutional block (DC5)")
    # ~ parser.add_argument('--position_embedding', default='sine', type=str, choices=('sine', 'learned'),
                        # ~ help="Type of positional embedding to use on top of the image features")

    # ~ # * Transformer
    # ~ parser.add_argument('--enc_layers', default=6, type=int,
                        # ~ help="Number of encoding layers in the transformer")
    # ~ parser.add_argument('--dec_layers', default=6, type=int,
                        # ~ help="Number of decoding layers in the transformer")
    # ~ parser.add_argument('--dim_feedforward', default=2048, type=int,
                        # ~ help="Intermediate size of the feedforward layers in the transformer blocks")
    # ~ parser.add_argument('--hidden_dim', default=256, type=int,
                        # ~ help="Size of the embeddings (dimension of the transformer)")
    # ~ parser.add_argument('--dropout', default=0.1, type=float,
                        # ~ help="Dropout applied in the transformer")
    # ~ parser.add_argument('--nheads', default=8, type=int,
                        # ~ help="Number of attention heads inside the transformer's attentions")
    # ~ parser.add_argument('--num_queries', default=10, type=int,
                        # ~ help="Number of query slots")
    # ~ parser.add_argument('--pre_norm', action='store_true')

    # ~ # * Segmentation
    # ~ parser.add_argument('--masks', action='store_true',
                        # ~ help="Train segmentation head if the flag is provided")

    # ~ # # Loss
    # ~ parser.add_argument('--no_aux_loss', dest='aux_loss', action='store_false',
                        # ~ help="Disables auxiliary decoding losses (loss at each layer)")
    # ~ # * Matcher
    # ~ parser.add_argument('--set_cost_class', default=1, type=float,
                        # ~ help="Class coefficient in the matching cost")
    # ~ parser.add_argument('--set_cost_bbox', default=5, type=float,
                        # ~ help="L1 box coefficient in the matching cost")
    # ~ parser.add_argument('--set_cost_giou', default=2, type=float,
                        # ~ help="giou box coefficient in the matching cost")
    # ~ # * Loss coefficients
    # ~ parser.add_argument('--mask_loss_coef', default=1, type=float)
    # ~ parser.add_argument('--dice_loss_coef', default=1, type=float)
    # ~ parser.add_argument('--bbox_loss_coef', default=5, type=float)
    # ~ parser.add_argument('--giou_loss_coef', default=2, type=float)
    # ~ parser.add_argument('--eos_coef', default=0.1, type=float,
                        # ~ help="Relative classification weight of the no-object class")

    # ~ # dataset parameters
    # ~ parser.add_argument('--dataset_file', default='face')
    # ~ parser.add_argument('--data_path', type=str)
    # ~ parser.add_argument('--data_panoptic_path', type=str)
    # ~ parser.add_argument('--remove_difficult', action='store_true')

    # ~ parser.add_argument('--output_dir', default='',
                        # ~ help='path where to save the results, empty for no saving')
    # ~ parser.add_argument('--device', default='cuda',
                        # ~ help='device to use for training / testing')
    # ~ parser.add_argument('--resume', default='', help='resume from checkpoint')

    # ~ parser.add_argument('--thresh', default=0.5, type=float)

    # ~ return parser


@torch.no_grad()

def infer(model, postprocessors, device, output_path, data_loader_train):
    '''
    this function plot the pictures with the predicted bounding boxes. 
    Inputs: (automatic from args)
    Outputs: void, shows the images 
    '''
    model.eval()
    duration = 0
    train_ds = dm.train
    batch = train_ds[1]
    record = batch['record']
    data = batch['signal']
    events = batch['events']
    for h5_sample_index in range(0,len(train_ds)):  # for every h5 file in the chosen path 
        # get_2Dmatrix is an added code to the detr/mros_data/datamodule/mixin/plotting_mixin.py file
        spectrogram = train_ds.get_2Dmatrix(h5_sample_index, channel_idx=0, window_size=int(4.0 * train_ds.fs), step_size=int(0.125 * train_ds.fs), nfft=1024)
        fig, ax = plt.subplots(figsize=(25, 4))
        img_sample = specshow(spectrogram, sr=10000, win_length=int(4.0 * train_ds.fs), ax=ax, hop_length=int(0.125 * train_ds.fs), n_fft=1024)      
        # ~ fig.colorbar(img)#,format="%+2.f dB")
        # ~ plt.show()
        
        # MS: change this code to plot the spectrogram.
        quad_mesh_sizes = img_sample.get_sizes()
        
        print("\n IMAGE SIZE", quad_mesh_sizes)
        print("\n------------\nCHECKPOINT 1\n-------------")

        w, h = img_sample.get_sizes()
        transform = make_face_transforms("val")
        dummy_target = {
            "size": torch.as_tensor([int(h), int(w)]),
            "orig_size": torch.as_tensor([int(h), int(w)])
        }
        image, targets = transform(orig_image, dummy_target)
        image = image.unsqueeze(0)
        image = image.to(device)


        conv_features, enc_attn_weights, dec_attn_weights = [], [], []
        hooks = [
            model.backbone[-2].register_forward_hook(
                        lambda self, input, output: conv_features.append(output)

            ),
            model.transformer.encoder.layers[-1].self_attn.register_forward_hook(
                        lambda self, input, output: enc_attn_weights.append(output[1])

            ),
            model.transformer.decoder.layers[-1].multihead_attn.register_forward_hook(
                        lambda self, input, output: dec_attn_weights.append(output[1])

            ),

        ]

        start_t = time.perf_counter()
        outputs = model(image)
        end_t = time.perf_counter()

        outputs["pred_logits"] = outputs["pred_logits"].cpu()
        outputs["pred_boxes"] = outputs["pred_boxes"].cpu()

        probas = outputs['pred_logits'].softmax(-1)[0, :, :-1]
        # keep = probas.max(-1).values > 0.85
        keep = probas.max(-1).values > args.thresh

        bboxes_scaled = rescale_bboxes(outputs['pred_boxes'][0, keep], orig_image.size)
        probas = probas[keep].cpu().data.numpy()

        for hook in hooks:
            hook.remove()

        conv_features = conv_features[0]
        enc_attn_weights = enc_attn_weights[0]
        dec_attn_weights = dec_attn_weights[0].cpu()

        # get the feature map shape
        h, w = conv_features['0'].tensors.shape[-2:]

        if len(bboxes_scaled) == 0:
            continue

        img = np.array(orig_image)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        for idx, box in enumerate(bboxes_scaled):
            bbox = box.cpu().data.numpy()
            bbox = bbox.astype(np.int32)
            bbox = np.array([
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                ])
            bbox = bbox.reshape((4, 2))
            cv2.polylines(img, [bbox], True, (0, 255, 0), 2)

        # img_save_path = os.path.join(output_path, filename)
        # cv2.imwrite(img_save_path, img)
        cv2.imshow("img", img)
        cv2.waitKey()
        infer_time = end_t - start_t
        duration += infer_time
        print("Processing...{} ({:.3f}s)".format(filename, infer_time))

    avg_duration = duration / len(h5_path)
    print("Avg. Time: {:.3f}s".format(avg_duration))


if __name__ == "__main__":
    parser = argparse.ArgumentParser('DETR training and evaluation script', parents=[get_args_parser()])
    args = parser.parse_args()
    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    device = torch.device(args.device)

    model, _, postprocessors = build_model(args)
    if args.resume:
        checkpoint = torch.load(args.resume, map_location='cpu')
        model.load_state_dict(checkpoint['model'])
    model.to(device)
    
    
    # MROS code to create the dataloader dm, that contains the train_ds, that contains the signals, that can be plotted as spectrograms
    params = dict(
        data_dir="mros-data-lm/lm_reduced",
        batch_size=args.batch_size,
        n_eval=0,
        n_test=0,
        num_workers=args.num_workers,
        seed=1337,
        events={"lm": "Leg movements"},
        window_duration=600,  # seconds
        cache_data=True,
        default_event_window_duration=[15],
        event_buffer_duration=3,
        factor_overlap=2,
        fs=128,
        matching_overlap=0.5,
        n_jobs=-1,
        n_records=1,
        overfit=args.overfit,
        picks=["legl", "legr"],
        # transform=MultitaperTransform(128, 0.5, 35.0, tw=8.0, normalize=True),
        transform=STFTTransform(
            fs=128, segment_size=int(4.0 * 128), step_size=int(0.125 * 128), nfft=1024, normalize=True
        ),
        scaling="robust",
    )
    dm = SleepEventDataModule(**params)
    dm.setup()
    data_loader_train = dm.train_dataloader()
    data_loader_val = dm.val_dataloader()
        
    # plot everything, data_loader_train is added to contain the data related to the signals in train (with --overfit train and val are the same)
    infer(model, postprocessors, device, args.output_dir, data_loader_train) # created above
