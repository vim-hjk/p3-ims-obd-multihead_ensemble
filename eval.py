import os
import cv2
import argparse
import numpy as np
import pandas as pd
import multiprocessing as mp
import albumentations
import albumentations.pytorch
import segmentation_models_pytorch as smp
import torch.nn as nn
import pydensecrf.densecrf as dcrf
import pydensecrf.utils as utils
import torch.nn.functional as F


from importlib import import_module
from prettyprinter import cpprint
from tqdm import tqdm

import torch

from src.utils import seed_everything, YamlConfigManager, get_dataloader
from src.model import *

def dense_crf_wrapper(args):
    return dense_crf(args[0], args[1])

def dense_crf(img, output_probs):
    MAX_ITER = 10
    POS_W = 3
    POS_XY_STD = 1
    Bi_W = 4
    Bi_XY_STD = 67
    Bi_RGB_STD = 3

    c = output_probs.shape[0]
    h = output_probs.shape[1]
    w = output_probs.shape[2]

    U = utils.unary_from_softmax(output_probs)
    U = np.ascontiguousarray(U)

    img = np.ascontiguousarray(img)

    d = dcrf.DenseCRF2D(w, h, c)
    d.setUnaryEnergy(U)
    d.addPairwiseGaussian(sxy=POS_XY_STD, compat=POS_W)
    d.addPairwiseBilateral(sxy=Bi_XY_STD, srgb=Bi_RGB_STD, rgbim=img, compat=Bi_W)

    Q = d.inference(MAX_ITER)
    Q = np.array(Q).reshape((c, h, w))
    return Q


def test(cfg):    
    SEED = cfg.values.seed    
    BACKBONE = cfg.values.backbone
    MODEL_ARC = cfg.values.model_arc
    NUM_CLASSES = cfg.values.num_classes

    checkpoint = cfg.values.checkpoint
    test_batch_size = cfg.values.test_batch_size

    # for reproducibility
    seed_everything(SEED)

    data_path = '/opt/ml/input/data'
    test_annot = os.path.join(data_path, 'test.json')
    checkpoint_path = f'/opt/ml/vim-hjk/results/{MODEL_ARC}'

    test_transform = albumentations.Compose([
        albumentations.Resize(512, 512),
        albumentations.Normalize(mean=(0.461, 0.440, 0.419), std=(0.211, 0.208, 0.216)),
        albumentations.pytorch.transforms.ToTensorV2()])

    size = 256
    resize = albumentations.Resize(size, size)
    
    test_loader = get_dataloader(data_dir=test_annot, mode='test', transform=test_transform, batch_size=test_batch_size, shuffle=False)

    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

    model_module = getattr(import_module('segmentation_models_pytorch'), MODEL_ARC)

    model = model_module(
        encoder_name=BACKBONE,
        in_channels=3,
        classes=NUM_CLASSES
    )

    model = model.to(device)
    model.load_state_dict(torch.load(os.path.join(checkpoint_path, checkpoint)))
    print('Start prediction.')
    model.eval()

    file_name_list = []
    preds_array = np.empty((0, size * size), dtype=np.compat.long)

    with torch.no_grad():
        for step, (imgs, image_infos) in enumerate(tqdm(test_loader, desc='Test : ')):

            # inference (512 x 512)
            outs = model(torch.stack(imgs).to(device))
            probs = F.softmax(outs, dim=1).data.cpu().numpy()
            
            pool = mp.Pool(mp.cpu_count())
            images = torch.stack(imgs).data.cpu().numpy().astype(np.uint8).transpose(0, 2, 3, 1)
            probs = np.array(pool.map(dense_crf_wrapper, zip(images, probs)))
            pool.close()
            
            oms = np.argmax(probs, axis=1)
            
            # resize (256 x 256)
            temp_mask = []
            for img, mask in zip(np.stack(imgs), oms):
                transformed = resize(image=img, mask=mask)
                mask = transformed['mask']
                temp_mask.append(mask)

            oms = np.array(temp_mask)
            
            oms = oms.reshape([oms.shape[0], size*size]).astype(int)
            preds_array = np.vstack((preds_array, oms))
            
            file_name_list.append([i['file_name'] for i in image_infos])
    print("End prediction.")
    file_names = [y for x in file_name_list for y in x]
    
    return file_names, preds_array


def make_submission(cfg):
    # sample_submisson.csv 열기
    submission = pd.read_csv('../code/submission/sample_submission.csv', index_col=None)

    # test set에 대한 prediction
    file_names, preds = test(cfg)

    # PredictionString 대입
    for file_name, string in zip(file_names, preds):
        submission = submission.append({"image_id" : file_name, "PredictionString" : ' '.join(str(e) for e in string.tolist())}, 
                                    ignore_index=True)

    # submission.csv로 저장
    os.makedirs('./submission', exist_ok=True)
    submission.to_csv(f"./submission/{cfg.values.backbone}_{cfg.values.model_arc}.csv", index=False)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--eval_config_file_path', type=str, default='./config/eval_config.yml')
    parser.add_argument('--eval_config', type=str, default='base')
    
    args = parser.parse_args()
    cfg = YamlConfigManager(args.eval_config_file_path, args.eval_config)
    cpprint(cfg.values, sort_dict_keys=False)
    print('\n')
    make_submission(cfg)