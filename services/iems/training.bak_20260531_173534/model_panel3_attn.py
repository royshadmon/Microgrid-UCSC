"""Panel 3 NILM with appliance-wise attention (MATNilm 2DMA).

Extends the standard Panel3Net by inserting a multi-head self-attention
layer across the eight appliance representations. After each head's
BiLSTM stack produces a 32-dim hidden vector, the eight vectors are
stacked into a (B, 8, 32) tensor and passed through MultiheadAttention.
The attended representation goes into each head's classifier.

Xiong et al. 2023, MATNilm (arXiv:2307.14778), Section III.B:
    "Each appliance can update its representation based on other
     appliances' representations."

This is the appliance-wise half of the 2D attention (temporal × appliance).
Temporal attention is already implicit in the per-head BiLSTM.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class HeadBranchAttn(nn.Module):
    """BiLSTM stack that returns the hidden vector (not the sigmoid prediction).

    Final classifier is applied AFTER cross-appliance attention.
    """
    def __init__(self, in_dim: int = 32):
        super().__init__()
        self.lstm1 = nn.LSTM(in_dim, 32, batch_first=True, bidirectional=True)
        self.lstm2 = nn.LSTM(64, 16, batch_first=True, bidirectional=True)
        self.dropout = nn.Dropout(0.2)

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        h, _ = self.lstm1(h)
        h, _ = self.lstm2(h)
        return self.dropout(h[:, -1, :])           # (B, 32)


class Panel3NetAttn(nn.Module):
    """Panel3Net + appliance-wise multi-head attention before classification."""
    HEADS = (
        "refrigerator", "dishwasher", "microwave", "dryer",
        "washing_machine", "pressure_pump", "computers", "tv_stereo",
    )

    def __init__(self, in_features: int = 12, hidden_dim: int = 32,
                 attn_heads: int = 4):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_features, 32, kernel_size=5, padding=2),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.Dropout(0.1),
        )
        for name in self.HEADS:
            setattr(self, f"{name}_branch", HeadBranchAttn())

        # Appliance-wise self-attention.
        self.attn = nn.MultiheadAttention(
            embed_dim=hidden_dim,
            num_heads=attn_heads,
            batch_first=True,
        )
        self.attn_norm = nn.LayerNorm(hidden_dim)

        # Classifier per head (after attention).
        for name in self.HEADS:
            setattr(self, f"{name}_clf", nn.Sequential(
                nn.Linear(hidden_dim, 16),
                nn.ReLU(),
                nn.Linear(16, 1),
            ))

    def forward(self, x: torch.Tensor):
        # x: (B, T=100, F=12)
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)

        # Each branch → (B, 32). Stack to (B, 8, 32).
        per_head = [getattr(self, f"{n}_branch")(h) for n in self.HEADS]
        H = torch.stack(per_head, dim=1)            # (B, 8, 32)

        # Appliance-wise attention with residual + layernorm.
        attn_out, _ = self.attn(H, H, H, need_weights=False)
        H = self.attn_norm(H + attn_out)             # (B, 8, 32)

        # Per-head classifier on attended representation.
        outs = []
        for i, n in enumerate(self.HEADS):
            logits = getattr(self, f"{n}_clf")(H[:, i, :])   # (B, 1)
            outs.append(torch.sigmoid(logits).squeeze(-1))
        return tuple(outs)


if __name__ == "__main__":
    model = Panel3NetAttn()
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Panel3NetAttn parameters: {n_params:,}")
    x = torch.randn(2, 100, 12)
    outs = model(x)
    print(f"forward(2, 100, 12) → tuple of {len(outs)} tensors, each shape {outs[0].shape}")
