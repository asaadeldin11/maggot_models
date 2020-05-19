# %% [markdown]
# ##
import os
import time
from scipy.special import comb

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import Circle
from mpl_toolkits.axes_grid1 import make_axes_locatable
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from scipy.integrate import tplquad
from scipy.stats import gaussian_kde

import pymaid
from graspy.utils import pass_to_ranks
from hyppo.ksample import KSample
from src.data import load_metagraph
from src.graph import MetaGraph, preprocess
from src.hierarchy import signal_flow
from src.io import readcsv, savecsv, savefig
from src.pymaid import start_instance
from src.visualization import (
    CLASS_COLOR_DICT,
    adjplot,
    barplot_text,
    get_mid_map,
    gridmap,
    matrixplot,
    remove_axis,
    remove_spines,
    set_axes_equal,
    stacked_barplot,
)

FNAME = os.path.basename(__file__)[:-3]
print(FNAME)


def stashfig(name, **kws):
    savefig(name, foldername=FNAME, save_on=True, fmt="pdf", **kws)


def stashcsv(df, name, **kws):
    savecsv(df, name, foldername=FNAME, **kws)


# params

level = 7
class_key = f"lvl{level}_labels"

metric = "bic"
bic_ratio = 1
d = 8  # embedding dimension
method = "color_iso"

basename = f"-method={method}-d={d}-bic_ratio={bic_ratio}"
title = f"Method={method}, d={d}, BIC ratio={bic_ratio}"

exp = "137.2-BDP-omni-clust"


# load data
pair_meta = readcsv("meta" + basename, foldername=exp, index_col=0)
pair_meta["lvl0_labels"] = pair_meta["lvl0_labels"].astype(str)
pair_adj = readcsv("adj" + basename, foldername=exp, index_col=0)
pair_adj = pair_adj.values
mg = MetaGraph(pair_adj, pair_meta)
meta = mg.meta


# load connectors
connector_path = "maggot_models/data/processed/2020-05-08/connectors.csv"
connectors = pd.read_csv(connector_path)


# %% [markdown]
# ##

# plot params
scale = 5
n_col = 10
n_row = 3
margin = 0.01
gap = 0.02

rc_dict = {
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.formatter.limits": (-3, 3),
    "figure.figsize": (6, 3),
    "figure.dpi": 100,
    "axes.edgecolor": "grey",
    "ytick.color": "dimgrey",
    "xtick.color": "dimgrey",
    "axes.labelcolor": "dimgrey",
    "text.color": "dimgrey",
}
for k, val in rc_dict.items():
    mpl.rcParams[k] = val
context = sns.plotting_context(context="talk", font_scale=1, rc=rc_dict)
sns.set_context(context)

# compare dendrite inputs

compartment = "dendrite"
direction = "postsynaptic"


def filter_connectors(connectors, ids, direction, compartment):
    label_connectors = connectors[connectors[f"{direction}_to"].isin(ids)]
    label_connectors = label_connectors[
        label_connectors[f"{direction}_type"] == compartment
    ]
    label_connectors = label_connectors[
        ~label_connectors["connector_id"].duplicated(keep="first")
    ]
    return label_connectors


from sklearn.metrics import pairwise_distances


def euclidean(x):
    """Default euclidean distance function calculation"""
    return pairwise_distances(X=x, metric="euclidean", n_jobs=-1)


def run_dcorr(data1, data2):
    ksamp = KSample("Dcorr", compute_distance=euclidean)
    stat, pval = ksamp.test(data1, data2, auto=True)
    return stat, pval


def spatial_dcorr(data1, data2, method="full", max_samples=1000, n_subsamples=5):
    if (len(data1) == 0) or (len(data2) == 0):
        return np.nan, np.nan

    if method == "full":
        stat, p_val = run_dcorr(data1, data2)
    elif method == "subsample":
        stats = np.empty(n_subsamples)
        p_vals = np.empty(n_subsamples)
        for i in range(n_subsamples):
            subsampled_data = []
            for data in [data1, data2]:
                n_subsamples = min(len(data), max_samples)
                inds = np.random.choice(n_subsamples, size=n_subsamples, replace=False)
                subsampled_data.append(data[inds])
            stat, p_val = run_dcorr(*subsampled_data)
            stats[i] = stat
            p_vals[i] = p_val
        stat = np.median(stats)
        p_val = np.median(p_vals)
    elif method == "max-d":
        max_dim_stat = -np.inf
        best_p_val = np.nan
        for dim in range(data1.shape[1]):
            dim_stat, dim_p_val = run_dcorr(data1[:, dim], data2[:, dim])
            if dim_stat > max_dim_stat:
                max_dim_stat = dim_stat
                best_p_val = dim_p_val
        stat = max_dim_stat
        p_val = best_p_val
    else:
        raise ValueError()

    return stat, p_val


# %% [markdown]
# ##

first = 10
class_labels = meta[class_key].unique()[::-1][:first]
p_vals = np.zeros((len(class_labels), len(class_labels)))
stats = np.zeros_like(p_vals)
cluster_meta = pd.DataFrame(index=class_labels)

total = comb(len(class_labels), k=2, exact=True)
count = 0
for i, label1 in enumerate(class_labels):
    label1_meta = meta[meta[class_key] == label1]
    label1_ids = label1_meta.index.values
    label1_connectors = filter_connectors(
        connectors, label1_ids, direction, compartment
    )
    cluster_meta.loc[label1, "n_samples"] = len(label1_connectors)
    for j, label2 in enumerate(class_labels):
        if i < j:
            print(f"Progress: {count / total:.2f}")
            label2_meta = meta[meta[class_key] == label2]
            label2_ids = label2_meta.index.values
            label2_connectors = filter_connectors(
                connectors, label2_ids, direction, compartment
            )
            data1 = label1_connectors[["x", "y", "z"]].values
            data2 = label2_connectors[["x", "y", "z"]].values
            stat, p_val = spatial_dcorr(data1, data2, method="full")
            stats[i, j] = stat
            p_vals[i, j] = p_val
            count += 1

p_val_df = pd.DataFrame(
    data=p_vals, index=cluster_meta.index, columns=cluster_meta.index
)
stashcsv(p_val_df, "p-vals")

stats_df = pd.DataFrame(
    data=stats, index=cluster_meta.index, columns=cluster_meta.index
)
stashcsv(stats_df, "test-stats")

plot_p_vals = -np.log10(p_vals)
plt.figure()
adjplot(
    plot_p_vals,
    meta=cluster_meta,
    vmax=np.nanmax(plot_p_vals[~np.isinf(plot_p_vals)]),
    cbar_kws=dict(shrink=0.7),
    cbar=True,
    cmap="Reds",
)
stashfig("p-val-plot")

plt.figure(figsize=(10, 10))
sns.heatmap(
    stats,
    cmap="Reds",
    cbar_kws=dict(shrink=0.7),
    square=True,
    xticklabels=False,
    yticklabels=False,
)
stashfig("stats-plot")
