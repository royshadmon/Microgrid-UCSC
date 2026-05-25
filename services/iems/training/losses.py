"""Loss functions for NILM training.

Two losses, both with NaN masking for per-head labels:
- masked_bce: standard weighted BCE
- masked_focal: focal loss (Lin et al. 2017) for severe class imbalance

Use focal loss for heads where pos_weight in weighted BCE exceeds ~50.
At that range the gradient signal from rare positives collapses the model
into recall-only predictions; focal loss focuses on hard examples instead
of just rare ones.
"""
from __future__ import annotations

import torch


def masked_bce(prob: torch.Tensor, target: torch.Tensor, pos_weight: float = 1.0) -> torch.Tensor:
    """Weighted binary cross-entropy with NaN masking."""
    mask = ~torch.isnan(target)
    if mask.sum() == 0:
        return prob.new_zeros(())
    p = prob[mask].clamp(1e-7, 1 - 1e-7)
    t = target[mask]
    return -(pos_weight * t * p.log() + (1 - t) * (1 - p).log()).mean()


def masked_focal(prob: torch.Tensor, target: torch.Tensor,
                 gamma: float = 2.0, alpha: float = 0.25) -> torch.Tensor:
    """Focal loss with NaN masking. Lin et al. 2017 (arXiv:1708.02002).

    L = - alpha * (1 - p_t)^gamma * log(p_t)

    where p_t = p if y=1 else (1 - p). alpha balances positive/negative class.
    With alpha=0.25, easy negatives get 0.75 weight, hard positives get 0.25 —
    deliberately downweighting easy examples regardless of class.

    gamma controls the focusing strength. gamma=0 reduces to weighted CE;
    gamma=2 is the canonical setting for severely imbalanced detection tasks.
    """
    mask = ~torch.isnan(target)
    if mask.sum() == 0:
        return prob.new_zeros(())
    p = prob[mask].clamp(1e-7, 1 - 1e-7)
    t = target[mask]
    p_t = t * p + (1 - t) * (1 - p)
    alpha_t = t * alpha + (1 - t) * (1 - alpha)
    loss = -alpha_t * (1 - p_t).pow(gamma) * p_t.log()
    return loss.mean()


def auto_loss(pos_weight: float, focal_threshold: float = 50.0,
              gamma: float = 2.0, alpha: float = 0.25):
    """Return a loss closure that picks focal vs BCE based on pos_weight."""
    if pos_weight >= focal_threshold:
        def _focal(prob, target):
            return masked_focal(prob, target, gamma=gamma, alpha=alpha)
        return _focal, "focal"
    else:
        def _bce(prob, target):
            return masked_bce(prob, target, pos_weight=pos_weight)
        return _bce, "bce"
