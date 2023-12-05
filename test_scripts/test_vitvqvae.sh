python ./trainers/train_vitvqvae.py \
    --mode 'test' \
    --from_checkpoint \
    --checkpoint_path './models/vitvqvae/model.pt' \
    --num_test_images 10 \
    --latent_dim 64 \
    --num_embeddings 512 \
    --image_channels 3 \
    --image_size 32 \
    --patch_size 4 \
    --beta 0.25 \
    --lr 0.001 \
    --num_heads 4 \
    --num_blocks 2 \
    --dropout 0.01 \
    --keep_prob 0.5
