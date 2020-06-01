import os
os.environ["OMP_NUM_THREADS"] = "1"

import numpy as np
import numpy.random as npr

import mimo
from mimo import distributions, mixture
from mimo.util.text import progprint_xrange

import os
import argparse

import matplotlib.pyplot as plt

import pathos
from pathos.pools import _ProcessPool as Pool
nb_cores = pathos.multiprocessing.cpu_count()


def _job(kwargs):
    args = kwargs.pop('arguments')
    seed = kwargs.pop('seed')

    input = kwargs.pop('train_input')
    target = kwargs.pop('train_target')

    input_dim = input.shape[-1]
    target_dim = target.shape[-1]

    # set random seed
    np.random.seed(seed)

    nb_params = input_dim
    if args.affine:
        nb_params += 1

    basis_prior = []
    models_prior = []

    # initialize Normal
    psi_niw = 1e0
    kappa = (1. / (input.T @ input)).item()

    # initialize Matrix-Normal
    psi_mniw = 1e0
    if args.affine:
        X = np.hstack((input, np.ones((len(input), 1))))
    else:
        X = input

    V = 10 * X.T @ X

    for n in range(args.nb_models):
        basis_hypparams = dict(mu=np.zeros((input_dim, )),
                               psi=np.eye(input_dim) * psi_niw,
                               kappa=kappa, nu=input_dim + 1 + 100)

        aux = distributions.NormalInverseWishart(**basis_hypparams)
        basis_prior.append(aux)

        models_hypparams = dict(M=np.zeros((target_dim, nb_params)),
                                affine=args.affine, V=V,
                                nu=target_dim + 1,
                                psi=np.eye(target_dim) * psi_mniw)

        aux = distributions.MatrixNormalInverseWishart(**models_hypparams)
        models_prior.append(aux)

    # define gating
    if args.prior == 'stick-breaking':
        gating_hypparams = dict(K=args.nb_models, gammas=np.ones((args.nb_models,)), deltas=np.ones((args.nb_models,)) * args.alpha)
        gating_prior = distributions.StickBreaking(**gating_hypparams)

        dpglm = mixture.BayesianMixtureOfLinearGaussians(gating=distributions.BayesianCategoricalWithStickBreaking(gating_prior),
                                                         basis=[distributions.BayesianGaussian(basis_prior[i]) for i in range(args.nb_models)],
                                                         models=[distributions.BayesianLinearGaussian(models_prior[i]) for i in range(args.nb_models)])

    else:
        gating_hypparams = dict(K=args.nb_models, alphas=np.ones((args.nb_models,)) * args.alpha)
        gating_prior = distributions.Dirichlet(**gating_hypparams)

        dpglm = mixture.BayesianMixtureOfLinearGaussians(gating=distributions.BayesianCategoricalWithDirichlet(gating_prior),
                                                         basis=[distributions.BayesianGaussian(basis_prior[i]) for i in range(args.nb_models)],
                                                         models=[distributions.BayesianLinearGaussian(models_prior[i]) for i in range(args.nb_models)])
    dpglm.add_data(target, input)

    for _ in range(args.super_iters):
        # Gibbs sampling
        if args.verbose:
            print("Gibbs Sampling")

        gibbs_iter = range(args.gibbs_iters) if not args.verbose\
            else progprint_xrange(args.gibbs_iters)

        for _ in gibbs_iter:
            dpglm.resample()

        if args.stochastic:
            # Stochastic meanfield VI
            if args.verbose:
                print('Stochastic Variational Inference')

            svi_iter = range(args.gibbs_iters) if not args.verbose\
                else progprint_xrange(args.svi_iters)

            batch_size = args.svi_batchsize
            prob = batch_size / float(len(input))
            for _ in svi_iter:
                minibatch = npr.permutation(len(input))[:batch_size]
                dpglm.meanfield_sgdstep(y=target[minibatch, :], x=input[minibatch, :],
                                        prob=prob, stepsize=args.svi_stepsize)
        if args.deterministic:
            # Meanfield VI
            if args.verbose:
                print("Variational Inference")
            dpglm.meanfield_coordinate_descent(tol=args.earlystop,
                                               maxiter=args.meanfield_iters,
                                               progprint=args.verbose)

    return dpglm


def parallel_dpglm_inference(nb_jobs=50, **kwargs):
    kwargs_list = []
    for n in range(nb_jobs):
        kwargs['seed'] = n
        kwargs_list.append(kwargs.copy())

    with Pool(processes=min(nb_jobs, nb_cores)) as p:
        res = p.map(_job, kwargs_list)

    return res


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Evaluate DPGLM with a Stick-breaking prior')
    parser.add_argument('--datapath', help='path to dataset', default=os.path.abspath(mimo.__file__ + '/../../datasets'))
    parser.add_argument('--evalpath', help='path to evaluation', default=os.path.abspath(mimo.__file__ + '/../../evaluation/uai2020/toy'))
    parser.add_argument('--nb_seeds', help='number of seeds', default=1, type=int)
    parser.add_argument('--prior', help='prior type', default='stick-breaking')
    parser.add_argument('--alpha', help='concentration parameter', default=100, type=float)
    parser.add_argument('--nb_models', help='max number of models', default=10, type=int)
    parser.add_argument('--affine', help='affine functions', action='store_true', default=True)
    parser.add_argument('--super_iters', help='interleaving Gibbs/VI iterations', default=1, type=int)
    parser.add_argument('--gibbs_iters', help='Gibbs iterations', default=25, type=int)
    parser.add_argument('--stochastic', help='use stochastic VI', action='store_true', default=False)
    parser.add_argument('--no_stochastic', help='do not use stochastic VI', dest='stochastic', action='store_false')
    parser.add_argument('--deterministic', help='use deterministic VI', action='store_true', default=True)
    parser.add_argument('--no_deterministic', help='do not use deterministic VI', dest='deterministic', action='store_false')
    parser.add_argument('--meanfield_iters', help='max VI iterations', default=1000, type=int)
    parser.add_argument('--svi_iters', help='SVI iterations', default=250, type=int)
    parser.add_argument('--svi_stepsize', help='SVI step size', default=5e-4, type=float)
    parser.add_argument('--svi_batchsize', help='SVI batch size', default=256, type=int)
    parser.add_argument('--prediction', help='prediction to mode or average', default='mode')
    parser.add_argument('--earlystop', help='stopping criterion for VI', default=1e-2, type=float)
    parser.add_argument('--verbose', help='show learning progress', action='store_true', default=True)
    parser.add_argument('--mute', help='show no output', dest='verbose', action='store_false')
    parser.add_argument('--seed', help='choose seed', default=1337, type=int)

    args = parser.parse_args()

    np.random.seed(args.seed)

    # create data
    noise = npr.normal(0, 1, (200, 1)) * 0.05
    target = npr.uniform(0, 1, (200, 1))
    input = target + 0.3 * np.sin(2. * np.pi * target) + noise

    dpglm = parallel_dpglm_inference(nb_jobs=args.nb_seeds,
                                     train_input=input,
                                     train_target=target,
                                     arguments=args)[0]

    # mean prediction
    mu_predict = []
    for t in range(len(input)):
        _mean, _, _, _ = dpglm.meanfield_prediction(input[t, :], prediction='average', sparse=True)
        mu_predict.append(np.atleast_2d(_mean))

    mu_predict = np.vstack(mu_predict)

    # metrics
    from sklearn.metrics import explained_variance_score, mean_squared_error, r2_score
    evar = explained_variance_score(target, mu_predict)
    mse = mean_squared_error(target, mu_predict)
    smse = 1. - r2_score(target, mu_predict)

    print('MEAN - EVAR:', evar, 'MSE:', mse, 'SMSE:', smse, 'Components:', len(dpglm.used_labels))

    # creat plot for mean vs mode prediction and gaussian activations
    fig, axes = plt.subplots(2, 1)

    axes[0].scatter(input, target, facecolors='none', edgecolors='k', linewidth=0.5)
    axes[0].scatter(input, mu_predict, marker='x', c='b', linewidth=0.5)
    plt.ylabel('y')

    # mode prediction
    mu_predict = []
    for t in range(len(input)):
        _mean, _var, _, _ = dpglm.meanfield_prediction(input[t, :], prediction='mode', sparse=True)
        mu_predict.append(np.atleast_2d(_mean))

    mu_predict = np.vstack(mu_predict)
    # metrics
    from sklearn.metrics import explained_variance_score, mean_squared_error

    mse = mean_squared_error(target, mu_predict)
    evar = explained_variance_score(target, mu_predict, multioutput='variance_weighted')
    smse = 1. - r2_score(target, mu_predict, multioutput='variance_weighted')

    print('Mode - EVAR:', evar, 'MSE:', mse, 'SMSE:', smse, 'Components:', len(dpglm.used_labels))

    axes[0].scatter(input, mu_predict, marker='D', facecolors='none', edgecolors='r', linewidth=0.5)

    # plot gaussian activations
    axes[1].set_xlabel('x')
    axes[1].set_ylabel('p(x)')

    sorted_input = np.sort(input, axis=0)
    activations = dpglm.meanfield_predictive_activation(sorted_input)

    colours = ['green', 'orange', 'purple']
    for i in range(len(dpglm.used_labels)):
        axes[1].plot(sorted_input, activations[:, i], color=colours[i])

    # set working directory
    os.chdir(args.evalpath)
    dataset = 'inverse'

    # save tikz and pdf
    import tikzplotlib
    path = os.path.join(str(dataset) + '/')
    tikzplotlib.save(path + dataset + '_comparison.tex')
    plt.savefig(path + dataset + '_comparison.pdf')
    plt.show()

    # get mean of matrix-normal for plotting experts
    regcoeff = []
    for idx, m in enumerate(dpglm.models):
        if idx in dpglm.used_labels:
            M, _, _, _ = m.posterior.params
            regcoeff.append(M)

    # plot three experts
    plt.figure()
    axis = np.linspace(0, 1, 500).reshape(-1, 1)
    mu_predict = []
    for t in range(len(axis)):
        q = np.hstack((axis[t, :], 1.))
        _mu_predict = (regcoeff[0] @ q).tolist()
        mu_predict.append(_mu_predict)
    mu_predict = np.asarray(mu_predict).reshape(-1, 1)
    plt.plot(axis, mu_predict, linewidth=2, c='green')

    mu_predict = []
    for t in range(len(axis)):
        q = np.hstack((axis[t, :], 1.))
        _mu_predict = (regcoeff[1] @ q).tolist()
        mu_predict.append(_mu_predict)
    mu_predict = np.asarray(mu_predict).reshape(-1, 1)
    plt.plot(axis, mu_predict, linewidth=2, c='orange')

    mu_predict = []
    for t in range(len(axis)):
        q = np.hstack((axis[t, :], 1.))
        _mu_predict = (regcoeff[2] @ q).tolist()
        mu_predict.append(_mu_predict)
    mu_predict = np.asarray(mu_predict).reshape(-1, 1)
    plt.plot(axis, mu_predict, linewidth=2, c='purple')

    # plot data
    plt.scatter(input, target, facecolors='none', edgecolors='k', linewidth=0.5)

    plt.ylabel('y')
    plt.xlabel('x')

    # save tikz and pdf
    import tikzplotlib
    path = os.path.join(str(dataset) + '/')
    tikzplotlib.save(path + dataset + '_experts.tex')
    plt.savefig(path + dataset + '_experts.pdf')

    plt.show()
