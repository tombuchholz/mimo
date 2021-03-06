import numpy as np
import numpy.random as npr

from matplotlib import pyplot as plt

from mimo.distributions import Dirichlet
from mimo.distributions import CategoricalWithDirichlet
from mimo.distributions import NormalWishart
from mimo.distributions import GaussianWithNormalWishart

from mimo.mixtures import BayesianMixtureOfGaussians


npr.seed(1337)

nb_samples = 2500

data = np.zeros((nb_samples, 2))
step = 14. * np.pi / nb_samples

for i in range(data.shape[0]):
    x = i * step - 6.
    data[i, 0] = x + npr.normal(0, 0.1)
    data[i, 1] = 3. * (np.sin(x) + npr.normal(0, .1))

plt.figure()
plt.plot(data[:, 0], data[:, 1], 'kx')
plt.title('data')

nb_models = 25

gating_hypparams = dict(K=nb_models, alphas=np.ones((nb_models, )))
gating_prior = Dirichlet(**gating_hypparams)

components_hypparams = dict(mu=np.zeros((2, )), kappa=0.01,
                            psi=np.eye(2), nu=3)
components_prior = NormalWishart(**components_hypparams)

gmm = BayesianMixtureOfGaussians(gating=CategoricalWithDirichlet(gating_prior),
                                 components=[GaussianWithNormalWishart(components_prior)
                                             for _ in range(nb_models)])

gmm.add_data(data, labels_from_prior=True)

gmm.resample(maxiter=2500)

plt.figure()
plt.title('posterior')
gmm.plot()
plt.show()
