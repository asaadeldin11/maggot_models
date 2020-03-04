# %% [markdown]
# #
import itertools
import os
import time
from pathlib import Path

import colorcet as cc
import matplotlib.colors as mplc
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
import textdistance
from joblib import Parallel, delayed

from graspy.embed import AdjacencySpectralEmbed
from graspy.plot import gridplot, heatmap, pairplot
from graspy.utils import get_lcc, symmetrize
from src.data import load_metagraph
from src.embed import ase, lse, preprocess_graph
from src.graph import MetaGraph, preprocess
from src.io import savecsv, savefig, saveskels, savelol
from src.traverse import (
    generate_random_cascade,
    generate_random_walks,
    path_to_visits,
    to_markov_matrix,
    to_path_graph,
)
from src.visualization import (
    CLASS_COLOR_DICT,
    barplot_text,
    draw_networkx_nice,
    remove_spines,
    screeplot,
    stacked_barplot,
)

FNAME = os.path.basename(__file__)[:-3]
print(FNAME)


def stashfig(name, **kws):
    savefig(name, foldername=FNAME, save_on=True, **kws)


def stashcsv(df, name, **kws):
    savecsv(df, name, foldername=FNAME, save_on=True, **kws)


def stashlol(df, name, **kws):
    savelol(df, name, foldername=FNAME, save_on=True, **kws)


#%% Load and preprocess the data

VERSION = "2020-03-02"
print(f"Using version {VERSION}")

graph_type = "G"
threshold = 0
weight = "weight"
all_out = False
mg = load_metagraph(graph_type, VERSION)
mg = preprocess(
    mg,
    threshold=threshold,
    sym_threshold=True,
    remove_pdiff=False,
    binarize=False,
    weight=weight,
)
print(f"Preprocessed graph {graph_type} with threshold={threshold}, weight={weight}")

# %% [markdown]
# # Setup the simulations
class_key = "Merge Class"

out_groups = [("O_dVNC",), ("O_dSEZ",), ("O_IPC", "O_ITP", "O_CA-LP")]

sens_groups = [
    ("sens-ORN",),
    ("sens-photoRh5", "sens-photoRh6"),
    ("sens-PaN", "sens-MN"),
    ("sens-thermo;AN",),
]

adj = nx.to_numpy_array(mg.g, weight=weight, nodelist=mg.meta.index.values)
n_verts = len(adj)
meta = mg.meta.copy()
g = mg.g.copy()
meta["idx"] = range(len(meta))
ind_map = dict(zip(meta.index, meta["idx"]))
g = nx.relabel_nodes(g, ind_map, copy=True)
prob_mat = to_markov_matrix(adj)
n_walks = 100
max_walk = 30

# %% [markdown]
# ## Generate paths SOMEHOW

import csv
from sklearn.model_selection import ParameterGrid

basename = (
    f"sm-paths-{graph_type}-t{threshold}-w{weight}-nwalks{n_walks}-maxwalk{max_walk}"
)


def run_random_walks(sens_classes=None, out_classes=None):
    from_inds = meta[meta[class_key].isin(sens_classes)]["idx"].values
    out_inds = meta[meta[class_key].isin(out_classes)]["idx"].values
    paths, _ = generate_random_walks(
        prob_mat, from_inds, out_inds, n_walks=n_walks, max_walk=max_walk
    )
    stashlol(paths, basename + f"{sens_classes}-{out_classes}")


np.random.seed(8888889)
n_replicates = 1
param_grid = {"out_classes": out_groups, "sens_classes": sens_groups}
params = list(ParameterGrid(param_grid))
seeds = np.random.randint(1e8, size=n_replicates * len(params))
param_keys = random_names(len(seeds))


rep_params = []
for i, seed in enumerate(seeds):
    p = params[i % len(params)].copy()
    p["seed"] = seed
    p["param_key"] = param_keys[i]
    rep_params.append(p)

print("\n\n\n\n")
print(f"Running {len(rep_params)} jobs in total")
print("\n\n\n\n")
currtime = time.time()
outs = Parallel(n_jobs=-2, verbose=10)(
    delayed(run_random_walks)(**p) for p in rep_params
)
print(f"{time.time() - currtime} elapsed")

# group_pair_map[(sens_classes, out_classes)] = paths
# from_visit_orders = path_to_visits(paths, n_verts, from_order=True)
# for node, orders in from_visit_orders.items():
#     node_encodings[node].append(np.median(orders))
# out_visit_orders = path_to_visits(
#     paths, n_verts, from_order=False, out_inds=out_inds
# )
# for node, orders in out_visit_orders.items():
#     node_encodings[node].append(np.median(orders))

print(f"{time.time() - currtime} elapsed")


# %% [markdown]
# #
encoding_df = pd.DataFrame(node_encodings).T
encoding_df = encoding_df.fillna(0)

from sklearn.decomposition import PCA

from graspy.plot import pairplot

embedding = PCA(n_components=8).fit_transform(encoding_df.values)

pairplot(embedding, labels=meta["Merge Class"].values, palette=CLASS_COLOR_DICT)

# %% [markdown]
# #
encoding_df["Merge Class"] = meta["Merge Class"].values
fig, ax = plt.subplots(1, 1, figsize=(10, 10))
sns.scatterplot(
    data=encoding_df,
    x=0,
    y=1,
    hue="Merge Class",
    palette=CLASS_COLOR_DICT,
    legend=False,
)


# %% [markdown]
# #


@njit()
def _simulate_walk(s, prob_mat, out_inds, dead_inds, max_walk):
    n_verts = len(prob_mat)
    curr_ind = s
    n_steps = 0
    path = [s]
    while (
        (curr_ind not in out_inds)
        and (n_steps <= max_walk)
        and (curr_ind not in dead_inds)
    ):
        next_ind = np.random.choice(n_verts, p=prob_mat[curr_ind])
        n_steps += 1
        curr_ind = next_ind
        path.append(curr_ind)
    if curr_ind in out_inds:
        return path
    else:
        return None


dead_inds = np.where(prob_mat.sum(axis=1) == 0)[0]
_simulate_walk(1, prob_mat, out_inds, dead_inds, max_walk)

# %% [markdown]
# #

# from_inds = meta[meta[class_key].isin(sens_classes)]["idx"].values
# out_inds = meta[meta[class_key].isin(out_classes)]["idx"].values

# out_ind_map = dict(zip(out_inds, range(len(out_inds))))

# %% [markdown]
# ##
from src.traverse import generate_random_walks_fast


currtime = time.time()

print(f"{time.time() - currtime} elapsed")


def calculate_path_lengths(paths):
    lens = []
    for path in paths:
        lens.append(len(path))
    return lens


path_lens = calculate_path_lengths(paths)

sns.distplot(path_lens)


# # %% [markdown]
# # # Try the propogation thing

# p = 0.01
# not_probs = (1 - p) ** adj  # probability of none of the synapses causing postsynaptic
# probs = 1 - not_probs  # probability of ANY of the synapses firing onto next

# # %% [markdown]
# # ## generate random "waves"
# currtime = time.time()

# n_sims = 1
# paths = []
# for f in from_inds[:1]:
#     for i in range(n_sims):
#         temp_paths = generate_random_cascade(
#             f, probs, 0, stop_inds=out_inds, max_depth=15
#         )
#         paths += temp_paths

# print(len(paths))
# print(f"{time.time() - currtime} elapsed")


# # %% [markdown]
# # #

# meta["median_visit"] = -1
# meta["n_visits"] = 0

# visit_orders = path_to_visits(paths, n_verts)

# for node_ind, visits in visit_orders.items():
#     median_order = np.median(visits)
#     meta.iloc[node_ind, meta.columns.get_loc("median_visit")] = median_order
#     meta.iloc[node_ind, meta.columns.get_loc("n_visits")] = len(visits)

