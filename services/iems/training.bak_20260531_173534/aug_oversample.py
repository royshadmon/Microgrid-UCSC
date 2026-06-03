"""MATNilm-inspired oversampling for sparse-positive NILM heads.

True MATNilm (Xiong 2023) injects appliance operation profiles into the
aggregate signal at minibatch time. That requires per-appliance circuit
truth, which we don't have yet (waiting on Dr. Mantey's I11-I32 labels).

This module implements the easier sibling: weighted random sampling that
biases minibatches toward windows containing positives for sparse classes.
Same algebraic effect on the gradient (the rare positive contributes more
per epoch), but no need for per-appliance ground-truth circuits.

For each head with positive_rate < THRESHOLD, identify windows where that
head is positive at the midpoint and oversample them so the effective
per-epoch positive count is at least MIN_EPOCH_POSITIVES.
"""
from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import WeightedRandomSampler


def build_oversample_weights(y_dict: dict, head_keys: tuple,
                             sparse_threshold: float = 0.05,
                             target_min_pos_rate: float = 0.10) -> np.ndarray:
    """Return per-sample weights for WeightedRandomSampler.

    A sample's weight is 1.0 by default. If it contains a positive label
    for one or more sparse heads (positive rate < sparse_threshold), its
    weight is boosted so that the effective per-epoch positive rate for
    each sparse head reaches target_min_pos_rate.

    Args:
        y_dict: {head_name: np.ndarray of labels, shape (N,)} for each head
        head_keys: ordered head names to iterate
        sparse_threshold: heads with positive rate below this are oversampled
        target_min_pos_rate: minimum positive rate per epoch after oversampling

    Returns:
        weights: shape (N,) array of float sampling weights
    """
    N = len(next(iter(y_dict.values())))
    weights = np.ones(N, dtype=np.float64)

    info = {}
    for h in head_keys:
        y = y_dict[h]
        mask = ~np.isnan(y)
        pos_idx = np.where(mask & (y > 0.5))[0]
        n_pos = len(pos_idx)
        pos_rate = n_pos / max(mask.sum(), 1)
        info[h] = {"n_pos": n_pos, "pos_rate": pos_rate, "pos_idx": pos_idx}

        if pos_rate < sparse_threshold and n_pos > 0:
            # Boost factor so that pos_idx accounts for target_min_pos_rate
            # of the effective sample distribution.
            # Effective positive rate = (boost * n_pos) / (boost * n_pos + (N - n_pos))
            # Solve for boost given target rate t: boost = t * (N - n_pos) / ((1-t) * n_pos)
            t = target_min_pos_rate
            boost = t * (N - n_pos) / max((1 - t) * n_pos, 1e-9)
            weights[pos_idx] = np.maximum(weights[pos_idx], boost)
            info[h]["boost"] = boost
        else:
            info[h]["boost"] = 1.0

    return weights, info


def make_oversampler(y_dict: dict, head_keys: tuple,
                     sparse_threshold: float = 0.05,
                     target_min_pos_rate: float = 0.10,
                     num_samples: int | None = None) -> WeightedRandomSampler:
    """Construct a WeightedRandomSampler that oversamples rare positives."""
    weights, info = build_oversample_weights(
        y_dict, head_keys, sparse_threshold, target_min_pos_rate
    )
    N = len(weights)
    if num_samples is None:
        num_samples = N
    sampler = WeightedRandomSampler(
        torch.from_numpy(weights), num_samples=num_samples, replacement=True
    )
    return sampler, info


def add_signal_noise(X: torch.Tensor, sigma: float = 0.02) -> torch.Tensor:
    """Light additive noise on aggregate features only (cols 0-4 = panel watts + utility tie).

    Acts as a regularizer when oversampling — without it, the same rare-positive
    windows get repeated identically multiple times per epoch and the model
    memorizes them. With sigma=0.02 (after standardization), noise ~2% of std.
    """
    if sigma <= 0:
        return X
    noise = torch.zeros_like(X)
    # Add noise to first 5 cols (panel watts + utility tie current)
    noise[..., :5] = torch.randn_like(X[..., :5]) * sigma
    return X + noise
