import gymnasium as gym
import numpy as np

        
class ObservationGenerator:
    def __init__(self):
        pass
    
    @staticmethod
    def get_observation_space(self, *args, **kwargs):
        return gym.spaces.Discrete(1)
    
    def generate_observation(self, json_input: dict) -> np.ndarray:
        return [0]