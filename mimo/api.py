import os
os.environ["OMP_NUM_THREADS"] = "1"

import numpy as np
import numpy.random as npr

from mimo.distributions import NormalWishart
from mimo.distributions import MatrixNormalWishart

from mimo.distributions import GaussianWithNormalWishart
from mimo.distributions import LinearGaussianWithMatrixNormalWishart

from mimo.distributions import StickBreaking
from mimo.distributions import CategoricalWithStickBreaking

from mimo.mixtures import BayesianMixtureOfLinearGaussians

from mimo.util.text import progprint_xrange


class InfiniteLinearRegression:
    """
    This class serves as an abstract RegressionModel template
    """
    def __init__(self, input_dim, output_dim,
                 basis_prior, model_prior,
                 gating_prior, nb_models, affine=True):
        """
        The constructor for RegressionModel.

        Parameters:
            input_dim (int): The number of input dimensions of the regression model.
            output_dim (int): The number of output dimensions of the regression model.

        """
        self.k = input_dim
        self.d = output_dim

        self.nb_models = nb_models

        self.gating_prior = gating_prior
        self.basis_prior = basis_prior
        self.model_prior = model_prior

        self.affine = affine

        # number of parameters per regressor
        self.nb_params = self.k + 1 if self.affine else self.k

        basis_prior_list = []
        model_prior_list = []

        for n in range(self.nb_models):
            basis_hypparams = dict(mu=np.zeros((self.k,)),
                                   psi=np.eye(self.k) * self.basis_prior['psi'],
                                   kappa=self.basis_prior['kappa'], nu=self.k + 2)

            basis_prior_list.append(NormalWishart(**basis_hypparams))

            model_hypparams = dict(M=np.zeros((self.d, self.nb_params)),
                                   K=np.eye(self.nb_params) * self.model_prior['K'],
                                   psi=np.eye(self.d) * self.model_prior['psi'], nu=self.d + 2)

            model_prior_list.append(MatrixNormalWishart(**model_hypparams))

        gating_hypparams = dict(K=self.nb_models,
                                gammas=np.ones((self.nb_models,)),
                                deltas=np.ones((self.nb_models,)) * self.gating_prior['alpha'])
        gating_prior = StickBreaking(**gating_hypparams)

        self.regressor = BayesianMixtureOfLinearGaussians(gating=CategoricalWithStickBreaking(gating_prior),
                                                          basis=[GaussianWithNormalWishart(basis_prior[i]) for i in range(self.nb_models)],
                                                          models=[LinearGaussianWithMatrixNormalWishart(basis_prior[i], affine=self.affine)
                                                                  for i in range(self.nb_models)])

    def fit(self, output, input,
            super_iters=1, verbose=False,
            gibbs_iters=1, vi_iters=1000,
            vi_earlystop=1e-2, svi_iters=0,
            svi_batch_size=64, svi_step_size=1e-3):
        """
        Fits the model to the training data.
        """

        self.regressor.add_data(output, input, whiten=False)

        for i in range(super_iters):
            # Gibbs sampling
            if verbose:
                print("Gibbs Sampling")

            gibbs_iter = range(gibbs_iters) if not verbose \
                else progprint_xrange(gibbs_iters)

            for _ in gibbs_iter:
                self.regressor.resample()

            # Stochastic meanfield VI
            if verbose:
                print('Stochastic Variational Inference')

            svi_iter = range(svi_iters) if not verbose \
                else progprint_xrange(svi_iters)

            prob = svi_batch_size / float(len(input))
            for _ in svi_iter:
                minibatch = npr.permutation(len(input))[:svi_batch_size]
                self.regressor.meanfield_sgdstep(y=output[minibatch, :], x=input[minibatch, :],
                                                 prob=prob, stepsize=svi_step_size)

            # Meanfield VI
            if verbose:
                print("Variational Inference")
            self.regressor.meanfield_coordinate_descent(tol=vi_earlystop,
                                                        maxiter=vi_iters,
                                                        progprint=verbose)

            if super_iters > 1 and i + 1 < super_iters:
                self.regressor.gating.prior = self.regressor.gating.posterior
                for n in range(self.regressor.size):
                    self.regressor.basis[n].prior = self.regressor.basis[n].posterior
                    self.regressor.models[n].prior = self.regressor.models[n].posterior

    def predict(self, X):
        mu, var, _, _ = self.regressor.meanfield_prediction(X, prediction='average')
        return mu, var

