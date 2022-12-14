# Needed for training the network
import numpy as np
import tensorflow as tf
import tensorflow.keras as keras
import tensorflow.keras.layers as layers
import tensorflow.keras.initializers as initializers
import math
# from keras.layers import Dropout

class GaussianPolicy():
	"""
		Inspiration from: https://towardsdatascience.com/a-minimal-working-example-for-continuous-policy-gradients-in-tensorflow-2-0-d3413ec38c6b
			Tutorial written the 18th of Aug 2020
	"""

	def __init__(self, input_shape=(1,),
					bias_mu_throttle=0.5,
					bias_mu_steering=0.0,
					bias_sigma_throttle=0.03, # ~1% outside (0.5 +- 0.4)
					bias_sigma_steering=0.1, # ~2% outside (0 +- 0.9)
					learning_rate=0.001):
		"""
			Summary:
				In the continuous variant, we usually draw actions from a Gaussian distribution;
				The goal is to learn an appropriate mean μ and a standard deviation σ

				Once obtaining this output (μ and σ), an action a is randomly drawn from the corresponding Gaussian distribution.
				Thus, we have a=μ(s)+σ(s)ξ , where ξ ∼ 𝒩(0,1).

			Args:
				input_shape ([type]):
					The input is the state s 
						or
					a feature array ϕ(s), followed by one or more hidden layers that transform the input
				output_size ([type]):
					The output being μ and σ
		"""
		# Create actor network
		# bias 0.0 yields mu=0.0 with linear activation function
		self.bias_mu_throttle = bias_mu_throttle
		self.bias_mu_steering = bias_mu_steering
		# bias 0.55 yields sigma=1.0 with softplus activation function
		self.bias_sigma_throttle = bias_sigma_throttle
		self.bias_sigma_steering = bias_sigma_steering

		self.lr = learning_rate

		self.actor_network = self.build_model(
                   				input_shape,  # input dimension is (1,) for testor
               					bias_mu_throttle=self.bias_mu_throttle,
               					bias_mu_steering=self.bias_mu_steering,
               					bias_sigma_throttle=self.bias_sigma_throttle,
               					bias_sigma_steering=self.bias_sigma_steering)

		self.opt = keras.optimizers.Adam(learning_rate=self.lr)
		self.actor_network.compile(loss='mse', optimizer=self.opt)
		self.actor_network.summary()

		# For debugging purposes
		self.loss_ = 0
		self.mu_throttle = 0
		self.sigma_throttle = 0
		self.mu_steering = 0
		self.sigma_steering = 0

	def build_model(self,
					input_shape,
					number_of_layers=5,
					neurons_by_layers=10,
					bias_mu_throttle=0.5,
					bias_mu_steering=0.0,
					bias_sigma_throttle=0.03, # ~1% outside (0.5 +- 0.4)
					bias_sigma_steering=0.1, # ~2% outside (0 +- 0.9)
					dropout=0.15):
		"""
			Construct the actor network with mu and sigma as output
		"""
		print(f"Input shape of policy: {input_shape}")
		inputs = layers.Input(shape=input_shape)

		prev_layer = inputs
		for i in range(number_of_layers):

			current_layer = layers.Dense(neurons_by_layers,
							activation="relu",
							kernel_initializer=initializers.he_normal())(prev_layer)
			if i < number_of_layers - 1:
				prev_layer = current_layer
				layers.Dropout(dropout)(prev_layer)
			prev_layer = current_layer

		current_layer = layers.Flatten()(prev_layer)

		mu_throttle = layers.Dense(1,
                    activation="linear",
                    kernel_initializer=initializers.Zeros(),
                    bias_initializer=initializers.Constant(bias_mu_throttle))(current_layer)

		sigma_throttle = layers.Dense(1,
                       activation="softplus",
                       kernel_initializer=initializers.Zeros(),
                       bias_initializer=initializers.Constant(bias_sigma_throttle))(current_layer)

		mu_steering = layers.Dense(1,
                    activation="linear",
                    kernel_initializer=initializers.Zeros(),
                    bias_initializer=initializers.Constant(bias_mu_steering))(current_layer)

		sigma_steering = layers.Dense(1,
                       activation="softplus",
                       kernel_initializer=initializers.Zeros(),
                       bias_initializer=initializers.Constant(bias_sigma_steering))(current_layer)


		actor_network = keras.Model(inputs=inputs, outputs=[mu_throttle, sigma_throttle, mu_steering, sigma_steering])

		return actor_network

	def choose_action(self, state, one=False, constrained=False):
		# Obtain mu and sigma from network
		print(f"state shape: {state.shape}")
		self.mu_throttle, self.sigma_throttle, self.mu_steering, self.sigma_steering = self.actor_network(state)
		print(f"sigma_throttle shape: {self.sigma_throttle.shape}")
		print(f"mu_throttle shape: {self.mu_throttle.shape}")
		print(f"sigma_steering shape: {self.sigma_steering.shape}")
		print(f"mu_steering shape: {self.mu_steering.shape}")

		# TODO: IT'S A QUICK FIX TO SEE IF IT WORKS -> WILL BREAK IN THE LONG TERM !!!!
		# if len(state.shape) == 4:
		# 	m = [1, state.shape[0]]
		# else:
		# 	m = [1]
		# Draw action from normal distribution
		action_throttle = tf.random.normal(self.mu_throttle.shape, mean=self.mu_throttle, stddev=self.sigma_throttle)
		action_steering = tf.random.normal(self.mu_throttle.shape, mean=self.mu_steering, stddev=self.sigma_steering)

		action_throttle = action_throttle.numpy().reshape(-1, 1)
		action_steering = action_steering.numpy().reshape(-1, 1)

		
		if constrained:
			sigmoid = lambda Z: 1 / (1 + np.exp(-Z))
			action_throttle = sigmoid(action_throttle)
			tanh = lambda Z: (np.exp(Z) - np.exp(-Z)) / (np.exp(Z) + np.exp(-Z))
			action_steering = tanh(action_steering)

		if one:
			return action_steering

		print(f"actions throt shape: {action_throttle.shape}")
		# print(f"actions shape: {action_steering.shape}")
		# actions = np.concatenate([action_throttle, action_steering], axis=1)
		# return actions
		return (action_throttle, action_steering)

	def policy_probability(self, s_t):
		a_t, a_s = self.choose_action(s_t)

		mu_t = self.mu_throttle
		si_t = self.sigma_throttle
		mu_s = self.mu_steering
		si_s = self.sigma_steering

		def prob_dis(x, m, s):
			#  $ f(x, \mu, \sigma) = \frac{1}{\sigma\sqrt{2\pi}}e ^\frac{-(x -\mu) ^ 2}{2\sigma ^ 2} $
			print(f"x.shape {tf.shape(x)}")
			print(f"mu.shape {tf.shape(m)}")
			print(f"sig.shape {tf.shape(s)}")
			pi = tf.constant(math.pi)
			sig_sqrt = s * tf.math.sqrt(2 * pi)
			print(f"sig_sqrt.shape {tf.shape(sig_sqrt)}")
			expo = tf.math.exp(- tf.math.pow(x - m, 2) / (2 * tf.math.pow(s, 2)))
			print(f"expo.shape {tf.shape(expo)}")
			return (1 / sig_sqrt) * expo 

		prob_t = prob_dis(a_t, mu_t, si_t)
		print(f"prob_t.shape {tf.shape(prob_t)}")
		prob_s = prob_dis(a_s, mu_s, si_s)
		print(f"prob_s.shape {tf.shape(prob_s)}")

		probability_to_draw_action = prob_t * prob_s
		print(f"prob.shape {tf.shape(probability_to_draw_action)}")
		print(f"prob {probability_to_draw_action}")
		return probability_to_draw_action

	def custom_loss_gaussian(self, state, action, reward, debug=False):
		"""[summary]
			Weighted Gaussian log likelihood loss function for RL

		Args:
			state ([type]): [description]
			action ([type]): [description]
			reward ([type]): [description]

		Returns:
			[type]: loss_actor
			Next step will be to apply it
		"""
		action_throttle = action[:, 0]
		action_steering = action[:, 1]
		action_throttle = tf.reshape(action_throttle, (-1, 1))
		action_steering = tf.reshape(action_steering, (-1, 1))
		print(f"action_throttle shape: {action_throttle.shape}")
		print(f"action_steering shape: {action_steering.shape}")

		# * Predict mu and sigma with actor network
		mu_throttle, sigma_throttle, mu_steering, sigma_steering = self.actor_network(state)

		action_throttle = tf.cast(action_throttle, tf.float64)
		action_steering = tf.cast(action_steering, tf.float64)
		mu_throttle = tf.cast(mu_throttle, tf.float64)
		sigma_throttle = tf.cast(sigma_throttle, tf.float64)
		mu_steering = tf.cast(mu_steering, tf.float64)
		sigma_steering = tf.cast(sigma_steering, tf.float64)
		print(f"mu_throttle shape: {mu_throttle.shape}")
		print(f"sigma_throttle shape: {sigma_throttle.shape}")


		# * Compute Gaussian probability distribution function value
		pdf_value_throttle = tf.exp(-0.5 * ((action_throttle - mu_throttle) / (sigma_throttle))**2) * \
				1 / (sigma_throttle * tf.cast(tf.sqrt(2 * np.pi), tf.float64))

		pdf_value_steering = tf.exp(-0.5 * ((action_steering - mu_steering) / (sigma_steering))**2) * \
				1 / (sigma_steering * tf.cast(tf.sqrt(2 * np.pi), tf.float64))

		# * Convert probability distribution function value to log probability
		log_probability_throttle = tf.math.log(pdf_value_throttle + 1e-5)
		log_probability_steering = tf.math.log(pdf_value_steering + 1e-5)

		if debug:
			print(f"PDF t: {float(log_probability_throttle):9.5}")
			print(f"PDF s: {float(log_probability_steering):9.5}")
		# * Compute weighted loss
		# TODO: check if multiplication is **really** the good way to combine a double log_probability
		# Using absolute value do NOT work.
		self.loss_ = - reward * ((log_probability_throttle) + (log_probability_steering))
		if debug:
			print(f"Loss: {self.loss_}")

		print(f"Loss: {self.loss_}")

		return self.loss_


	def update(self, state, action, reward, debug=False):
		# * MATHEMATICS:
			# *
			# * After taking our action a, we observe a corresponding reward signal v.
			# * Together with some learning rate α, we may update the weights into a direction that improves the expected reward of our policy
			# *
			# * Update rule:
			# * DELTA_mu_th(s) = alpha * v * (a - mu_th(s)) / std_th**2
			# * DELTA_std_th(s) = alpha * v * ((a - mu_th(s))**2 - std_th**2) / std_th**3
			# *
			# * Linear approx:
			# * mu_th(s) = th ** (T_phi(s))
			# *
			# * For NeuralNets: not as starightforward
			# * -> Trained by minimizing loss function
			# * 	-> is computed by MSE
			# *
			# * For the policy, we need to define a 'pseudo loss function' to update net
			# *
			# * Update rule in its generic form:
			# *		DELTA_th = alpha * NABLA_th (log(pi_th(a | s)) * v)
			# *
			# *		Update form gradient decent, hence minus sign
			# *			Loss(a, s, v) = -log(pi_th(a | s)) * v
			# *
			# *			Intution: log yields neg nb if input < 1
			# *				If action w/ small prob && high reward:
			# *					WE WANT large loss
			# *
			# *		Here, we can substitute pi_th by Gaussian Probability density function:
			# *
			# *			GPD() = ( 1 / (std (2 pi)**(1/2)) ) * e^( -1/2 * ((a - mu) / std)**2 )
			# *			Loss(a, s, v) = -log(GPD()) * v
			# *

		# * IMPLEMTATION:
			# *
			# *		Unfortunately, it's not directly applicable in TS 2.0
			# *
			# *			Normally ->
			# *						model.compile(loss='mse',optimizer=opt)
			# *						model.fit || model.train_on_batch
			# *
			# *			But ->
			# *					- Gaussian log likelihood loss function is not a default one in TensorFlow 2.0 (but it's in Theano)
			# *						-> Have to create a custom one
			# *
			# *					- TS requires 2 args: y_true, y_predicted
			# *						But -> we have 3 (we need to multiply w/ reward)
			# *
			# *			SEE: implementation in custom_loss_gaussian(state, action, reward)
			# *
			# *		How to apply our loss function update ?
			# *
			# *			GradientTape -> novel addition to TF 2.0
			# *				What is this ?
			# *					It records the forward steps on a 'tape'
			# *						-> so it can apply automatic differentiation
			# *
			# *				Updating approach:
			# *
			# *					1st :
			# *						Forward pass (actor net) with custom loss func
			# *							values are memorized
			# *						Calculate loss
			# *
			# *					2nd :
			# *						with .trainable_variables() -> we recall the weights of forward pass
			# *						tape.gradient calculates all the gradients
			# *							it plugs in loss value && trainable variables
			# *
			# *					3rd :
			# *						with optimizer.apply_gradients() -> update net weights
			# *							different optimizers are possible: SGD, Adam, RMSprop,...
			# *
			# *

		"""
			Compute and apply gradients to update network weights
		"""
		with tf.GradientTape() as tape:
			# Compute Gaussian loss with custom loss function
			loss_value = self.custom_loss_gaussian(state,
												action,
												reward,
												debug)

			# Compute gradients for actor network
			grads = tape.gradient(loss_value,
								self.actor_network.trainable_variables)

			# Apply gradients to update network weights
			self.opt.apply_gradients(zip(grads,
										self.actor_network.trainable_variables))
