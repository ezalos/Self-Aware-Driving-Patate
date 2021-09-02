import torch
from torch import nn
from torch import optim
import torch.nn.functional as F

class GaussianOut(nn.Module):
	def __init__(self, input_units):
		super(GaussianOut, self).__init__()
		self.lin_μ = nn.linear(input_units, 1)
		self.lin_σ = nn.linear(input_units, 1)

	def forward(self, x):
		μ = self.lin_μ(x)
		σ = self.lin_σ(x)
		return μ, σ


class PolicyModel(nn.Module):
	def __init__(self):
		super(PolicyModel, self).__init__()
		# Vector (4, 8)
		in_channels = [*config.input_size][0]
		self.conv0 = nn.Conv1d(in_channels, 4, kernel_size=1, stride=1, padding=0) # (kernal_size - 1) / 2 for same paddind
		self.conv1 = nn.Conv1d(4, 2, kernel_size=1, stride=1, padding=0) # (kernal_size - 1) / 2 for same paddind
		self.conv2 = nn.Conv1d(2, 1, kernel_size=1, stride=1, padding=0) # (kernal_size - 1) / 2 for same paddind

		self.flatten = nn.Flatten()

		self.dense1 = nn.Linear(config.input_size[1], 16)
		self.dense2 = nn.Linear(16, 32)
		self.dense3 = nn.Linear(32, 32)

		end_units = 16
		self.dense4 = nn.Linear(32, end_units)

		self.G_throttle = GaussianOut(end_units)
		self.G_steering = GaussianOut(end_units)

	def forward(self, x):
		x = x.to(device)
		# Carefull relu -> neurons might die bc low vector space
		x = F.relu(self.conv0(x))
		x = F.relu(self.conv1(x))
		x = F.relu(self.conv2(x))
		x = self.flatten(x)
		x = F.relu(self.dense1(x))
		x = F.relu(self.dense2(x))
		x = F.relu(self.dense3(x))
		x = F.relu(self.dense4(x))
		throttle = self.G_throttle(x)
		steering = self.G_steering(x)
		return throttle, steering


def gaussian_pdf(x, m, s):
	#  $ f(x, \mu, \sigma) = \frac{1}{\sigma\sqrt{2\pi}}e ^\frac{-(x -\mu) ^ 2}{2\sigma ^ 2} $
	pi = torch.tensor(math.pi)
	sig_sqrt = s * torch.sqrt(2 * pi)
	expo = torch.exp(- torch.pow(x - m, 2) / (2 * torch.pow(s, 2)))
	return (1 / sig_sqrt) * expo 


class Policy():
	def __init__(self, input_shape, bottleneck_shape, learning_rate=1e-3) -> None:
		self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
		self.model = PolicyModel().to(self.device)
		self.optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
		# self.criterion = nn.MSELoss()
		self.loss = 0.

	def train(self, batch):
		batch = batch.to(self.device)
		self.optimizer.zero_grad()
		outputs = self.model(batch)
		loss = self.criterion(outputs, batch)
		loss.backward()
		self.optimizer.step()
		self.loss += loss.item()

	def draw_actions(self, gauss_throttle, gauss_steering):
		throttle = torch.normal(*gauss_throttle)
		throttle = F.tanh(throttle)

		steering = torch.normal(*gauss_steering)
		steering = F.sigmoid(steering)

		return throttle, steering

	def policy_probability(self, g_t, a_t):
		g_throttle, g_steering = g_t

		throttle, steering = a_t

		steering = torch.logit(steering)
		throttle = torch.atanh(throttle)

		prob_throttle = gaussian_pdf(throttle, *g_throttle)
		prob_steering = gaussian_pdf(steering, *g_steering)

		# By the way, it's not independant.
		# But simplification is useful
		prob = prob_throttle * prob_steering
		return prob

	def criterion(self, state, action, reward):
		gaussian_distrib = self.model(state)
		probability = self.policy_probability(gaussian_distrib, action)
		loss =  reward - torch.log(probability)
		return loss