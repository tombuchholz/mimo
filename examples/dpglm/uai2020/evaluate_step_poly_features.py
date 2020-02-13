import os
os.environ["OMP_NUM_THREADS"] = "1"

import numpy as np
import numpy.random as npr

import mimo
from mimo import distributions, models
from mimo.util.text import progprint_xrange
from mimo.util.general import near_pd

import argparse

import matplotlib.pyplot as plt

from joblib import Parallel, delayed
import multiprocessing
nb_cores = multiprocessing.cpu_count()


def create_job(kwargs):
    train_data = kwargs.pop('train_data')
    args = kwargs.pop('arguments')
    seed = kwargs.pop('seed')

    input = train_data['input']
    target = train_data['target']
    data = np.hstack((input, target))

    input_dim = input.shape[-1]
    target_dim = target.shape[-1]

    # set random seed
    np.random.seed(seed)

    nb_params = input_dim
    if args.affine:
        nb_params += 1

    components_prior = []
    if args.init_kmeans:
        from sklearn.cluster import KMeans
        km = KMeans(args.nb_models).fit(np.hstack((input, target)))

        for n in range(args.nb_models):
            # initialize Normal
            mu_input = km.cluster_centers_[n, :input_dim]
            _psi_input = np.cov(input[km.labels_ == n], bias=False, rowvar=False)
            psi_input = near_pd(np.atleast_2d(_psi_input))
            kappa = 1e-2

            # initialize Matrix-Normal
            mu_output = np.zeros((target_dim, nb_params))
            mu_output[:, -1] = km.cluster_centers_[n, input_dim:]
            psi_mniw = 1e-1
            V = 1e3 * np.eye(nb_params)

            components_hypparams = dict(mu=mu_input, kappa=kappa,
                                        psi_niw=psi_input, nu_niw=input_dim + 1,
                                        M=mu_output, affine=args.affine,
                                        V=V, nu_mniw=target_dim + 1,
                                        psi_mniw=np.eye(target_dim) * psi_mniw)

            aux = distributions.NormalInverseWishartMatrixNormalInverseWishart(**components_hypparams)
            components_prior.append(aux)
    else:
        # initialize Normal
        mu_low = np.min(input, axis=0)
        mu_high = np.max(input, axis=0)
        psi_niw = 1e0
        kappa = 1e-2

        # initialize Matrix-Normal
        psi_mniw = 1e-1
        V = 1e3 * np.eye(nb_params)

        for n in range(args.nb_models):
            components_hypparams = dict(mu=npr.uniform(mu_low, mu_high, size=input_dim),
                                        kappa=kappa, psi_niw=np.eye(input_dim) * psi_niw,
                                        nu_niw=input_dim + 1,
                                        M=np.zeros((target_dim, nb_params)),
                                        affine=args.affine, V=V,
                                        nu_mniw=target_dim + 1,
                                        psi_mniw=np.eye(target_dim) * psi_mniw)

            aux = distributions.NormalInverseWishartMatrixNormalInverseWishart(**components_hypparams)
            components_prior.append(aux)

    # define gating
    if args.prior == 'stick-breaking':
        gating_hypparams = dict(K=args.nb_models, gammas=np.ones((args.nb_models,)), deltas=np.ones((args.nb_models,)) * args.alpha)
        gating_prior = distributions.StickBreaking(**gating_hypparams)
    else:
        gating_hypparams = dict(K=args.nb_models, alphas=np.ones((args.nb_models,)) * args.alpha)
        gating_prior = distributions.Dirichlet(**gating_hypparams)

    # define model
    if args.prior == 'stick-breaking':
        dpglm = models.Mixture(gating=distributions.BayesianCategoricalWithStickBreaking(gating_prior),
                               components=[distributions.BayesianLinearGaussianWithNoisyInputs(components_prior[i]) for i in range(args.nb_models)])
    else:
        dpglm = models.Mixture(gating=distributions.BayesianCategoricalWithDirichlet(gating_prior),
                               components=[distributions.BayesianLinearGaussianWithNoisyInputs(components_prior[i]) for i in range(args.nb_models)])
    dpglm.add_data(data)

    for _ in range(args.super_iters):
        gibbs_iter = range(args.gibbs_iters) if not args.verbose\
            else progprint_xrange(args.gibbs_iters)

        # Gibbs sampling
        print("Gibbs Sampling")
        for _ in gibbs_iter:
            dpglm.resample_model()

        if not args.stochastic:
            # Meanfield VI
            print("Variational Inference")
            dpglm.meanfield_coordinate_descent(tol=args.earlystop,
                                               maxiter=args.meanfield_iters,
                                               progprint=args.verbose)
        else:
            svi_iters = range(args.gibbs_iters) if not args.verbose\
                else progprint_xrange(args.svi_iters)

            # Stochastic meanfield VI
            print('Stochastic Variational Inference')
            batch_size = args.svi_batchsize
            prob = batch_size / float(len(data))
            for _ in svi_iters:
                minibatch = npr.permutation(len(data))[:batch_size]
                dpglm.meanfield_sgdstep(minibatch=data[minibatch, :],
                                        prob=prob, stepsize=args.svi_stepsize)

    return dpglm


def parallel_dpglm_inference(nb_jobs=50, **kwargs):
    kwargs_list = []
    for n in range(nb_jobs):
        kwargs['seed'] = n
        kwargs_list.append(kwargs.copy())

    return Parallel(n_jobs=min(nb_jobs, nb_cores),
                    verbose=10, backend='loky')(map(delayed(create_job), kwargs_list))


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Evaluate DPGLM with a Stick-breaking prior')
    parser.add_argument('--datapath', help='Set path to dataset', default=os.path.abspath(mimo.__file__ + '/../../datasets'))
    parser.add_argument('--evalpath', help='Set path to evaluation', default=os.path.abspath(mimo.__file__ + '/../../evaluation/uai2020'))
    parser.add_argument('--nb_seeds', help='Set number of seeds', default=1, type=int)
    parser.add_argument('--prior', help='Set prior type', default='stick-breaking')
    parser.add_argument('--alpha', help='Set concentration parameter', default=25, type=float)
    parser.add_argument('--nb_models', help='Set max number of models', default=20, type=int)
    parser.add_argument('--affine', help='Set affine or not', default=True, type=bool)
    parser.add_argument('--super_iters', help='Set interleaving Gibbs/VI iterations', default=1, type=int)
    parser.add_argument('--gibbs_iters', help='Set Gibbs iterations', default=100, type=int)
    parser.add_argument('--stochastic', help='Set stoch. or deter. VI', default=False, type=float)
    parser.add_argument('--meanfield_iters', help='Set max VI iterations', default=500, type=int)
    parser.add_argument('--svi_iters', help='Set stochastic VI iterations', default=2500, type=int)
    parser.add_argument('--svi_stepsize', help='Set SVI step size', default=5e-4, type=float)
    parser.add_argument('--svi_batchsize', help='Set SVI batch size', default=256, type=int)
    parser.add_argument('--prediction', help='Set prediction to mode or average', default='mode')
    parser.add_argument('--earlystop', help='Set stopping criterion for VI', default=1e-2, type=float)
    parser.add_argument('--init_kmeans', help='Set initialization with KMEANS', default=False, type=float)
    parser.add_argument('--verbose', help='Show learning progress', default=True, type=float)

    args = parser.parse_args()

    np.random.seed(1337)

    # create data
    n_train = 300
    noise_std = 2
    input1 = np.linspace(-3., 0, int(n_train / 2)).reshape(int(n_train / 2), 1)
    input2 = np.linspace(0., 3., int(n_train / 2)).reshape(int(n_train / 2), 1)
    mean1 = 4 * input1 ** 3 - 2 * input1
    mean2 = 4 * input2 ** 3 - 2 * input2 + 100
    input, mean = np.concatenate((input1, input2), axis=0), np.concatenate((mean1, mean2), axis=0)
    noise = npr.normal(0, noise_std, n_train).reshape(n_train, 1)
    target = mean + noise

    # create plot for prediction and gaussian activations
    from matplotlib import gridspec
    fig = plt.figure()
    gs = gridspec.GridSpec(2, 1, height_ratios=[6, 1])
    ax0 = plt.subplot(gs[0])
    plt.ylabel('y')

    # polynomial features
    from sklearn.preprocessing import PolynomialFeatures
    poly = PolynomialFeatures(degree=3, interaction_only=False, include_bias=False)
    input = poly.fit_transform(np.atleast_2d(input))
    target = poly.fit_transform(np.atleast_2d(target))

    # # Scaled Data
    # from sklearn.decomposition import PCA
    # input_scaler = PCA(n_components=1, whiten=True)
    # target_scaler = PCA(n_components=1, whiten=True)
    #
    # input_scaler.fit(input)
    # target_scaler.fit(target)
    #
    # scaled_input = input_scaler.transform(input)
    # scaled_target = target_scaler.transform(target)
    #
    # scaled_train_data = {'input': scaled_input,
    #                      'target': scaled_target}

    train_data = {'input': input,
                         'target': target}

    dpglm = parallel_dpglm_inference(nb_jobs=args.nb_seeds,
                                      train_data=train_data,
                                      arguments=args)[0]

    # predict
    from mimo.util.prediction import meanfield_prediction

    mu_predict, var_predict, std_predict = [], [], []
    for t in range(len(input)):
        _mean, _var, _ = meanfield_prediction(dpglm, input[t, :], args.prediction)
        # mu_predict.append(target_scaler.inverse_transform(np.atleast_2d(_mean)))
        mu_predict.append(_mean[0])

        # trans = np.sqrt(target_scaler.explained_variance_[:, None]) * target_scaler.components_
        # _var = trans.T @ _var @ trans
        var_predict.append(_var[0])
        std_predict.append(np.sqrt(_var)[0])

    mu_predict = np.vstack(mu_predict)
    var_predict = np.vstack(var_predict)
    std_predict = np.vstack(std_predict)

    # get data without feature transformation
    target = target[:, 0]
    input = input[:, 0]

    # metrics
    from sklearn.metrics import explained_variance_score, mean_squared_error
    evar = explained_variance_score(mu_predict, target)
    mse = mean_squared_error(mu_predict, target)
    smse = mean_squared_error(mu_predict, target) / np.var(target, axis=0)

    print('EVAR:', evar, 'MSE:', mse, 'SMSE:', smse, 'Compnents:', len(dpglm.used_labels))

    # plot prediction
    ax0.plot(input, mu_predict + 2 * std_predict, '-b', zorder=5)
    ax0.plot(input, mu_predict - 2 * std_predict, '-b', zorder=5)
    ax0.plot(input, mu_predict, '-r', zorder=10)
    plt.scatter(input, target, s=0.75, color="black", zorder=0)

    # plot gaussian activations
    import scipy.stats as stats
    ax1 = plt.subplot(gs[1])
    plt.xlabel('x')
    plt.ylabel('p(x)')

    mu, sigma = [], []
    for idx, c in enumerate(dpglm.components):
        if idx in dpglm.used_labels:
            _mu, _sigma, _, _ = c.posterior.mode()

            # _mu = input_scaler.inverse_transform(np.atleast_2d(_mu))
            # trans = (np.sqrt(input_scaler.explained_variance_[:, None]) * input_scaler.components_).T
            # _sigma = trans.T @ np.diag(_sigma) @ trans

            mu.append(_mu[0])
            sigma.append(_sigma[0, 0])

    activations = []
    for i in range(len(dpglm.used_labels)):
        activations.append(stats.norm.pdf(input, mu[i], np.sqrt(sigma[i])))

    activations = np.asarray(activations).squeeze()
    # activations = activations / np.sum(activations, axis=1, keepdims=True)
    activations = activations / np.sum(activations, axis=0, keepdims=True)

    for i in range(len(dpglm.used_labels)):
        ax1.plot(input, activations[i])

    # set working directory
    os.chdir(args.evalpath)
    dataset = 'step_poly_features'

    # save tikz and pdf
    import tikzplotlib
    path = os.path.join(str(dataset) + '/')
    tikzplotlib.save(path + dataset + '.tex')
    plt.savefig(path + dataset + '.pdf')

    plt.show()
