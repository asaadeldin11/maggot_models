# %% [markdown]
# # Imports
import json
import os
import warnings
from operator import itemgetter
from pathlib import Path
import pickle
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from joblib import Parallel, delayed
from joblib.parallel import Parallel, delayed
from sklearn.metrics import adjusted_rand_score, silhouette_score
import networkx as nx
from spherecluster import SphericalKMeans

from graspy.cluster import GaussianCluster, AutoGMMCluster
from graspy.embed import AdjacencySpectralEmbed, OmnibusEmbed
from graspy.models import DCSBMEstimator, SBMEstimator
from graspy.plot import heatmap, pairplot
from graspy.utils import binarize, cartprod, get_lcc, pass_to_ranks
from src.data import load_everything
from src.utils import export_skeleton_json, savefig
from src.visualization import clustergram, palplot, sankey
from src.hierarchy import signal_flow
from src.embed import lse
from src.io import stashfig

warnings.simplefilter("ignore", category=FutureWarning)


FNAME = os.path.basename(__file__)[:-3]
print(FNAME)


# %% [markdown]
# # Parameters
BRAIN_VERSION = "2019-12-09"
GRAPH_TYPES = ["Gad", "Gaa", "Gdd", "Gda"]
GRAPH_TYPE_LABELS = [r"A $\to$ D", r"A $\to$ A", r"D $\to$ D", r"D $\to$ A"]
N_GRAPH_TYPES = len(GRAPH_TYPES)

SAVEFIGS = True
SAVESKELS = True
SAVEOBJS = True

MIN_CLUSTERS = 2
MAX_CLUSTERS = 3
N_INIT = 50
PTR = True
ONLY_RIGHT = True

embed = "LSE"
cluster = "AutoGMM"
n_components = 4
if cluster == "GMM":
    gmm_params = {"n_init": N_INIT, "covariance_type": "all"}
elif cluster == "AutoGMM":
    gmm_params = {"max_agglom_size": None}
elif cluster == "SKMeans":
    gmm_params = {"n_init": N_INIT}

np.random.seed(23409857)


def stashskel(name, ids, colors, palette=None, **kws):
    if SAVESKELS:
        return export_skeleton_json(
            name, ids, colors, palette=palette, foldername=FNAME, **kws
        )


def stashobj(obj, name, **kws):
    foldername = FNAME
    subfoldername = "objs"
    pathname = "./maggot_models/notebooks/outs"
    if SAVEOBJS:
        path = Path(pathname)
        if foldername is not None:
            path = path / foldername
            if not os.path.isdir(path):
                os.mkdir(path)
            if subfoldername is not None:
                path = path / subfoldername
                if not os.path.isdir(path):
                    os.mkdir(path)
        with open(path / str(name + ".pickle"), "wb") as f:
            pickle.dump(obj, f)


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


adj, class_labels, side_labels, skeleton_labels = load_everything(
    "Gad",
    version=BRAIN_VERSION,
    return_keys=["Merge Class", "Hemisphere"],
    return_ids=True,
)


# select the right hemisphere
if ONLY_RIGHT:
    side = "right hemisphere"
    right_inds = np.where(side_labels == "R")[0]
    adj = adj[np.ix_(right_inds, right_inds)]
    class_labels = class_labels[right_inds]
    skeleton_labels = skeleton_labels[right_inds]
else:
    side = "full brain"

# sort by number of synapses
degrees = adj.sum(axis=0) + adj.sum(axis=1)
sort_inds = np.argsort(degrees)[::-1]
adj = adj[np.ix_(sort_inds, sort_inds)]
class_labels = class_labels[sort_inds]
skeleton_labels = skeleton_labels[sort_inds]

# remove disconnected nodes
adj, lcc_inds = get_lcc(adj, return_inds=True)
class_labels = class_labels[lcc_inds]
skeleton_labels = skeleton_labels[lcc_inds]

# remove pendants
degrees = np.count_nonzero(adj, axis=0) + np.count_nonzero(adj, axis=1)
not_pendant_mask = degrees != 1
not_pendant_inds = np.array(range(len(degrees)))[not_pendant_mask]
adj = adj[np.ix_(not_pendant_inds, not_pendant_inds)]
class_labels = class_labels[not_pendant_inds]
skeleton_labels = skeleton_labels[not_pendant_inds]

# plot degree sequence
d_sort = np.argsort(degrees)[::-1]
degrees = degrees[d_sort]
plt.figure(figsize=(10, 5))
sns.scatterplot(x=range(len(degrees)), y=degrees, s=30, linewidth=0)

known_inds = np.where(class_labels != "Unk")[0]


# %% [markdown]
# #
from graspy.cluster import PartitionalGaussianCluster

# %% [markdown]
# # Run clustering using LSE on the sum graph

n_verts = adj.shape[0]


latent = lse(adj, n_components, regularizer=None, ptr=PTR)
pairplot(latent, labels=class_labels, title=embed)

# %% [markdown]
# #


class PartitionCluster:
    def __init__(self):
        self.min_split_samples = 5

    def fit(self, X, y=None):
        n_samples = X.shape[0]

        if n_samples > self.min_split_samples:
            cluster = GaussianCluster(min_components=1, max_components=2, n_init=20)
            cluster.fit(X)
            self.model_ = cluster
        else:
            self.pred_labels_ = np.zeros(X.shape[0])
            self.left_ = None
            self.right_ = None
            self.model_ = None
            return self

        # recurse
        if cluster.n_components_ != 1:
            pred_labels = cluster.predict(X)
            self.pred_labels_ = pred_labels
            indicator = pred_labels == 0
            self.X_left_ = X[indicator, :]
            self.X_right_ = X[~indicator, :]
            split_left = PartitionCluster()
            self.left_ = split_left.fit(self.X_left_)

            split_right = PartitionCluster()
            self.right_ = split_right.fit(self.X_right_)
        else:
            self.pred_labels_ = np.zeros(X.shape[0])
            self.left_ = None
            self.right_ = None
            self.model_ = None
        return self

    def predict_sample(self, sample):
        model = self.model_
        if model is not None:
            pred = model.predict([sample])[0]
            if pred == 0:
                next_pred = self.left_.predict_sample(sample)
            if pred == 1:
                next_pred = self.right_.predict_sample(sample)
            total_pred = str(pred) + next_pred
        else:
            total_pred = ""
        return total_pred

    def predict(self, X):
        predictions = []
        for sample in X:
            pred = self.predict_sample(sample)
            predictions.append(pred)
        return np.array(predictions)


pgmm = PartitionCluster()
pgmm.fit(latent)
pred_labels = pgmm.predict(latent)

from src.visualization import stacked_barplot

stacked_barplot(pred_labels, class_labels)


# %% [markdown]
# #

uni_labels = np.unique(pred_labels)
# consider only the longest strings:

label_lens = []
for l in uni_labels:
    str_len = len(l)
    label_lens.append(str_len)
label_lens = np.array(label_lens)
max_len = max(label_lens)
print(max_len)

max_inds = np.where(label_lens == max_len)
temp_labels = uni_labels[max_inds]

dist_mat = np.zeros((len(uni_labels), 4))

# consider only temp_labels
# find the ones that are pairs
temp_labels = []
for l in temp_labels:
    temp_str = l[:-2]
    print(temp_str)
    temp_labels = []
    