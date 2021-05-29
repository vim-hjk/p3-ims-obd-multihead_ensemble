python augmix_train.py --seed 42 --batch_size 16 --lr 1e-4 --trn_ratio 0.0 \
                     --decay 1e-6 --epochs 40 \
                     --cutmix_beta 0.0 --use_weight 1 --use_augmix 1 \
                     --version "hrnet_ocr_v8" --model_type 'hrnet_ocr'

# Weighted DiceCELoss