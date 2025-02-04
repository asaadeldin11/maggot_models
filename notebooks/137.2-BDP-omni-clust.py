# %% [markdown]
# ##
import os
import warnings

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.transforms as transforms
import numpy as np
import pandas as pd
import seaborn as sns
from joblib import Parallel, delayed
from scipy.stats import poisson
from sklearn.exceptions import ConvergenceWarning
from sklearn.manifold import MDS, TSNE, Isomap
from sklearn.metrics import pairwise_distances
from sklearn.neighbors import NearestNeighbors
from sklearn.utils.testing import ignore_warnings
from tqdm.autonotebook import tqdm
from umap import UMAP

from graspy.embed import (
    AdjacencySpectralEmbed,
    ClassicalMDS,
    LaplacianSpectralEmbed,
    OmnibusEmbed,
    select_dimension,
    selectSVD,
)
from graspy.models import DCSBMEstimator, SBMEstimator
from graspy.plot import pairplot
from graspy.simulations import sbm
from graspy.utils import (
    augment_diagonal,
    binarize,
    pass_to_ranks,
    remove_loops,
    symmetrize,
    to_laplace,
)
from src.align import Procrustes
from src.cluster import BinaryCluster, MaggotCluster, get_paired_inds
from src.data import load_metagraph
from src.graph import preprocess
from src.hierarchy import signal_flow
from src.io import savecsv, savefig
from src.pymaid import start_instance

from src.visualization import (
    CLASS_COLOR_DICT,
    add_connections,
    adjplot,
    barplot_text,
    draw_networkx_nice,
    gridmap,
    matrixplot,
    palplot,
    plot_neurons,
    screeplot,
    set_axes_equal,
    stacked_barplot,
)

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
    savecsv(df, name, foldername=FNAME, **kws)


graph_type = "G"


def plot_pairs(
    X, labels, model=None, left_pair_inds=None, right_pair_inds=None, equal=False
):

    n_dims = X.shape[1]

    fig, axs = plt.subplots(
        n_dims, n_dims, sharex=False, sharey=False, figsize=(20, 20)
    )
    data = pd.DataFrame(data=X)
    data["label"] = labels

    for i in range(n_dims):
        for j in range(n_dims):
            ax = axs[i, j]
            ax.axis("off")
            if i < j:
                sns.scatterplot(
                    data=data,
                    x=j,
                    y=i,
                    ax=ax,
                    alpha=0.7,
                    linewidth=0,
                    s=8,
                    legend=False,
                    hue="label",
                    palette=CLASS_COLOR_DICT,
                )
                if left_pair_inds is not None and right_pair_inds is not None:
                    add_connections(
                        data.iloc[left_pair_inds, j],
                        data.iloc[right_pair_inds, j],
                        data.iloc[left_pair_inds, i],
                        data.iloc[right_pair_inds, i],
                        ax=ax,
                    )

    plt.tight_layout()
    return fig, axs


def preprocess_adjs(adjs, method="ase"):
    adjs = [pass_to_ranks(a) for a in adjs]
    adjs = [a + 1 / a.size for a in adjs]
    if method == "ase":
        adjs = [augment_diagonal(a) for a in adjs]
    elif method == "lse":
        adjs = [to_laplace(a) for a in adjs]
    return adjs


def omni(
    adjs,
    n_components=4,
    remove_first=None,
    concat_graphs=True,
    concat_directed=True,
    method="ase",
):
    adjs = preprocess_adjs(adjs, method=method)
    omni = OmnibusEmbed(n_components=n_components, check_lcc=False, n_iter=10)
    embed = omni.fit_transform(adjs)
    if concat_directed:
        embed = np.concatenate(
            embed, axis=-1
        )  # this is for left/right latent positions
    if remove_first is not None:
        embed = embed[remove_first:]
    if concat_graphs:
        embed = np.concatenate(embed, axis=0)
    return embed


def ipsi_omni(adj, lp_inds, rp_inds, co_adj=None, n_components=4, method="ase"):
    ll_adj = adj[np.ix_(lp_inds, lp_inds)]
    rr_adj = adj[np.ix_(rp_inds, rp_inds)]
    ipsi_adjs = [ll_adj, rr_adj]
    if co_adj is not None:
        co_ll_adj = co_adj[np.ix_(lp_inds, lp_inds)]
        co_rr_adj = co_adj[np.ix_(rp_inds, rp_inds)]
        ipsi_adjs += [co_ll_adj, co_rr_adj]

    out_ipsi, in_ipsi = omni(
        ipsi_adjs,
        n_components=n_components,
        concat_directed=False,
        concat_graphs=False,
        method=method,
    )
    left_embed = np.concatenate((out_ipsi[0], in_ipsi[0]), axis=1)
    right_embed = np.concatenate((out_ipsi[1], in_ipsi[1]), axis=1)
    ipsi_embed = np.concatenate((left_embed, right_embed), axis=0)
    return ipsi_embed


def contra_omni(adj, lp_inds, rp_inds, co_adj=None, n_components=4, method="ase"):
    lr_adj = adj[np.ix_(lp_inds, rp_inds)]
    rl_adj = adj[np.ix_(rp_inds, lp_inds)]
    contra_adjs = [lr_adj, rl_adj]

    if co_adj is not None:
        co_lr_adj = co_adj[np.ix_(lp_inds, rp_inds)]
        co_rl_adj = co_adj[np.ix_(rp_inds, lp_inds)]
        contra_adjs += [co_lr_adj, co_rl_adj]

    out_contra, in_contra = omni(
        contra_adjs,
        n_components=n_components,
        concat_directed=False,
        concat_graphs=False,
        method=method,
    )

    left_embed = np.concatenate((out_contra[0], in_contra[1]), axis=1)
    right_embed = np.concatenate((out_contra[1], in_contra[0]), axis=1)
    contra_embed = np.concatenate((left_embed, right_embed), axis=0)
    return contra_embed


def lateral_omni(adj, lp_inds, rp_inds, n_components=4, method="ase"):
    ipsi_embed = ipsi_omni(
        adj, lp_inds, rp_inds, n_components=n_components, method=method
    )
    contra_embed = contra_omni(
        adj, lp_inds, rp_inds, n_components=n_components, method=method
    )

    embed = np.concatenate((ipsi_embed, contra_embed), axis=1)
    return embed


def quick_embed_viewer(
    embed, labels=None, lp_inds=None, rp_inds=None, left_right_indexing=False
):
    if left_right_indexing:
        lp_inds = np.arange(len(embed) // 2)
        rp_inds = np.arange(len(embed) // 2) + len(embed) // 2

    fig, axs = plt.subplots(3, 2, figsize=(20, 30))

    cmds = ClassicalMDS(n_components=2)
    cmds_euc = cmds.fit_transform(embed)
    plot_df = pd.DataFrame(data=cmds_euc)
    plot_df["labels"] = labels
    plot_kws = dict(
        x=0,
        y=1,
        hue="labels",
        palette=CLASS_COLOR_DICT,
        legend=False,
        s=20,
        linewidth=0.5,
        alpha=0.7,
    )
    ax = axs[0, 0]
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    add_connections(
        plot_df.iloc[lp_inds, 0],
        plot_df.iloc[rp_inds, 0],
        plot_df.iloc[lp_inds, 1],
        plot_df.iloc[rp_inds, 1],
        ax=ax,
    )
    ax.set_title("CMDS o euclidean")

    cmds = ClassicalMDS(n_components=2, dissimilarity="precomputed")
    pdist = symmetrize(pairwise_distances(embed, metric="cosine"))
    cmds_cos = cmds.fit_transform(pdist)
    plot_df[0] = cmds_cos[:, 0]
    plot_df[1] = cmds_cos[:, 1]
    ax = axs[0, 1]
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    add_connections(
        plot_df.iloc[lp_inds, 0],
        plot_df.iloc[rp_inds, 0],
        plot_df.iloc[lp_inds, 1],
        plot_df.iloc[rp_inds, 1],
        ax=ax,
    )
    ax.set_title("CMDS o cosine")

    tsne = TSNE(metric="euclidean")
    tsne_euc = tsne.fit_transform(embed)
    plot_df[0] = tsne_euc[:, 0]
    plot_df[1] = tsne_euc[:, 1]
    ax = axs[1, 0]
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    add_connections(
        plot_df.iloc[lp_inds, 0],
        plot_df.iloc[rp_inds, 0],
        plot_df.iloc[lp_inds, 1],
        plot_df.iloc[rp_inds, 1],
        ax=ax,
    )
    ax.set_title("TSNE o euclidean")

    tsne = TSNE(metric="precomputed")
    tsne_cos = tsne.fit_transform(pdist)
    plot_df[0] = tsne_cos[:, 0]
    plot_df[1] = tsne_cos[:, 1]
    ax = axs[1, 1]
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    add_connections(
        plot_df.iloc[lp_inds, 0],
        plot_df.iloc[rp_inds, 0],
        plot_df.iloc[lp_inds, 1],
        plot_df.iloc[rp_inds, 1],
        ax=ax,
    )
    ax.set_title("TSNE o cosine")

    umap = UMAP(metric="euclidean", n_neighbors=30, min_dist=1)
    umap_euc = umap.fit_transform(embed)
    plot_df[0] = umap_euc[:, 0]
    plot_df[1] = umap_euc[:, 1]
    ax = axs[2, 0]
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    add_connections(
        plot_df.iloc[lp_inds, 0],
        plot_df.iloc[rp_inds, 0],
        plot_df.iloc[lp_inds, 1],
        plot_df.iloc[rp_inds, 1],
        ax=ax,
    )
    ax.set_title("UMAP o euclidean")

    umap = UMAP(metric="cosine", n_neighbors=30, min_dist=1)
    umap_cos = umap.fit_transform(embed)
    plot_df[0] = umap_cos[:, 0]
    plot_df[1] = umap_cos[:, 1]
    ax = axs[2, 1]
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    add_connections(
        plot_df.iloc[lp_inds, 0],
        plot_df.iloc[rp_inds, 0],
        plot_df.iloc[lp_inds, 1],
        plot_df.iloc[rp_inds, 1],
        ax=ax,
    )
    ax.set_title("UMAP o cosine")


def umapper(embed, metric="euclidean", n_neighbors=30, min_dist=1, **kws):
    umap = UMAP(metric=metric, n_neighbors=n_neighbors, min_dist=min_dist)
    umap_euc = umap.fit_transform(embed)
    plot_df = pd.DataFrame(data=umap_euc)
    plot_df["labels"] = labels
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    plot_kws = dict(
        x=0,
        y=1,
        hue="labels",
        palette=CLASS_COLOR_DICT,
        legend=False,
        s=20,
        linewidth=0.5,
        alpha=0.7,
    )
    sns.scatterplot(data=plot_df, ax=ax, **plot_kws)
    ax.axis("off")
    left_right_indexing = True
    if left_right_indexing:
        tlp_inds = np.arange(len(embed) // 2)
        trp_inds = np.arange(len(embed) // 2) + len(embed) // 2
        add_connections(
            plot_df.iloc[tlp_inds, 0],
            plot_df.iloc[trp_inds, 0],
            plot_df.iloc[tlp_inds, 1],
            plot_df.iloc[trp_inds, 1],
            ax=ax,
        )
    return fig, ax


# %% [markdown]
# ## Load and preprocess data
graph_type = "G"
master_mg = load_metagraph(graph_type)
mg = master_mg.remove_pdiff()

meta = mg.meta

degrees = mg.calculate_degrees()
quant_val = np.quantile(degrees["Total edgesum"], 0.05)

# remove low degree neurons
idx = meta[degrees["Total edgesum"] > quant_val].index
print(quant_val)
mg = mg.reindex(idx, use_ids=True)

# remove center neurons # FIXME
idx = mg.meta[mg.meta["hemisphere"].isin(["L", "R"])].index
mg = mg.reindex(idx, use_ids=True)

idx = mg.meta[mg.meta["pair"].isin(mg.meta.index)].index
mg = mg.reindex(idx, use_ids=True)

mg = mg.make_lcc()
mg.calculate_degrees(inplace=True)

meta = mg.meta
meta["pair_td"] = meta["pair_id"].map(meta.groupby("pair_id")["Total degree"].mean())
mg = mg.sort_values(["pair_td", "pair_id"], ascending=False)
meta["inds"] = range(len(meta))
adj = mg.adj.copy()
lp_inds, rp_inds = get_paired_inds(meta)
left_inds = meta[meta["left"]]["inds"]

print(len(mg))


# %% [markdown]
# ## Load the 4-color graphs

graph_types = ["Gad", "Gaa", "Gdd", "Gda"]
adjs = []
for g in graph_types:
    temp_mg = load_metagraph(g)
    temp_mg.reindex(mg.meta.index, use_ids=True)
    temp_adj = temp_mg.adj
    adjs.append(temp_adj)

# %% [markdown]
# ## SVDer
# 8, 16 seems to work
n_omni_components = 8  # this is used for all of the embedings initially
n_svd_components = 16  # this is for the last step
method = "ase"


def svd(X, n_components=n_svd_components):
    return selectSVD(X, n_components=n_components, algorithm="full")[0]


# %% [markdown]
# # Iso Omni, sum graph

full_adjs = [
    adj[np.ix_(lp_inds, lp_inds)],
    adj[np.ix_(lp_inds, rp_inds)],
    adj[np.ix_(rp_inds, rp_inds)],
    adj[np.ix_(rp_inds, lp_inds)],
]
out_embed, in_embed = omni(
    full_adjs,
    n_components=n_omni_components,
    remove_first=None,
    concat_graphs=False,
    concat_directed=False,
    method=method,
)

# ipsi out, contra out, ipsi in, contra in
left_embed = np.concatenate(
    (out_embed[0], out_embed[1], in_embed[0], in_embed[3]), axis=1
)
right_embed = np.concatenate(
    (out_embed[2], out_embed[3], in_embed[2], in_embed[1]), axis=1
)
omni_iso_embed = np.concatenate((left_embed, right_embed), axis=0)

svd_iso_embed = svd(omni_iso_embed)

# %% [markdown]
# ## Aniso OMNI on G, SVD

omni_aniso_embed = lateral_omni(
    adj, lp_inds, rp_inds, n_components=n_omni_components, method=method
)
svd_aniso_embed = svd(omni_aniso_embed)

# %% [markdown]
# ## Iso OMNI, 4-color graphs

all_sub_adjs = []
for a in adjs:
    sub_adjs = [
        a[np.ix_(lp_inds, lp_inds)],
        a[np.ix_(lp_inds, rp_inds)],
        a[np.ix_(rp_inds, rp_inds)],
        a[np.ix_(rp_inds, lp_inds)],
    ]
    all_sub_adjs += sub_adjs


out_embed, in_embed = omni(
    all_sub_adjs,
    n_components=n_omni_components,
    remove_first=None,
    concat_graphs=False,
    concat_directed=False,
    method=method,
)

color_embeds = []
for i in range(len(adjs)):
    start = i * 4  # 4 is for contra/ipsi left/right
    left_embed = np.concatenate(
        (
            out_embed[0 + start],
            out_embed[1 + start],
            in_embed[0 + start],
            in_embed[3 + start],
        ),
        axis=1,
    )
    right_embed = np.concatenate(
        (
            out_embed[2 + start],
            out_embed[3 + start],
            in_embed[2 + start],
            in_embed[1 + start],
        ),
        axis=1,
    )
    color_embed = np.concatenate((left_embed, right_embed), axis=0)
    color_embeds.append(color_embed)

omni_color_embed = np.concatenate(color_embeds, axis=1)
svd_color_iso_embed = svd(omni_color_embed)

# omni_iso_embed = np.concatenate((left_embed, right_embed), axis=0)

# %% [markdown]
# ## Define what we want to look at
n_pairs = len(lp_inds)
new_lp_inds = np.arange(n_pairs)
new_rp_inds = np.arange(n_pairs) + n_pairs
names = ["iso", "aniso", "color_iso"]
embeds = [svd_iso_embed, svd_aniso_embed, svd_color_iso_embed]
new_meta = meta.iloc[np.concatenate((lp_inds, rp_inds), axis=0)].copy()
labels = new_meta["merge_class"].values


# %% [markdown]
# ## Look at the best one! (ish)

# new_meta = meta.iloc[np.concatenate((lp_inds, rp_inds), axis=0)].copy()
# labels = new_meta["merge_class"].values
plot_pairs(
    svd_color_iso_embed[:, :8],
    labels,
    left_pair_inds=new_lp_inds,
    right_pair_inds=new_rp_inds,
)
stashfig("color_iso-pairs")

quick_embed_viewer(
    svd_color_iso_embed, labels=labels, lp_inds=new_lp_inds, rp_inds=new_rp_inds
)
stashfig("color_iso-manifold")


# %% [markdown]
# ## Cluster

n_levels = 12  # max # of splits
metric = "bic"
bic_ratio = 1
d = 8  # embedding dimension
method = "color_iso"
if method == "aniso":
    X = svd_aniso_embed
elif method == "iso":
    X = svd_iso_embed
elif method == "color_iso":
    X = svd_color_iso_embed
X = X[:, :d]
basename = f"-method={method}-d={d}-bic_ratio={bic_ratio}"
title = f"Method={method}, d={d}, BIC ratio={bic_ratio}"

np.random.seed(8888)
mc = BinaryCluster(
    "0",
    adj=adj,
    n_init=50,
    meta=new_meta,
    stashfig=stashfig,
    X=X,
    bic_ratio=bic_ratio,
    reembed=False,
    min_split=4,
)

mc.fit(n_levels=n_levels, metric=metric)

n_levels = mc.height

show_bars = False
if show_bars:
    fig, axs = plt.subplots(1, n_levels, figsize=(8 * n_levels, 30))
    for i in range(n_levels):
        ax = axs[i]
        stacked_barplot(
            mc.meta[f"lvl{i}_labels_side"],
            mc.meta["merge_class"],
            category_order=np.unique(mc.meta[f"lvl{i}_labels_side"].values),
            color_dict=CLASS_COLOR_DICT,
            norm_bar_width=False,
            ax=ax,
        )
        ax.set_yticks([])
        ax.get_legend().remove()
        ax.set_title(title)

    plt.tight_layout()

    stashfig(f"count-barplot-lvl{i}" + basename)
    plt.close()


inds = np.concatenate((lp_inds, rp_inds))
new_adj = adj[np.ix_(inds, inds)]
new_meta = mc.meta
new_meta["sf"] = -signal_flow(new_adj)

for l in range(n_levels):
    fig, ax = plt.subplots(1, 1, figsize=(20, 20))
    sort_class = [f"lvl{i}_labels" for i in range(l)]
    sort_class += [f"lvl{l}_labels_side"]  # leaf nodes show left/right split also
    _, _, top, _ = adjplot(
        new_adj,
        meta=new_meta,
        sort_class=sort_class,
        item_order="merge_class",
        plot_type="scattermap",
        class_order="sf",
        sizes=(0.5, 1),
        ticks=False,
        colors="merge_class",
        ax=ax,
        palette=CLASS_COLOR_DICT,
        gridline_kws=dict(linewidth=0.2, color="grey", linestyle="--"),
    )
    top.set_title(title + f", level={l}")
    stashfig(f"adj-lvl{l}" + basename)
    plt.close()

stashcsv(new_meta, "meta" + basename)
adj_df = pd.DataFrame(new_adj, index=new_meta.index, columns=new_meta.index)
stashcsv(adj_df, "adj" + basename)

# %% [markdown]
# ##
pairs = np.unique(new_meta["pair_id"])
p_same_clusters = []
p_same_chance = []
rows = []
n_shuffles = 10
for l in range(n_levels):
    n_same = 0
    pred_labels = new_meta[f"lvl{l}_labels"].values.copy()
    left_labels = pred_labels[new_lp_inds]
    right_labels = pred_labels[new_rp_inds]
    n_same = (left_labels == right_labels).sum()
    p_same = n_same / len(pairs)
    rows.append(dict(p_same_cluster=p_same, labels="True", level=l))

    # look at random chance
    for i in range(n_shuffles):
        np.random.shuffle(pred_labels)
        left_labels = pred_labels[new_lp_inds]
        right_labels = pred_labels[new_rp_inds]
        n_same = (left_labels == right_labels).sum()
        p_same = n_same / len(pairs)
        rows.append(dict(p_same_cluster=p_same, labels="Shuffled", level=l))

plot_df = pd.DataFrame(rows)
fig, ax = plt.subplots(1, 1, figsize=(8, 4))
sns.lineplot(data=plot_df, x="level", y="p_same_cluster", ax=ax, hue="labels")
ax.set_ylabel("P same cluster")
ax.set_xlabel("Level")
ax.set_title(title)
stashfig("p_in_same_cluster" + basename)

n_clusters = []
for l in range(n_levels):
    n_clusters.append(new_meta[f"lvl{l}_labels"].nunique())

fig, ax = plt.subplots(1, 1, figsize=(8, 4))
sns.lineplot(x=range(n_levels), y=n_clusters, ax=ax)
sns.scatterplot(x=range(n_levels), y=n_clusters, ax=ax)
ax.set_ylabel("Clusters per side")
ax.set_xlabel("Level")
ax.set_title(title)
stashfig("n_cluster" + basename)

size_dfs = []
for l in range(n_levels):
    sizes = new_meta.groupby(f"lvl{l}_labels_side").size().values
    sizes = pd.DataFrame(data=sizes, columns=["Size"])
    sizes["Level"] = l
    size_dfs.append(sizes)

size_df = pd.concat(size_dfs)
fig, ax = plt.subplots(1, 1, figsize=(8, 4))
sns.stripplot(data=size_df, x="Level", y="Size", ax=ax, jitter=0.45, alpha=0.5)
ax.set_yscale("log")
ax.set_title(title)
stashfig("log-sizes" + basename)

# %% [markdown]
# ## Fit models and compare L/R

rows = []

for l in range(n_levels):
    labels = new_meta[f"lvl{l}_labels"].values
    left_adj = binarize(new_adj[np.ix_(new_lp_inds, new_lp_inds)])
    left_adj = remove_loops(left_adj)
    right_adj = binarize(new_adj[np.ix_(new_rp_inds, new_rp_inds)])
    right_adj = remove_loops(right_adj)
    for model, name in zip([DCSBMEstimator, SBMEstimator], ["DCSBM", "SBM"]):
        estimator = model(directed=True, loops=False)
        uni_labels, inv = np.unique(labels, return_inverse=True)
        estimator.fit(left_adj, inv[new_lp_inds])
        train_left_p = estimator.p_mat_
        train_left_p[train_left_p == 0] = 1 / train_left_p.size

        score = poisson.logpmf(left_adj, train_left_p).sum()
        rows.append(
            dict(
                train_side="left",
                test="same",
                test_side="left",
                score=score,
                level=l,
                model=name,
            )
        )
        score = poisson.logpmf(right_adj, train_left_p).sum()
        rows.append(
            dict(
                train_side="left",
                test="opposite",
                test_side="right",
                score=score,
                level=l,
                model=name,
            )
        )

        estimator = model(directed=True, loops=False)
        estimator.fit(right_adj, inv[new_rp_inds])
        train_right_p = estimator.p_mat_
        train_right_p[train_right_p == 0] = 1 / train_right_p.size

        score = poisson.logpmf(left_adj, train_right_p).sum()
        rows.append(
            dict(
                train_side="right",
                test="opposite",
                test_side="left",
                score=score,
                level=l,
                model=name,
            )
        )
        score = poisson.logpmf(right_adj, train_right_p).sum()
        rows.append(
            dict(
                train_side="right",
                test="same",
                test_side="right",
                score=score,
                level=l,
                model=name,
            )
        )


# %% [markdown]
# ## Plot model results

plot_df = pd.DataFrame(rows)

fig, ax = plt.subplots(1, 1, figsize=(8, 4))
model_name = "SBM"
sns.lineplot(
    data=plot_df[plot_df["model"] == model_name],
    hue="test",
    x="level",
    y="score",
    style="train_side",
)
ax.get_legend().remove()
ax.legend(bbox_to_anchor=(1, 1), loc="upper left")
ax.set_title(title)
ax.set_ylabel(f"{model_name} log lik.")
stashfig("sbm-lik-curves" + basename)

model_name = "DCSBM"
fig, ax = plt.subplots(1, 1, figsize=(8, 4))
sns.lineplot(
    data=plot_df[plot_df["model"] == model_name],
    hue="test",
    x="level",
    y="score",
    style="train_side",
)
ax.get_legend().remove()
ax.legend(bbox_to_anchor=(1, 1), loc="upper left")
ax.set_title(title)
ax.set_ylabel(f"{model_name} log lik.")
stashfig("dcsbm-lik-curves" + basename)


# %% [markdown]
# ## Plot neurons
lvl = 4
show_neurons = False

if show_neurons:
    uni_labels = np.unique(new_meta[f"lvl{lvl}_labels"])
    start_instance()

    for label in uni_labels:
        plot_neurons(new_meta, f"lvl{lvl}_labels", label=label, barplot=True)
        stashfig(f"label{label}_lvl{lvl}" + basename)


# %%
