import torch
import logging
import time
import numpy as np
import json
import io

from RewardOpti import RewardOpti
from agents.Agent import DQNAgent
from Preprocessing import Preprocessing
import utils

from agents.SAC import SoftActorCritic

from Memory import SACDataset
from agents.config import config as agent_config

Logger = logging.getLogger("NeuralPlayer")
Logger.setLevel(logging.INFO)
stream = logging.StreamHandler()
Logger.addHandler(stream)


class NeuralPlayer():
	def __init__(self, config, env, simulator):
		print("Start init NeuralPlayer")
		self.sac = True
		self.config = config
		self.env = env
		self.agent =  None
		self.preprocessor = None
		self.simulator = simulator
		self._init_agent(config.config_Agent)
		self._init_preprocessor(config.config_Preprocessing)
		self._init_reward_optimizer(self.config)
		self.scores = []
		# self._save_config()
		print("End init NeuralPlayer")


	def _init_preprocessor(self, config_Preprocessing):
		self.preprocessor = Preprocessing(config = config_Preprocessing)


	def _init_agent(self, config_Agent):
		if self.sac:
			self.agent = SoftActorCritic(agent_config)
		else:
			self.agent = DQNAgent(config=config_Agent)

  
	def _init_reward_optimizer(self, config_NeuralPlayer):
		self.RO = RewardOpti(config_NeuralPlayer)


	def _train_agent(self):
		self.agent.train()
	
	
	def _save_config(self):
		if self.agent.conf_data.saving_frequency > 0:
			config_dictionnary = {}
			for info in self.config:
				config_dictionnary[info] = self.config[info]
			file_name = f"{self.agent.conf_data.model_to_save_name}{self.agent.conf_data.config_extension}"
			if self.agent.conf_data.S3_connection == True:
				conf_path = f"{self.agent.S3.config.model_folder}{file_name}"
				json_obj = json.dumps(config_dictionnary).encode('UTF-8')
				bytes_obj = io.BytesIO(json_obj)
				bytes_obj.seek(0)
				self.agent.S3.upload_bytes(bytes_obj, conf_path)
			else:
				conf_path = f"{self.agent.conf_data.local_model_folder}{file_name}"
				with open(conf_path, "w") as f:
					json.dump(config_dictionnary, f)
				
			


	def train_agent_from_SimCache(self):
		Logger.info(f"Training agent from SimCache database")
		simcache = self.agent.SimCache
		while simcache.loading_counter < simcache.nb_files_to_load:
			path = simcache.folder + simcache.list_files[simcache.loading_counter]
			self.agent.SimCache.load(path)
			
			for datapoint in self.agent.SimCache.data:
				state, action, new_state, reward, done, infos = datapoint
				done = self._is_over_race(infos, done)
				reward = self.RO.sticks_and_carrots(action, infos, done)
				[action, reward] = utils.to_numpy_32([action, reward])
				processed_state, new_processed_state = self.preprocessor.process(state), self.preprocessor.process(new_state)
				self.agent.memory.add(processed_state, action, new_processed_state, reward, done)

			if (len(self.agent.memory) >= self.agent.config.memory_size):
				for _ in range(self.config.replay_memory_batches):
					self.agent.replay_memory()
			
			if (self.agent.conf_data.saving_frequency != 0):
				self.agent.save_modelo(f"{self.agent.conf_data.model_to_save_name}_simcache_{simcache.loading_counter}", self.config)
			

	def _is_over_race(self, infos, done):
		cte = infos["cte"]
		cte_corr = cte + self.config.cte_offset
		if (done):
			return True

		if (abs(cte) > 100):
			return True
		
		if (abs(cte_corr) > self.config.cte_limit):
			return True

		return False


	def get_action(self, state):
		return self.agent.get_action(self.preprocessor.process(state))


	def add_score(self, iteration):
		self.scores.append(iteration)


	def do_races_ddqn(self, episodes):
		Logger.info(f"Doing {episodes} races.")
		for e in range(1, episodes + 1):
			Logger.info(f"\nepisode {e}/{episodes}")
			print(f"memory size = {len(self.agent.memory)}")
			self.RO.new_race_init(e)
			
			self.simulator = utils.fix_cte(self.simulator)
			self.env = self.simulator.env

			state, reward, done, infos = self.env.step([0, 0])
			processed_state = self.preprocessor.process(state)
			done = self._is_over_race(infos, done)
			Logger.debug(f"Initial CTE: {infos['cte']}")
			iteration = 0
			while (not done):

				action = self.agent.get_action(processed_state, e)
				Logger.debug(f"action: {action}")
				new_state, reward, done, infos = self.env.step(action)
				self.agent.add_simcache_point([state, action, new_state, reward, done, infos])
				new_processed_state = self.preprocessor.process(new_state)
				done = self._is_over_race(infos, done)
				reward = self.RO.sticks_and_carrots(action, infos, done)
				[action, reward] = utils.to_numpy_32([action, reward])
				self.agent.memory.add(processed_state, action, new_processed_state, reward, done)
				processed_state = new_processed_state
				Logger.debug(f"cte:{infos['cte'] + 2.25}")
				iteration += 1
			
			self.add_score(iteration)
			self.agent._update_epsilon()
			if (e % self.config.replay_memory_freq == 0):
				for _ in range(self.config.replay_memory_batches):
					self.agent.replay_memory()
					pass


			if (self.agent.conf_data.saving_frequency != 0 and
				(e % self.agent.conf_data.saving_frequency == 0 or e == self.config.episodes)):
				self.agent.save_modelo(f"{self.agent.conf_data.model_to_save_name}{e}")
		
		self.agent.SimCache.upload()
		self.env.reset()
		return

	def do_races_sac(self, episodes):
		memory = SACDataset()
		print(f"Doing {episodes} races.")
		scores = []
		for e in range(1, episodes + 1):
			print(f"\nepisode {e}/{episodes}")
			# print(f"memory size = {len(self.agent.memory)}")
			self.RO.new_race_init(e)
			
			self.simulator = utils.fix_cte(self.simulator)
			self.env = self.simulator.env

			state, reward, done, infos = self.env.step([0, 0])
			processed_state = self.preprocessor.process(state)
			done = self._is_over_race(infos, done)
			print(f"Initial CTE: {infos['cte']}")
			iteration = 0
			while (not done):

				action = self.agent.get_action(processed_state)[0].numpy()
				# print(f"True {action = }")
				# print(f"action: st {int(action[0] * 100)/100:7.2} th {(action[1] * 100)/100:7.2}")
				new_state, reward, done, infos = self.env.step(action)
				# self.agent.add_simcache_point([state, action, new_state, reward, done, infos])
				new_processed_state = self.preprocessor.process(new_state)
				# print(f"{new_processed_state.shape = }")
				done = self._is_over_race(infos, done)

				reward = self.RO.sticks_and_carrots(action, infos, done)

				# [action, reward] = utils.to_numpy_32([action, reward])

				# print(f"{new_processed_state[0].shape = }")
				# print(f"{action = }")
				current_action = torch.tensor(action)
				# print(f"{current_action = }")
				memory.add(processed_state[0], current_action, new_processed_state[0], reward, int(done))

				processed_state = new_processed_state
				# print(f"cte:{infos['cte'] + 2.25}")
				iteration += 1
			
			self.add_score(iteration)
			print(f"Episode len: {self.scores[-1]}")

			if (e % self.config.replay_memory_freq == 0):

				print("Training")
				# scores.append(len(memory))
				if self.agent.train(memory):
					memory = SACDataset()
				print(self.scores)
		
		self.env.reset()
		return

	def do_races(self, episodes):
		if self.sac:
			self.do_races_sac(episodes)
		else:
			self.do_races_ddqn(episodes)
