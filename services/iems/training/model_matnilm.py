"""Canonical MATNilm (2DMA) with dual regression+classification heads.

One configurable module shared by all panels. Follows Xiong et al.
(arXiv:2307.14778) MAT architecture:

  Encoder  : Conv stem + Transformer encoder -> shared temporal representation.
  Decoder  : per-appliance branch (shared rep + learned appliance embedding),
             stacked 2DMA blocks. Each 2DMA block applies multi-head attention
             across TIME (temporal) then across APPLIANCES (appliance-wise),
             each with residual + LayerNorm, then a position-wise FFN.
  Heads    : last block splits per appliance into
               - classification head: Linear -> sigmoid  => o_hat  (on/off)
               - regression head    : Linear -> ReLU     => p_hat  (kW)
             Final disaggregated power is the subtask-gated y_hat = p_hat * o_hat.

forward(x) returns a flat tuple: (prob_0..prob_{N-1}, pow_0..pow_{N-1}).
Powers are in kW (targets are divided by 1000 at train time).
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn


class PositionalEncoding(nn.Module):
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
    """Two-Dimensional Multi-head Attention. Input/output (B, T, N, D)."""

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
        # Temporal attention: across T for each appliance
        ht = h.permute(0, 2, 1, 3).reshape(b * n, t, d)
        ht_out, _ = self.temp_attn(ht, ht, ht)
        ht = self.ln1(ht + ht_out)
        h = ht.reshape(b, n, t, d).permute(0, 2, 1, 3)
        # Appliance-wise attention: across N for each timestep (co-occurrence axis)
        ha = h.reshape(b * t, n, d)
        ha_out, _ = self.app_attn(ha, ha, ha)
        ha = self.ln2(ha + ha_out)
        h = ha.reshape(b, t, n, d)
        # FFN with residual
        h = self.ln3(h + self.ffn(h))
        return h


class MATNilm(nn.Module):
    """Configurable MATNilm 2DMA network with dual heads, shared by all panels."""

    def __init__(
        self,
        heads: tuple[str, ...],
        in_features: int = 13,
        d_model: int = 128,
        n_heads: int = 4,
        n_encoder_layers: int = 3,
        n_decoder_blocks: int = 3,
        dropout: float = 0.15,
        window: int = 100,
        mid: int = 50,
    ):
        super().__init__()
        self.heads = tuple(heads)
        self.n_appliances = len(self.heads)
        self.window = window
        self.mid = mid

        self.input_proj = nn.Conv1d(in_features, d_model, kernel_size=5, padding=2)
        self.input_bn = nn.BatchNorm1d(d_model)
        self.input_drop = nn.Dropout(dropout)
        self.pos_enc = PositionalEncoding(d_model, max_len=window + 16)

        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=4 * d_model,
            dropout=dropout, batch_first=True, activation="gelu", norm_first=False,
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_encoder_layers)

        self.app_embed = nn.Parameter(torch.randn(self.n_appliances, d_model) * 0.02)
        self.decoder = nn.ModuleList(
            [TwoDMABlock(d_model, n_heads, dropout) for _ in range(n_decoder_blocks)]
        )

        def _head():
            return nn.Sequential(
                nn.LayerNorm(d_model),
                nn.Linear(d_model, d_model // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(d_model // 2, 1),
            )

        # Independent per-appliance classification and regression heads.
        self.cls_heads = nn.ModuleList([_head() for _ in range(self.n_appliances)])
        self.reg_heads = nn.ModuleList([_head() for _ in range(self.n_appliances)])

    def forward(self, x: torch.Tensor):
        b, t, _ = x.shape
        h = self.input_proj(x.transpose(1, 2))
        h = self.input_bn(h)
        h = torch.relu(h)
        h = self.input_drop(h)
        h = h.transpose(1, 2)
        h = self.pos_enc(h)
        enc = self.encoder(h)

        dec = enc.unsqueeze(2).expand(b, t, self.n_appliances, enc.size(-1)).contiguous()
        dec = dec + self.app_embed.view(1, 1, self.n_appliances, -1)
        for block in self.decoder:
            dec = block(dec)

        mid_idx = min(self.mid, t - 1)
        slice_mid = dec[:, mid_idx, :, :]  # (B, N, D)

        probs, powers = [], []
        for i in range(self.n_appliances):
            feat = slice_mid[:, i, :]
            probs.append(torch.sigmoid(self.cls_heads[i](feat)).squeeze(-1))
            powers.append(torch.relu(self.reg_heads[i](feat)).squeeze(-1))  # kW
        return tuple(probs) + tuple(powers)
