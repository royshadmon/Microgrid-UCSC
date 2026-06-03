"""Panel 2 NILM -- MATNilm-style encoder + 2DMA decoder.

Heads:
  - water_heater   (raw-power, 2-4 kW)
  - hair_dryer     (raw-power, 1.1-1.9 kW bursts)
  - sprinklers     (baseline-step, AM/PM windows)
  - bath_lights    (baseline-step, evening windows)

~9.4k training windows justifies the document's recommended ceiling for a
single-house deployment: d_model=128, n_heads=4, 3 decoder blocks.

This shares the TwoDMABlock implementation with Panel 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_panel1_matnilm import PositionalEncoding, TwoDMABlock  # noqa: E402


class Panel2MATNilm(nn.Module):
    HEADS = ("water_heater", "hair_dryer", "sprinklers", "bath_lights")

    def __init__(
        self,
        in_features: int = 12,
        d_model: int = 128,
        n_heads: int = 4,
        n_encoder_layers: int = 3,
        n_decoder_blocks: int = 3,
        dropout: float = 0.15,
        window: int = 100,
        mid: int = 50,
    ):
        super().__init__()
        self.window = window
        self.mid = mid
        self.n_appliances = len(self.HEADS)

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

        self.app_embed = nn.Parameter(torch.randn(self.n_appliances, d_model) * 0.02)

        self.decoder = nn.ModuleList(
            [TwoDMABlock(d_model, n_heads, dropout) for _ in range(n_decoder_blocks)]
        )

        self.classifier = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1),
        )

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
        slice_mid = dec[:, mid_idx, :, :]
        logits = self.classifier(slice_mid).squeeze(-1)
        probs = torch.sigmoid(logits)
        return tuple(probs[:, i] for i in range(self.n_appliances))
