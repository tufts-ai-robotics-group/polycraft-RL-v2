
import os
import argparse
from envs.polycraft_simplified import SAPolycraftRL
from shutil import rmtree
import tianshou as ts
import gymnasium as gym
from net.basic import BasicNet
import torch
from torch.utils.tensorboard import SummaryWriter
from tianshou.utils import TensorboardLogger

parser = argparse.ArgumentParser(description="Polycraft Gym Environment")
# parser.add_argument("filename", type=str, nargs='+', help="The path of the config file.", default="polycraft_gym_main.json")
parser.add_argument(
    "-n",
    "--episodes",
    type=int,
    help="The number of episodes.",
    required=False,
    default=1000
)
parser.add_argument(
    "--exp_name",
    type=str, 
    help="The name of the experiment.", 
    required=False,
    default="main"
)
parser.add_argument(
    '--rendering',
    type=str,
    help="The rendering mode.",
    required=False,
    default="human"
)
parser.add_argument(
    '--seed',
    type=str,
    help="The seed.",
    required=False,
    default=None
)
parser.add_argument(
    '--num_threads',
    type=int,
    help="Number of sub threads used to run the env.",
    required=False,
    default=4
)
parser.add_argument(
    '--reset_rl',
    action=argparse.BooleanOptionalAction,
    help="Whether to reset the RL agent and remove the existing models.",
    required=False,
    default=False
)
parser.add_argument(
    '--agent',
    type=str,
    help="The agent module of the first agent.",
    required=False
)
parser.add_argument(
    '--logdir',
    type=str,
    help="The directory to save the logs.",
    required=False,
    default="results"
)

verbose = False

args = parser.parse_args()


if __name__ == "__main__":
    num_episodes = args.episodes

    exp_name = args.exp_name
    agent = args.agent
    seed = args.seed
    reset_rl = args.reset_rl

    log_path = os.path.join(args.logdir, args.exp_name, "dqn")
    writer = SummaryWriter(log_path)
    writer.add_text("args", str(args))
    logger = TensorboardLogger(writer)


    if reset_rl:
        try:
            rmtree(os.path.join(os.path.dirname(__file__), "agents", "rl_subagents", "rapid_learn_utils", "policies"))
        except:
            print("No existing RL policies to reset.")

    # change agent
    # if agent is not None:
    #     config_content["entities"]["main_1"]["agent"] = agent


    # env = SAPolycraftRL(
    #     config_file_paths=config_file_paths,
    #     agent_name="agent_0",
    #     task_name="main",
    #     show_action_log=True
    # )

    config_file_paths = ["config/polycraft_gym_rl_single.json"]
    config_file_paths.append("novelties/evaluation1/multi_interact/multi_interact.json")

    envs = [lambda: gym.make(
        "NG2-PolycraftMultiInteract-v0",
        config_file_paths=config_file_paths,
        agent_name="agent_0",
        task_name="main",
        show_action_log=False
    ) for _ in range(args.num_threads)]
    # tianshou env
    venv = ts.env.SubprocVectorEnv(envs)

    state_shape = venv.observation_space[0].shape or venv.observation_space[0].n
    action_shape = venv.action_space[0].shape or venv.action_space[0].n
    net = BasicNet(state_shape, action_shape)
    optim = torch.optim.Adam(net.parameters(), lr=1e-3)
    policy = ts.policy.DQNPolicy(net, optim, discount_factor=0.99, estimation_step=3)

    train_collector = ts.data.Collector(policy, venv, ts.data.VectorReplayBuffer(20000, 10), exploration_noise=True)
    test_collector = ts.data.Collector(policy, venv, exploration_noise=True)

    # train_collector.collect(n_step=5000, random=True)
    # print("Done Collecting Experience. Starting Training...")


    # policy.set_eps(0.1)

    # for i in range(int(1e6)):
    #     collect_result = train_collector.collect(n_step=10)

    #     # once if the collected episodes' mean returns reach the threshold,
    #     # or every 1000 steps, we test it on test_collector
    #     if collect_result['rews'].mean() >= env.spec.reward_threshold or i % 1000 == 0:
    #         policy.set_eps(0.05)
    #         result = test_collector.collect(n_episode=100)
    #         print("episode:", i, "  test_reward:", result['rews'].mean())
    #         if result['rews'].mean() >= env.spec.reward_threshold:
    #             print(f'Finished training! Test mean returns: {result["rews"].mean()}')
    #             break
    #         else:
    #             # back to training eps
    #             policy.set_eps(0.1)

    #     # train policy with a sampled batch data from buffer
    #     losses = policy.update(64, train_collector.buffer)

def set_train_eps(epoch, env_step):
    max_eps = 0.4
    min_eps = 0.1
    if epoch > 10:
        return min_eps
    else:
        return max_eps - (max_eps - min_eps) / 10 * epoch

result = ts.trainer.offpolicy_trainer(
    policy, train_collector, test_collector,
    max_epoch=100, step_per_epoch=1000, step_per_collect=10,
    update_per_step=0.1, episode_per_test=50, batch_size=64,
    train_fn=set_train_eps,
    test_fn=lambda epoch, env_step: policy.set_eps(0.05),
    stop_fn=lambda mean_rewards: mean_rewards >= venv.spec[0].reward_threshold,
    logger=logger
)
print(f'Finished training! Use {result["duration"]}')