import torch, numpy as np
from torch import nn

class NormalizedNet(nn.Module):
    def __init__(self, state_shape, action_shape):
        super().__init__()
        self.model = nn.Sequential(
            nn.BatchNorm1d(np.prod(state_shape)),
            nn.Linear(np.prod(state_shape), 256), nn.ReLU(inplace=True),
            nn.BatchNorm1d(256),
            nn.Linear(256, 128), nn.ReLU(inplace=True),
            nn.Linear(128, np.prod(action_shape)),
        )

    def forward(self, obs, state=None, info={}):
        if not isinstance(obs, torch.Tensor):
            obs = torch.tensor(obs, dtype=torch.float)
        batch = obs.shape[0]
        logits = self.model(obs.view(batch, -1))
        return logits, state
