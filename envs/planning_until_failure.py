from typing import Tuple
import gymnasium as gym

from agents.base_planning import BasePlanningAgent
from utils.diarc_json_utils import generate_diarc_json_from_state

from .single_agent import SingleAgentEnv

REWARDS = {
    "positive": 1000,
    "negative": -250,
    "step": -1,
}


class PlanningUntilFailureEnv(SingleAgentEnv):
    """
    An environment where given the pddl domains,
    it will execute the plan until an action failed, or until it's unable to plan.
    then the environment steps will start.

    Failure is denoted by the agent setting its stuck flag to True.
    """
    metadata = {"render_modes": ["human"]}
    
    def _fast_forward(self):
        # fast forward the environment until the agent in interest is reached.
        agent = self.env.agent_selection
        while agent != self.agent_name or \
              not getattr(self.env.agent_manager.agents[agent].agent, "stuck", False):
            if len(self.env.dones) == 0 or (agent == self.agent_name and self.env.dones[agent]):
                # episode is done, restart a new episode.
                if self.env.enable_render:
                    print("------Episode is finished internally.------")
                return False
            if agent not in self.env.dones or self.env.dones[agent]:
                # skips the process if agent is not the main agent and is done.
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
        if self.show_action_log:
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
        
        json_input = {
            "state": diarc_json,
            "domain": main_agent.pddl_domain,
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

        # case 2: unplannable mode, replan straight away
        if failed_action == "cannotplan":
            plan_found = main_agent.plan()
            if plan_found:
                # case 2.1, plan found. give positive reward and quit
                return True, False, REWARDS['positive']
            else:
                return False, False, REWARDS['step']


        # case 3: failed action mode. firstly check if effects met, then replan and assign rewards
        diarc_json = generate_diarc_json_from_state(
            player_id=self.player_id,
            state=self.env.internal_state,
            dynamic=self.env.dynamic,
            failed_action=failed_action,
            success=False,
        )
        effects_met = self.rep_gen.check_if_effects_met(diarc_json)
        # case 3.1: effects not met, return step reward and continue
        if not (effects_met[0] or effects_met[1]):
            return False, False, REWARDS['step']
        else:
            plan_found = main_agent.plan()
            if plan_found:
                # case 3.2, effects met, plannable
                return True, False, REWARDS['positive']
            else:
                # case 3.3, effects met, unplannable
                return True, False, REWARDS['negative']