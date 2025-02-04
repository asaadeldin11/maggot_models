# %% [markdown]
# # THE MIND OF A MAGGOT

# %% [markdown]
# ## Imports
import os
import time
import warnings
from itertools import chain

import colorcet as cc
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.transforms as transforms
import numpy as np
import pandas as pd
import seaborn as sns
from anytree import LevelOrderGroupIter, NodeMixin
from mpl_toolkits.mplot3d import Axes3D
from scipy.cluster.hierarchy import linkage
from scipy.linalg import orthogonal_procrustes
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import squareform
from sklearn.cluster import AgglomerativeClustering
from sklearn.exceptions import ConvergenceWarning
from sklearn.manifold import MDS
from sklearn.metrics import adjusted_rand_score, pairwise_distances
from sklearn.utils.testing import ignore_warnings

# from tqdm import tqdm

from graspy.cluster import AutoGMMCluster, GaussianCluster
from graspy.embed import (
    AdjacencySpectralEmbed,
    ClassicalMDS,
    LaplacianSpectralEmbed,
    selectSVD,
)
from graspy.models import DCSBMEstimator, RDPGEstimator, SBMEstimator
from graspy.plot import heatmap, pairplot
from graspy.simulations import rdpg
from graspy.utils import augment_diagonal, binarize, pass_to_ranks
from src.cluster import get_paired_inds
from src.data import load_metagraph
from src.graph import preprocess
from src.hierarchy import signal_flow
from src.io import savecsv, savefig
from src.traverse import (
    Cascade,
    RandomWalk,
    TraverseDispatcher,
    to_markov_matrix,
    to_transmission_matrix,
)
from src.visualization import (
    CLASS_COLOR_DICT,
    adjplot,
    barplot_text,
    gridmap,
    matrixplot,
    palplot,
    screeplot,
    set_axes_equal,
    stacked_barplot,
)
from tqdm.autonotebook import tqdm

warnings.filterwarnings(action="ignore", category=ConvergenceWarning)

FNAME = os.path.basename(__file__)[:-3]
print(FNAME)

rc_dict = {
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.formatter.limits": (-3, 3),
    "figure.figsize": (6, 3),
    "figure.dpi": 100,
}
for key, val in rc_dict.items():
    mpl.rcParams[key] = val
context = sns.plotting_context(context="talk", font_scale=1, rc=rc_dict)
sns.set_context(context)

np.random.seed(8888)


def stashfig(name, **kws):
    savefig(name, foldername=FNAME, save_on=True, **kws)


def stashcsv(df, name, **kws):
    savecsv(df, name)


def invert_permutation(p):
    """The argument p is assumed to be some permutation of 0, 1, ..., len(p)-1. 
    Returns an array s, where s[i] gives the index of i in p.
    """
    p = np.asarray(p)
    s = np.empty(p.size, p.dtype)
    s[p] = np.arange(p.size)
    return s


graph_type = "Gad"
mg = load_metagraph(graph_type, version="2020-04-01")
mg = preprocess(
    mg,
    threshold=0,
    sym_threshold=False,
    remove_pdiff=True,
    binarize=False,
    weight="weight",
)
meta = mg.meta

# plot where we are cutting out nodes based on degree
degrees = mg.calculate_degrees()
fig, ax = plt.subplots(1, 1, figsize=(5, 2.5))
sns.distplot(np.log10(degrees["Total edgesum"]), ax=ax)
q = np.quantile(degrees["Total edgesum"], 0.05)
ax.axvline(np.log10(q), linestyle="--", color="r")
ax.set_xlabel("log10(total synapses)")

# remove low degree neurons
idx = meta[degrees["Total edgesum"] > q].index
mg = mg.reindex(idx, use_ids=True)

# remove center neurons # FIXME
idx = mg.meta[mg.meta["hemisphere"].isin(["L", "R"])].index
mg = mg.reindex(idx, use_ids=True)

mg = mg.make_lcc()
mg.calculate_degrees(inplace=True)
meta = mg.meta
meta["inds"] = range(len(meta))
adj = mg.adj

# %% [markdown]
# ## Setup for paths

out_groups = [
    ("dVNC", "dVNC;CN", "dVNC;RG", "dSEZ;dVNC"),
    ("dSEZ", "dSEZ;CN", "dSEZ;LHN", "dSEZ;dVNC"),
    ("motor-PaN", "motor-MN", "motor-VAN", "motor-AN"),
    ("RG", "RG-IPC", "RG-ITP", "RG-CA-LP", "dVNC;RG"),
    ("dUnk",),
]
out_group_names = ["VNC", "SEZ" "motor", "RG", "dUnk"]
source_groups = [
    ("sens-ORN",),
    ("sens-MN",),
    ("sens-photoRh5", "sens-photoRh6"),
    ("sens-thermo",),
    ("sens-vtd",),
    ("sens-AN",),
]
source_group_names = ["Odor", "MN", "Photo", "Temp", "VTD", "AN"]
class_key = "merge_class"

sg = list(chain.from_iterable(source_groups))
og = list(chain.from_iterable(out_groups))
sg_name = "All"
og_name = "All"


np.random.seed(888)
max_hops = 10
n_init = 1024
p = 0.05
traverse = Cascade
simultaneous = True
transition_probs = to_transmission_matrix(adj, p)
transition_probs = to_markov_matrix(adj)

source_inds = meta[meta[class_key].isin(sg)]["inds"].values
out_inds = meta[meta[class_key].isin(og)]["inds"].values


# %% [markdown]
# ## Run paths
print(f"Running {n_init} random walks from each source node...")
paths = []
path_lens = []
for s in source_inds:
    rw = RandomWalk(
        transition_probs, stop_nodes=out_inds, max_hops=10, allow_loops=False
    )
    for n in range(n_init):
        rw.start(s)
        paths.append(rw.traversal_)
        path_lens.append(len(rw.traversal_))

# %% [markdown]
# ## Look at distribution of path lengths
for p in paths:
    path_lens.append(len(p))

sns.distplot(path_lens, kde=False)
stashfig(f"path-length-dist-graph={graph_type}")

paths_by_len = {i: [] for i in range(1, max_hops + 1)}
for p in paths:
    paths_by_len[len(p)].append(p)

# %% [markdown]
# ## Subsampling and selecting paths
path_len = 5
paths = paths_by_len[path_len]
subsample = min(2 ** 13, len(paths))

basename = f"-subsample={subsample}-plen={path_len}-graph={graph_type}"

new_paths = []
for p in paths:
    if p[-1] in out_inds:
        new_paths.append(p)
paths = new_paths
print(f"Number of paths of length {path_len}: {len(paths)}")

if subsample != -1:
    inds = np.random.choice(len(paths), size=subsample, replace=False)
    new_paths = []
    for i, p in enumerate(paths):
        if i in inds:
            new_paths.append(p)
    paths = new_paths

print(f"Number of paths after subsampling: {len(paths)}")


# %% [markdown]
# ## Embed for a dissimilarity measure
print("Embedding graph and finding pairwise distances...")
embedder = AdjacencySpectralEmbed(n_components=None, n_elbows=2)
embed = embedder.fit_transform(pass_to_ranks(adj))
embed = np.concatenate(embed, axis=-1)

lp_inds, rp_inds = get_paired_inds(meta)
R, _, = orthogonal_procrustes(embed[lp_inds], embed[rp_inds])

left_inds = meta[meta["left"]]["inds"]
right_inds = meta[meta["right"]]["inds"]
embed[left_inds] = embed[left_inds] @ R

pdist = pairwise_distances(embed, metric="cosine")


# %% [markdown]
# ## Compute distances between paths
print("Computing pairwise distances between paths...")
path_dist_mat = np.zeros((len(paths), len(paths)))
for i in range(len(paths)):
    for j in range(len(paths)):
        p1 = paths[i]
        p2 = paths[j]
        dist_sum = 0
        for t in range(path_len):
            dist = pdist[p1[t], p2[t]]
            dist_sum += dist
        path_dist_mat[i, j] = dist_sum


path_indicator_mat = np.zeros((len(paths), len(adj)), dtype=int)
for i, p in enumerate(paths):
    for j, visit in enumerate(p):
        path_indicator_mat[i, visit] = j + 1


# %% [markdown]
# ## Cluster and look at distance mat

Z = linkage(squareform(path_dist_mat), method="average")

sns.clustermap(
    path_dist_mat,
    figsize=(20, 20),
    row_linkage=Z,
    col_linkage=Z,
    xticklabels=False,
    yticklabels=False,
)
stashfig("agglomerative-path-dist-mat" + basename)

# %% [markdown]
# ##

from graspy.embed import select_dimension

print("Running CMDS on path dissimilarity...")
X = path_dist_mat
cmds = ClassicalMDS(
    dissimilarity="precomputed", n_components=int(np.ceil(np.log2(np.min(X.shape))))
)
path_embed = cmds.fit_transform(X)
elbows, elbow_vals = select_dimension(cmds.singular_values_, n_elbows=3)
rng = np.arange(1, len(cmds.singular_values_) + 1)
elbows = np.array(elbows)
fig, ax = plt.subplots(1, 1, figsize=(8, 4))
pc = ax.scatter(elbows, elbow_vals, color="red", label="ZG")
pc.set_zorder(10)
ax.plot(rng, cmds.singular_values_, "o-")
ax.legend()
stashfig("cmds-screeplot" + basename)


# %% [markdown]
# ##

pairplot(path_embed, alpha=0.02)
stashfig("cmds-pairs-all" + basename)
# %% [markdown]
# ##
print("Running AGMM on CMDS embedding")
n_components = 4

agmm = AutoGMMCluster(max_components=40, n_jobs=-2)
pred = agmm.fit_predict(path_embed[:, :n_components])

print(f"Number of clusters: {agmm.n_components_}")

# %% [markdown]
# ##
pairplot(
    path_embed[:, :n_components],
    alpha=0.02,
    labels=pred,
    palette=cc.glasbey_light,
    legend_name="Cluster",
)
stashfig("pairplot-agmm-cmds" + basename)

# %% [markdown]
# ##
from sklearn.manifold import Isomap

iso = Isomap(n_components=int(np.ceil(np.log2(np.min(X.shape)))), metric="precomputed")
iso_embed = iso.fit_transform(path_dist_mat)

pairplot(iso_embed, alpha=0.02)
stashfig("isomap-pairs-all" + basename)

# %% [markdown]
# ##
svals = iso.kernel_pca_.lambdas_
elbows, elbow_vals = select_dimension(svals, n_elbows=3)
rng = np.arange(1, len(svals) + 1)
elbows = np.array(elbows)
fig, ax = plt.subplots(1, 1, figsize=(8, 4))
pc = ax.scatter(elbows, elbow_vals, color="red", label="ZG")
pc.set_zorder(10)
ax.plot(rng, svals, "o-")
ax.legend()
stashfig("iso-screeplot" + basename)
n_components = elbows[2]

print("Running AGMM on ISO embedding")


agmm = AutoGMMCluster(max_components=50, n_jobs=-2)
pred = agmm.fit_predict(iso_embed[:, :n_components])

print(f"Number of clusters: {agmm.n_components_}")

pairplot(
    iso_embed[:, :n_components],
    alpha=0.02,
    labels=pred,
    palette=cc.glasbey_light,
    legend_name="Cluster",
)
stashfig("pairplot-agmm-iso" + basename)


# %% [markdown]
# ##
color_dict = dict(zip(np.unique(pred), cc.glasbey_light))
fig, ax = plt.subplots(1, 1, figsize=(20, 20))
adjplot(
    path_dist_mat,
    sort_class=pred,
    cmap=None,
    center=None,
    ax=ax,
    gridline_kws=dict(linewidth=0.5, color="grey", linestyle="--"),
    ticks=False,
    colors=pred,
    palette=color_dict,
    cbar=False,
)
stashfig("adjplot-GMMoCMDSoPathDist" + basename)


# %% [markdown]
# ##

from scipy.cluster.hierarchy import dendrogram

Z = linkage(squareform(path_dist_mat), method="average", optimal_ordering=False)
R = dendrogram(
    Z, truncate_mode=None, get_leaves=True, no_plot=True, color_threshold=-np.inf
)
order = invert_permutation(R["leaves"])

path_meta = pd.DataFrame()
path_meta["cluster"] = pred
path_meta["dend_order"] = order

Z = linkage(squareform(pdist), method="average", optimal_ordering=False)
R = dendrogram(
    Z, truncate_mode=None, get_leaves=True, no_plot=True, color_threshold=-np.inf
)
order = invert_permutation(R["leaves"])

meta["dend_order"] = order
meta["signal_flow"] = -signal_flow(adj)
meta["class2"].fillna(" ", inplace=True)
# %% [markdown]
# ##
fig, axs = plt.subplots(
    1, 2, figsize=(30, 20), gridspec_kw=dict(width_ratios=[0.95, 0.02], wspace=0.02)
)
ax = axs[0]
matrixplot(
    path_indicator_mat,
    ax=ax,
    plot_type="scattermap",
    col_sort_class=["class1", "class2"],
    col_class_order="signal_flow",
    col_ticks=True,
    tick_rot=90,
    col_meta=meta,
    col_colors="merge_class",
    col_palette=CLASS_COLOR_DICT,
    col_item_order="dend_order",
    col_tick_pad=[0.5, 1.5],
    # col_ticks=False,
    row_meta=path_meta,
    row_sort_class="cluster",
    row_item_order="dend_order",
    row_ticks=True,
    gridline_kws=dict(linewidth=0.3, color="grey", linestyle="--"),
    sizes=(2, 2),
    hue="weight",
    palette="tab10",
)
ax.set_ylabel("Cluster")
# fig.suptitle("G")
ax = axs[1]
palplot(path_len, cmap="tab10", ax=ax)
ax.yaxis.tick_right()
ax.set_title("Visit\norder")

stashfig("path-indcator-GMMoCMDSoPathDist" + basename)

# %% [markdown]
# ##

from src.traverse import to_path_graph
import networkx as nx

from src.visualization import draw_networkx_nice

uni_pred = np.unique(pred)

for up in uni_pred:
    mask = pred == up
    hop_hist = np.zeros((path_len, len(meta)))
    sub_path_mat = path_indicator_mat[mask]
    for i in range(path_len):
        num_at_visit = np.count_nonzero(sub_path_mat == i + 1, axis=0)
        hop_hist[i, :] = num_at_visit

    n_visits = hop_hist.sum(axis=0)
    sub_hop_hist = hop_hist[:, n_visits > 0]
    sub_meta = meta[n_visits > 0].copy()
    sum_visit = (sub_hop_hist * np.arange(1, path_len + 1)[:, None]).sum(axis=0)
    sub_n_visits = sub_hop_hist.sum(axis=0)
    mean_visit = sum_visit / sub_n_visits
    sub_meta["mean_visit_int"] = mean_visit.astype(int)
    sub_meta["mean_visit"] = mean_visit

    plot_mat = np.log10(sub_hop_hist + 1)

    Z = linkage(plot_mat.T, metric="cosine", method="average")
    R = dendrogram(Z, no_plot=True, color_threshold=-np.inf)
    order = R["leaves"]
    sub_meta["dend_order"] = invert_permutation(order)

    title = f"Cluster {up}, {len(sub_path_mat) / len(paths):0.2f} paths, {len(sub_meta)} neurons"

    fig, ax = plt.subplots(1, 1, figsize=(16, 8))
    ax, div, top_ax, left_ax = matrixplot(
        plot_mat,
        ax=ax,
        col_sort_class=["mean_visit_int"],
        # col_class_order="mean_visit",
        col_ticks=False,
        col_meta=sub_meta,
        col_colors="merge_class",
        col_palette=CLASS_COLOR_DICT,
        col_item_order=["merge_class", "dend_order"],
        cbar=False,
        gridline_kws=dict(linewidth=0.3, color="grey", linestyle="--"),
    )
    ax.set_yticks(np.arange(1, path_len + 1) - 0.5)
    ax.set_yticklabels(np.arange(1, path_len + 1))
    ax.set_ylabel("Hops")
    top_ax.set_title(title)
    stashfig(f"hop_hist-class-cluster={up}" + basename)

    fig, ax = plt.subplots(1, 1, figsize=(16, 8))
    ax, div, top_ax, left_ax = matrixplot(
        plot_mat,
        ax=ax,
        col_sort_class=["mean_visit_int"],
        # col_class_order="mean_visit",
        col_ticks=False,
        col_meta=sub_meta,
        col_colors="merge_class",
        col_palette=CLASS_COLOR_DICT,
        col_item_order=["dend_order"],
        cbar=False,
        gridline_kws=dict(linewidth=0.3, color="grey", linestyle="--"),
    )
    ax.set_yticks(np.arange(1, path_len + 1) - 0.5)
    ax.set_yticklabels(np.arange(1, path_len + 1))
    ax.set_ylabel("Hops")
    top_ax.set_title(title)
    stashfig(f"hop_hist-cluster={up}" + basename)

    sub_meta["colors"] = sub_meta["merge_class"].map(CLASS_COLOR_DICT)
    sub_meta_dict = sub_meta.set_index("inds").to_dict(orient="index")

    cluster_paths = []
    for i, p in enumerate(paths):
        if mask[i]:
            cluster_paths.append(p)
    path_graph = to_path_graph(cluster_paths)
    nx.set_node_attributes(path_graph, sub_meta_dict)

    for n, d in path_graph.degree():
        path_graph.nodes[n]["degree"] = d

    ax = draw_networkx_nice(
        path_graph,
        "dend_order",
        "mean_visit",
        colors="colors",
        sizes="degree",
        draw_labels=False,
        size_scale=2,
        weight_scale=0.25,
    )
    ax.invert_yaxis()
    ax.set_title(title)
    stashfig(f"path-graph-cluster={up}" + basename)

