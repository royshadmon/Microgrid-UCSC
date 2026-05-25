"""Panel 1 NILM — MATNilm-style encoder + 2DMA decoder.

Heads:
  - heat_pump
  - solar_pump

Architecture follows Xue et al. 2DMA:
  Encoder: Conv stem + multi-head temporal Transformer (shared representation).
  Decoder: per-appliance representation, then alternating temporal & appliance-
           wise multi-head attention (the 2DMA block).
  Heads:   per-appliance Linear -> sigmoid (classification only;
           regression branch omitted because labels are ON/OFF only).

Sized down because Panel 1 has ~991 labeled windows: d_model=64, n_heads=4,
2 decoder blocks. Document guidance: stay below 8 heads, 3 layers, d_model=128
until labeled validation has ~5000+ positives per head.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn


class PositionalEncoding(nn.Module):
    """Sinusoidal positional encoding added to the encoder input."""

    def __init__(self, d_model: int, max_len: int = 256):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len, dtype=torch.float32).unsqueeze(1)
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1)]


class TwoDMABlock(nn.Module):
    """Two-Dimensional Multi-head Attention.

    Input/output: (B, T, N, D). Temporal attention then appliance-wise
    attention, each with residual + LayerNorm. FFN last.
    """

    def __init__(self, d_model: int = 64, n_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.temp_attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.app_attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.ln1 = nn.LayerNorm(d_model)
        self.ln2 = nn.LayerNorm(d_model)
        self.ln3 = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, 4 * d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * d_model, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        b, t, n, d = h.shape

        # Temporal attention: attend across T for each appliance
        ht = h.permute(0, 2, 1, 3).reshape(b * n, t, d)
        ht_out, _ = self.temp_attn(ht, ht, ht)
        ht = self.ln1(ht + ht_out)
        h = ht.reshape(b, n, t, d).permute(0, 2, 1, 3)

        # Appliance-wise attention: attend across N for each timestep
        ha = h.reshape(b * t, n, d)
        ha_out, _ = self.app_attn(ha, ha, ha)
        ha = self.ln2(ha + ha_out)
        h = ha.reshape(b, t, n, d)

        # FFN with residual
        h = self.ln3(h + self.ffn(h))
        return h


class Panel1MATNilm(nn.Module):
    """MATNilm-style network for Panel 1 (heat_pump, solar_pump)."""

    HEADS = ("heat_pump", "solar_pump")

    def __init__(
        self,
        in_features: int = 12,
        d_model: int = 64,
        n_heads: int = 4,
        n_encoder_layers: int = 2,
        n_decoder_blocks: int = 2,
        dropout: float = 0.1,
        window: int = 100,
        mid: int = 50,
    ):
        super().__init__()
        self.window = window
        self.mid = mid
        self.n_appliances = len(self.HEADS)

        # Encoder: conv stem + temporal transformer
        self.input_proj = nn.Conv1d(in_features, d_model, kernel_size=5, padding=2)
        self.input_bn = nn.BatchNorm1d(d_model)
        self.input_drop = nn.Dropout(dropout)
        self.pos_enc = PositionalEncoding(d_model, max_len=window + 16)

        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=4 * d_model,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
            norm_first=False,
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_encoder_layers)

        # Appliance embeddings (learned per-head representation)
        self.app_embed = nn.Parameter(torch.randn(self.n_appliances, d_model) * 0.02)

        # Decoder: stacked 2DMA blocks
        self.decoder = nn.ModuleList(
            [TwoDMABlock(d_model, n_heads, dropout) for _ in range(n_decoder_blocks)]
        )

        # Per-head classifier
        self.classifier = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1),
        )

    def forward(self, x: torch.Tensor):
        b, t, _ = x.shape

        # Encoder
        h = self.input_proj(x.transpose(1, 2))
        h = self.input_bn(h)
        h = torch.relu(h)
        h = self.input_drop(h)
        h = h.transpose(1, 2)
        h = self.pos_enc(h)
        enc = self.encoder(h)

        # Broadcast to (B, T, N, D) + appliance embedding
        dec = enc.unsqueeze(2).expand(b, t, self.n_appliances, enc.size(-1)).contiguous()
        dec = dec + self.app_embed.view(1, 1, self.n_appliances, -1)

        # 2DMA decoder stack
        for block in self.decoder:
            dec = block(dec)

        # Mid-window slice -> classify
        mid_idx = min(self.mid, t - 1)
        slice_mid = dec[:, mid_idx, :, :]
        logits = self.classifier(slice_mid).squeeze(-1)
        probs = torch.sigmoid(logits)
        return tuple(probs[:, i] for i in range(self.n_appliances))
