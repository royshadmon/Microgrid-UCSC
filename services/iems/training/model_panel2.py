"""Panel 2 NILM — Conv + per-head BiLSTM branches.

Four heads, untied so each appliance can specialize:
  - water_heater   (raw-power, 2–4 kW)
  - hair_dryer     (raw-power, 1.1–1.9 kW bursts)
  - sprinklers     (baseline-step, AM/PM windows)
  - bath_lights    (baseline-step, evening windows)
"""
from __future__ import annotations

import torch
import torch.nn as nn


class HeadBranch(nn.Module):
    """Per-head BiLSTM stack + MLP."""

    def __init__(self, in_dim: int = 32):
        super().__init__()
        self.lstm1 = nn.LSTM(in_dim, 32, batch_first=True, bidirectional=True)
        self.lstm2 = nn.LSTM(64, 16, batch_first=True, bidirectional=True)
        self.head = nn.Sequential(
            nn.Dropout(0.2),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        h, _ = self.lstm1(h)
        h, _ = self.lstm2(h)
        h = h[:, -1, :]
        return torch.sigmoid(self.head(h)).squeeze(-1)


class Panel2Net(nn.Module):
    HEADS = (
        "water_heater",
        "hair_dryer",
        "sprinklers",
        "bath_lights",
    )

    def __init__(self, in_features: int = 12):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_features, 32, kernel_size=5, padding=2),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.Dropout(0.1),
        )
        for name in self.HEADS:
            setattr(self, f"{name}_branch", HeadBranch())

    def forward(self, x: torch.Tensor):
        # x: (B, T=100, F=12)
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)
        return tuple(getattr(self, f"{n}_branch")(h) for n in self.HEADS)
