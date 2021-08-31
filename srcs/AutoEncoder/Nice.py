from numpy.core.numeric import indices
import torch
from torch import nn
from torch import optim


class EncodeLayer(nn.Module):
	def __init__(self, in_channels, out_channels, conv_kernel=3, pool_kernel=2):
		super(EncodeLayer, self).__init__()
		self.in_channels = in_channels
		self.out_channels = out_channels
		self.conv_kernel = conv_kernel
		self.pool_kernel = pool_kernel
		self.build()

	def build(self):
		self.Conv = nn.Conv2d(self.in_channels,
							self.out_channels,
							kernel_size=self.conv_kernel,
                        	padding=int((self.conv_kernel - 1) / 2))
		self.ReLU = nn.ReLU()
		self.Pool = nn.MaxPool2d(self.pool_kernel, return_indices=True)

	def forward(self, x):
		x = self.Conv(x)
		x = self.ReLU(x)
		shape = x.shape
		x, indices = self.Pool(x)
		return x, (indices, shape)


class DecodeLayer(nn.Module):
	def __init__(self, in_channels, out_channels, conv_kernel=3, pool_kernel=2):
		super(DecodeLayer, self).__init__()
		self.in_channels = in_channels
		self.out_channels = out_channels
		self.conv_kernel = conv_kernel
		self.pool_kernel = pool_kernel
		self.build()

	def build(self):
		self.unPool = nn.MaxUnpool2d(self.pool_kernel)
		self.ConvT = nn.ConvTranspose2d(self.in_channels,
										self.out_channels,
										kernel_size=self.conv_kernel,
										padding=int((self.conv_kernel - 1) / 2))
		self.ReLU = nn.ReLU()

	def forward(self, x, indices, size):
		x = self.unPool(x, indices, output_size=size)
		x = self.ConvT(x)
		x = self.ReLU(x)
		return x


class AutoEncoderModel(nn.Module):
	def __init__(self):
		super(AutoEncoderModel, self).__init__()
		self.layers = [3, 32, 32, 32, 64, 64, 128]
		self.vector = 8
		self.encoder_layers = nn.ModuleList()
		self._init_encoder()
		self.decoder_layers = nn.ModuleList()
		self._init_decoder()
		self.my_size = True

	def _init_encoder(self):
		L = len(self.layers)
		for i in range(L - 1):
			encoder = EncodeLayer(self.layers[i], self.layers[i + 1])
			self.encoder_layers.append(encoder)

		self.encode_one = nn.Conv2d(self.layers[-1],
									self.vector,
									kernel_size=1)
		self.ReLU = nn.ReLU()
		
	def _init_decoder(self):
		L = len(self.layers)
		for i in range(L - 1):
			decoder = DecodeLayer(self.layers[::-1][i], self.layers[::-1][i + 1])
			self.decoder_layers.append(decoder)

		self.decode_one = nn.ConvTranspose2d(self.vector,
                                       self.layers[-1],
                                       kernel_size=1)

	def encoder(self, x):
		encoder_cache = []
		for layer in self.encoder_layers:
			x, cache = layer.forward(x)
			encoder_cache.append(cache)
		return x, encoder_cache[::-1]

	def decoder(self, x, encoder_cache):
		for layer, cache in zip(self.decoder_layers, encoder_cache):
			indices, size = cache
			x = layer.forward(x, indices, size)
		return x

	def forward(self, x):
		x, cache = self.encoder(x)
		x = self.encode_one(x)
		x =  self.ReLU(x)
		if self.my_size:
			self.my_size = False
			print(f"{x.shape = }")
		x = self.decode_one(x)
		x = self.ReLU(x)
		x = self.decoder(x, cache)
		return x


class NiceAutoEncoder():
	def __init__(self, config) -> None:
		self.config = config
		self.model_path = f"{self.config.model_dir}{self.__class__.__name__}_{self.config.name}"
		self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
		self.model = AutoEncoderModel().to(self.device)
		print(self.model)
		self.optimizer = optim.Adam(self.model.parameters(), lr=config.lr)
		self.criterion = nn.MSELoss()
		self.loss = 0.

	def train(self, batch):
		batch = batch.to(self.device)
		self.optimizer.zero_grad()
		outputs = self.model(batch)

		loss = self.criterion(outputs, batch)
		loss.backward()
		self.optimizer.step()

		self.loss += loss.item()

	def predict(self, X):
		with torch.no_grad():
			X = X.to(self.device)
			Y = self.model(X)
			return Y

	def encode(self, X):
		with torch.no_grad():
			X = X.to(self.device)
			X, _ = self.model.encoder(X)
			return X

	def load(self):
		self.model.load_state_dict(torch.load(self.model_path))
		self.model.eval()

	def save(self):
		torch.save(self.model.state_dict(), self.model_path)

	# def name(self):
	# 	pass