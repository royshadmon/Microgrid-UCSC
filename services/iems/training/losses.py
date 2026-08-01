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


# ─────────────────────────────────────────────────────────────────────────
# CamAL dual-supervision losses (strong + weak), per-sample weighted.
#
# The original masked_bce takes a SCALAR pos_weight and .mean()s every sample
# equally, so a per-label confidence column is inert. These variants accept a
# per-sample weight tensor so the dual labeller's trust tiers actually bite:
#     1.00  measured CT ground truth
#     ~conf temporal-signature confirmed, non-coupled
#     0.25  rule-only / coupled guess  (degenerate loads: microwave, cooktop,
#           dishwasher, freezer_garage -> present but never trusted)
#     0.00  abstain
# ─────────────────────────────────────────────────────────────────────────
def masked_bce_weighted(prob, target, weight, pos_weight: float = 1.0):
    """BCE with BOTH a scalar class weight and a per-sample trust weight.

    prob, target, weight: same shape. NaN targets are masked out. Samples with
    weight 0 contribute nothing (abstain).
    """
    mask = ~torch.isnan(target)
    if mask.sum() == 0:
        return prob.sum() * 0.0
    p = prob[mask].clamp(1e-6, 1 - 1e-6)
    t = target[mask]
    w = weight[mask]
    ll = -(pos_weight * t * p.log() + (1 - t) * (1 - p).log())
    denom = w.sum().clamp(min=1e-6)
    return (ll * w).sum() / denom


def weak_mil_loss(prob_window, target_window, weight_window):
    """Multiple-Instance-Learning loss for WEAK (per-window) labels.

    prob_window: (B, T) per-timestep probabilities for one appliance.
    target_window: (B,) 1 if the appliance ran ANYWHERE in the window.
    weight_window: (B,) trust in that window label.

    Max-pooling over time is the standard MIL reduction: a window is positive
    iff at least one timestep is positive. This is what lets a coupled load
    still supervise the model - "the dryer ran this afternoon" is knowable even
    when the exact minutes are not.
    """
    bag = prob_window.max(dim=1).values.clamp(1e-6, 1 - 1e-6)
    t = target_window
    w = weight_window
    ll = -(t * bag.log() + (1 - t) * (1 - bag).log())
    return (ll * w).sum() / w.sum().clamp(min=1e-6)


def dual_loss(prob, strong_t, strong_w, weak_t, weak_w,
              pos_weight: float = 1.0, weak_lambda: float = 0.3):
    """Cross-check twice: strong per-sample supervision + weak per-window MIL.

    weak_lambda balances the two. The weak term is the non-circular one (it does
    not depend on the rule thresholds being right at each instant), so it acts
    as a regulariser against the strong term's circularity.
    """
    ls = masked_bce_weighted(prob, strong_t, strong_w, pos_weight)
    lw = weak_mil_loss(prob, weak_t, weak_w)
    return ls + weak_lambda * lw
