from typing import Tuple
import gymnasium as gym

from gym_novel_gridworlds2.envs.sequential import NovelGridWorldSequentialEnv
from gym_novel_gridworlds2.utils.json_parser import ConfigParser, load_json
from agents.base_planning import BasePlanningAgent
from utils.diarc_json_utils import generate_diarc_json_from_state
from utils.pddl_utils import generate_obj_types, generate_pddl
from obs_convertion import LidarAll

REWARDS = {
    "positive": 1000,
    "negative": -250,
    "step": -1,
}


class SAPolycraftRL(gym.Wrapper):
    metadata = {"render_modes": ["human"]}
    def __init__(
            self, 
            config_file_paths, 
            agent_name, 
            task_name="", 
            show_action_log=False, 
            RepGenerator=LidarAll,
            rep_gen_args={},
            enable_render=False
        ):
        config_content = load_json(config_json={"extends": config_file_paths}, verbose=False)
        self.config_content = config_content

        self.player_id = 0

        self.env = NovelGridWorldSequentialEnv(
            config_dict=config_content, 
            max_time_step=None, 
            time_limit=None,
            enable_render=enable_render,
            run_name=task_name,
            logged_agents=['main_1'] if show_action_log else []
        )
        self.show_action_log = show_action_log
        self.env.dynamic.all_objects = generate_obj_types(self.config_content)
        self.agent_name = agent_name

        self.RepGeneratorModule = RepGenerator
        self.rep_gen_args = rep_gen_args
        self.rep_gen = None
        self.items_lidar_disabled = []

        self._action_space = None
        self._observation_space = None

        self.episode = -1

    
    @property
    def observation_space(self):
        if self._observation_space is None:
            return self.RepGeneratorModule.get_observation_space(
                self.env.dynamic.all_objects,
                **self.rep_gen_args
            )
        else:
            return self._observation_space
    

    @property
    def action_space(self):
        if self._action_space is None:
            action_set = self.env.agent_manager.agents['agent_0'].action_set
            action_set_rl = [action for action, _ in action_set.actions if action not in ["nop", "give_up"]]
            self._action_space = gym.spaces.Discrete(len(action_set_rl))
        return self._action_space

    
    def _fast_forward(self):
        # fast forward the environment until the agent in interest is reached.
        agent = self.env.agent_selection
        while agent != self.agent_name or not getattr(self.env.agent_manager.agents[agent].agent, "stuck", False):
            if len(self.env.dones) == 0:
                # episode is done, restart a new episode.
                print("------Episode is complete without RL.------")
                return False
            if agent not in self.env.dones or self.env.dones[agent]:
                # skips the process if agent is done.
                self.env.step(0, {})
            else:
                obs, reward, done, info = self.env.last()
                action = self.env.agent_manager.agents[agent].agent.policy(obs)
                            # getting the actions
                extra_params = {}
                if type(action) == tuple:
                    # symbolic agent sending extra params
                    action, extra_params = action
                else:
                    # rl agent / actions with no extra params
                    action = action

                self.env.step(action, extra_params)
            agent = self.env.agent_selection
        
        return True


    def _init_obs_gen(self):
        """
        Initialize the observation generator.
        """
        main_agent: BasePlanningAgent = self.env.agent_manager.agents["agent_0"].agent
        main_agent.verbose = True
        failed_action = main_agent.failed_action
        action_set = self.env.agent_manager.agents['agent_0'].action_set

        if type(failed_action) == tuple:
            failed_action = "(" + " ".join(failed_action[1]) + ")"
        
        diarc_json = generate_diarc_json_from_state(
            player_id=self.player_id,
            state=self.env.internal_state,
            dynamic=self.env.dynamic,
            failed_action=failed_action,
            success=False,
        )
        self.pddl_domain, self.pddl_problem = generate_pddl(
            ng2_config=self.config_content,
            state=self.env.internal_state,
            dynamics=self.env.dynamic,
        )
        
        json_input = {
            "state": diarc_json,
            "domain": self.pddl_domain,
            "plan": main_agent.pddl_plan,
            "novelActions": [],
            "actionSet": [action[0] for action in action_set.actions if action not in ["nop", "give_up"]],
        }
        self.rep_gen = self.RepGeneratorModule(
            json_input=json_input, 
            items_lidar_disabled=self.items_lidar_disabled,
            RL_test=True,
            **self.rep_gen_args
        )


    def _gen_obs(self):
        """
        Generate the observation.
        """
        main_agent = self.env.agent_manager.agents["agent_0"].agent
        failed_action = main_agent.failed_action
        diarc_json = generate_diarc_json_from_state(
            player_id=self.player_id,
            state=self.env.internal_state,
            dynamic=self.env.dynamic,
            failed_action=failed_action,
            success=False,
        )
        return self.rep_gen.generate_observation(diarc_json)


    def _gen_reward(self) -> Tuple[bool, bool, float]:
        """
        done, truncated, reward
        """
        # case 1: is done
        if self.env.internal_state._goal_achieved:
            return True, False, REWARDS["positive"]
        elif self.env.internal_state._given_up:
            return True, False, REWARDS["negative"]
        elif self.env.dones["agent_0"]:
            return False, True, REWARDS["step"]
        
        # not done, check if effects met
        main_agent: BasePlanningAgent = self.env.agent_manager.agents["agent_0"].agent
        failed_action = main_agent.failed_action
        diarc_json = generate_diarc_json_from_state(
            player_id=self.player_id,
            state=self.env.internal_state,
            dynamic=self.env.dynamic,
            failed_action=failed_action,
            success=False,
        )
        effects_met = self.rep_gen.check_if_effects_met(diarc_json)
        # case 2: effects not met, return step reward and continue
        if not (effects_met[0] or effects_met[1]):
            return False, False, REWARDS['step']
        else:
            plan_found = main_agent.plan()
            if plan_found:
                # case 3, effects met, plannable
                return True, False, REWARDS['positive']
            else:
                return True, False, REWARDS['negative']

    def step(self, action):
        # run the agent in interest
        self.env.step(action, {})

        # run another step of other agents using the stored policy 
        # until the agent in interest is reached again.
        self._fast_forward()

        obs, reward, env_done, info = self.env.last()

        # get relevant info
        main_agent = self.env.agent_manager.agents["agent_0"].agent
        info = {
            "pddl_domain": self.pddl_domain,
            "pddl_problem": self.pddl_problem,
            "pddl_plan": main_agent.pddl_plan,
            **info
        }

        # check if effects met and give the rewards
        plannable_done, truncated, reward = self._gen_reward()

        # generate the observation
        obs = self._gen_obs()
        return obs, reward, env_done or plannable_done, truncated, info

    def reset(self, seed=None, options={}):
        # reset the environment
        needs_rl = False
        main_agent = self.env.agent_manager.agents["agent_0"].agent
        main_agent._reset()
        if self.show_action_log:
            main_agent.verbose = True


        while not needs_rl:
            self.episode += 1
            self.env.reset(options={"episode": self.episode})
            self.env.dynamic.all_objects = generate_obj_types(self.config_content)
            
            # fast forward
            self._agent_iter = self.env.agent_iter()

            needs_rl = self._fast_forward()
        obs, reward, done, info = self.env.last()
        info = {
            "pddl_domain": getattr(self, "pddl_domain", ""),
            "pddl_problem": getattr(self, "pddl_problem", ""),
            "pddl_plan": getattr(main_agent, "pddl_plan", ""),
            **info
        }

        # initialize the observation generator
        self._init_obs_gen()

        # get the observation
        obs = self._gen_obs()
        return obs, {}

