# notes

# ask michael if we can get the locations of the different cells
# this thing (LSE) but on the whole brain
# compare to the omni one
# bic curves for both
# compute ARI

# slides for tomorrow
# when we present (seems like it should be obvious)
# then show the result, know whether it is what they would have expected

# ARI curve
# best ARI

# BIC Curve
# best bic

# at least one where we get cliques (across cliques)


#%% Imports
import math
import os
from operator import itemgetter

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from graspy.cluster import GaussianCluster
from graspy.embed import AdjacencySpectralEmbed, OmnibusEmbed
from graspy.models import SBMEstimator
from graspy.plot import heatmap, pairplot
from graspy.utils import binarize, cartprod, pass_to_ranks
from joblib.parallel import Parallel, delayed
from matplotlib.colors import LogNorm
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score
from spherecluster import SphericalKMeans

from src.data import load_everything
from src.utils import savefig
from src.visualization import sankey

FNAME = os.path.basename(__file__)[:-3]
print(FNAME)


# %% [markdown]
# # Parameters
MB_VERSION = "mb_2019-09-23"
BRAIN_VERSION = "2019-09-18-v2"
GRAPH_TYPES = ["Gad", "Gaa", "Gdd", "Gda"]
GRAPH_TYPE_LABELS = [r"A $\to$ D", r"A $\to$ A", r"D $\to$ D", r"D $\to$ A"]
N_GRAPH_TYPES = len(GRAPH_TYPES)

SAVEFIGS = False
DEFAULT_FMT = "png"
DEFUALT_DPI = 150

MAX_CLUSTERS = 10
MIN_CLUSTERS = 2
N_INIT = 1
PTR = True


# Functions


def stashfig(name, **kws):
    if SAVEFIGS:
        savefig(name, foldername=FNAME, fmt=DEFAULT_FMT, dpi=DEFUALT_DPI, **kws)


def annotate_arrow(ax, coords=(0.061, 0.93)):
    arrow_args = dict(
        arrowstyle="-|>",
        color="k",
        connectionstyle="arc3,rad=-0.4",  # "angle3,angleA=90,angleB=90"
    )
    t = ax.annotate("Target", xy=coords, xycoords="figure fraction")

    ax.annotate(
        "Source", xy=(0, 0.5), xycoords=t, xytext=(-1.4, -2.1), arrowprops=arrow_args
    )


def ase(adj, n_components):
    if PTR:
        adj = pass_to_ranks(adj)
    ase = AdjacencySpectralEmbed(n_components=n_components)
    latent = ase.fit_transform(adj)
    latent = np.concatenate(latent, axis=-1)
    return latent


def to_laplace(graph, form="DAD", regularizer=None):
    r"""
    A function to convert graph adjacency matrix to graph laplacian. 
    Currently supports I-DAD, DAD, and R-DAD laplacians, where D is the diagonal
    matrix of degrees of each node raised to the -1/2 power, I is the 
    identity matrix, and A is the adjacency matrix.
    
    R-DAD is regularized laplacian: where :math:`D_t = D + regularizer*I`.
    Parameters
    ----------
    graph: object
        Either array-like, (n_vertices, n_vertices) numpy array,
        or an object of type networkx.Graph.
    form: {'I-DAD' (default), 'DAD', 'R-DAD'}, string, optional
        
        - 'I-DAD'
            Computes :math:`L = I - D*A*D`
        - 'DAD'
            Computes :math:`L = D*A*D`
        - 'R-DAD'
            Computes :math:`L = D_t*A*D_t` where :math:`D_t = D + regularizer*I`
    regularizer: int, float or None, optional (default=None)
        Constant to be added to the diagonal of degree matrix. If None, average 
        node degree is added. If int or float, must be >= 0. Only used when 
        ``form`` == 'R-DAD'.
    Returns
    -------
    L: numpy.ndarray
        2D (n_vertices, n_vertices) array representing graph 
        laplacian of specified form
    References
    ----------
    .. [1] Qin, Tai, and Karl Rohe. "Regularized spectral clustering
           under the degree-corrected stochastic blockmodel." In Advances
           in Neural Information Processing Systems, pp. 3120-3128. 2013
    """
    valid_inputs = ["I-DAD", "DAD", "R-DAD"]
    if form not in valid_inputs:
        raise TypeError("Unsuported Laplacian normalization")

    A = graph

    in_degree = np.sum(A, axis=0)
    out_degree = np.sum(A, axis=1)

    # regularize laplacian with parameter
    # set to average degree
    if form == "R-DAD":
        if regularizer is None:
            regularizer = 1
        elif not isinstance(regularizer, (int, float)):
            raise TypeError(
                "Regularizer must be a int or float, not {}".format(type(regularizer))
            )
        elif regularizer < 0:
            raise ValueError("Regularizer must be greater than or equal to 0")
        regularizer = regularizer * np.mean(out_degree)

        in_degree += regularizer
        out_degree += regularizer

    with np.errstate(divide="ignore"):
        in_root = 1 / np.sqrt(in_degree)  # this is 10x faster than ** -0.5
        out_root = 1 / np.sqrt(out_degree)

    in_root[np.isinf(in_root)] = 0
    out_root[np.isinf(out_root)] = 0

    in_root = np.diag(in_root)  # just change to sparse diag for sparse support
    out_root = np.diag(out_root)

    if form == "I-DAD":
        L = np.diag(in_degree) - A
        L = in_root @ L @ in_root
    elif form == "DAD" or form == "R-DAD":
        L = out_root @ A @ in_root
    # return symmetrize(L, method="avg")  # sometimes machine prec. makes this necessary
    return L


def lse(adj, n_components, regularizer=None):
    if PTR:
        adj = pass_to_ranks(adj)
    lap = to_laplace(adj, form="R-DAD")
    ase = AdjacencySpectralEmbed(n_components=n_components)
    latent = ase.fit_transform(lap)
    latent = np.concatenate(latent, axis=-1)
    return latent


def omni(adjs, n_components):
    if PTR:
        adjs = [pass_to_ranks(a) for a in adjs]
    omni = OmnibusEmbed(n_components=n_components // len(adjs))
    latent = omni.fit_transform(adjs)
    latent = np.concatenate(latent, axis=-1)  # first is for in/out
    latent = np.concatenate(latent, axis=-1)  # second is for concat. each graph
    return latent


def ase_concatenate(adjs, n_components):
    if PTR:
        adjs = [pass_to_ranks(a) for a in adjs]
    ase = AdjacencySpectralEmbed(n_components=n_components // len(adjs))
    graph_latents = []
    for a in adjs:
        latent = ase.fit_transform(a)
        latent = np.concatenate(latent, axis=-1)
        graph_latents.append(latent)
    latent = np.concatenate(graph_latents, axis=-1)
    return latent


def get_sbm_prob(adj, labels):
    sbm = SBMEstimator(directed=True, loops=True)
    sbm.fit(binarize(adj), y=labels)
    data = sbm.block_p_
    uni_labels, counts = np.unique(labels, return_counts=True)
    sort_inds = np.argsort(counts)[::-1]
    uni_labels = uni_labels[sort_inds]
    data = data[np.ix_(sort_inds, sort_inds)]

    prob_df = pd.DataFrame(columns=uni_labels, index=uni_labels, data=data)

    return prob_df


def probplot(
    prob_df,
    ax=None,
    title=None,
    log_scale=False,
    cmap="Purples",
    vmin=None,
    vmax=None,
    figsize=(10, 10),
):
    cbar_kws = {"fraction": 0.08, "shrink": 0.8, "pad": 0.03}

    data = prob_df.values

    if log_scale:
        data = data + 0.001

        log_norm = LogNorm(vmin=data.min().min(), vmax=data.max().max())
        cbar_ticks = [
            math.pow(10, i)
            for i in range(
                math.floor(math.log10(data.min().min())),
                1 + math.ceil(math.log10(data.max().max())),
            )
        ]
        cbar_kws["ticks"] = cbar_ticks

    if ax is None:
        fig = plt.figure(figsize=figsize)
        ax = plt.gca()

    ax.set_title(title, pad=30, fontsize=30)

    sns.set_context("talk", font_scale=1)

    heatmap_kws = dict(
        cbar_kws=cbar_kws,
        annot=True,
        square=True,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        fmt=".0f",
    )
    if log_scale:
        heatmap_kws["norm"] = log_norm
    if ax is not None:
        heatmap_kws["ax"] = ax

    ax = sns.heatmap(prob_df, **heatmap_kws)

    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    return ax


def _get_block_indices(y):
    """
    y is a length n_verts vector of labels
    returns a length n_verts vector in the same order as the input
    indicates which block each node is
    """
    block_labels, block_inv, block_sizes = np.unique(
        y, return_inverse=True, return_counts=True
    )

    n_blocks = len(block_labels)
    block_inds = range(n_blocks)

    block_vert_inds = []
    for i in block_inds:
        # get the inds from the original graph
        inds = np.where(block_inv == i)[0]
        block_vert_inds.append(inds)
    return block_vert_inds, block_inds, block_inv


def _calculate_block_edgesum(graph, block_inds, block_vert_inds):
    """
    graph : input n x n graph 
    block_inds : list of length n_communities
    block_vert_inds : list of list, for each block index, gives every node in that block
    return_counts : whether to calculate counts rather than proportions
    """

    n_blocks = len(block_inds)
    block_pairs = cartprod(block_inds, block_inds)
    block_p = np.zeros((n_blocks, n_blocks))

    for p in block_pairs:
        from_block = p[0]
        to_block = p[1]
        from_inds = block_vert_inds[from_block]
        to_inds = block_vert_inds[to_block]
        block = graph[from_inds, :][:, to_inds]
        p = np.sum(block)
        p = p / block.size
        block_p[from_block, to_block] = p
    return block_p


def get_colors(true_labels, pred_labels):
    color_dict = {}
    classes = np.unique(true_labels)
    known_palette = sns.color_palette("tab10", n_colors=len(classes))
    for i, true_label in enumerate(classes):
        color = known_palette[i]
        color_dict[true_label] = color

    classes = np.unique(pred_labels)
    known_palette = sns.color_palette("gray", n_colors=len(classes))
    for i, pred_label in enumerate(classes):
        color = known_palette[i]
        color_dict[pred_label] = color
    return color_dict


def clustergram(
    adj, latent, prob_df, block_sum_df, true_labels, pred_labels, figsize=(20, 20)
):
    fig, ax = plt.subplots(2, 2, figsize=figsize)
    ax = ax.ravel()
    sns.set_context("talk", font_scale=2)
    color_dict = get_colors(true_labels, pred_labels)
    sankey(
        ax[0], true_labels, pred_labels, aspect=20, fontsize=16, colorDict=color_dict
    )
    ax[0].axis("off")
    ax[0].set_title("Known class sorting", fontsize=30, pad=45)

    ax[1] = heatmap(
        adj,
        transform="simple-all",
        inner_hier_labels=pred_labels,
        cbar=False,
        sort_nodes=True,
        ax=ax[1],
        cmap="PRGn_r",
        hier_label_fontsize=16,
    )
    ax[1].set_title("Sorted heatmap", fontsize=30, pad=70)

    probplot(100 * prob_df, ax=ax[2], title="Connection percentage")

    probplot(block_sum_df, ax=ax[3], title="Average synapses")


def get_block_edgesums(adj, pred_labels, sort_blocks):
    block_vert_inds, block_inds, block_inv = _get_block_indices(pred_labels)
    block_sums = _calculate_block_edgesum(adj, block_inds, block_vert_inds)
    sort_blocks = prob_df.columns.values
    block_sums = block_sums[np.ix_(sort_blocks, sort_blocks)]
    block_sum_df = pd.DataFrame(data=block_sums, columns=sort_blocks, index=sort_blocks)
    return block_sum_df


def sub_ari(known_inds, true_labels, pred_labels):
    true_known_labels = true_labels[known_inds]
    pred_known_labels = pred_labels[known_inds]
    ari = adjusted_rand_score(true_known_labels, pred_known_labels)
    return ari


# Set up plotting constants
plt.style.use("seaborn-white")
sns.set_palette("deep")
sns.set_context("talk", font_scale=1)


# %% [markdown]
# # Load the data
adj, class_labels, side_labels = load_everything(
    "G", version=BRAIN_VERSION, return_class=True, return_side=True
)

color_adjs = []
for t in GRAPH_TYPES:
    adj = load_everything(t)
    color_adjs.append(adj)

sum_adj = np.sum(color_adjs, axis=0)

embed_adjs = [color_adjs[0], sum_adj]
embed_adjs = [pass_to_ranks(g) for g in embed_adjs]

embed = OmnibusEmbed(n_components=4)
latents = embed.fit_transform(embed_adjs)
latents = np.concatenate(latents, axis=-1)
n_verts = sum_adj.shape[0]
indicator = n_verts * ["AtD"] + n_verts * ["Sum"]
plot_latents = np.concatenate(latents, axis=0)
pairplot(plot_latents, labels=indicator)
plot_class_labels = np.concatenate((class_labels, class_labels))
#%%
pairplot(plot_latents, plot_class_labels, palette="tab20")

#%%
diffs = np.linalg.norm(latents[0] - latents[1], axis=1)
plt.figure(figsize=(20, 10))
sns.set_palette("tab20")
sns.set_context("talk", font_scale=1.25)
uni_classes = np.unique(class_labels)
for i, name in enumerate(uni_classes):
    inds = np.where(class_labels == name)[0]
    class_diffs = diffs[inds]
    sns.distplot(class_diffs, label=name, kde=False, norm_hist=True)
plt.legend()


# %%
