#%% Load data
import numpy as np
import networkx as nx
from graspy.plot import heatmap, gridplot
from src.data import load_networkx
from src.utils import meta_to_array

graph_type = "Gn"

graph = load_networkx(graph_type)

heatmap(graph, transform="simple-all")

df_adj = nx.to_pandas_adjacency(graph)
adj = df_adj.values

classes = meta_to_array(graph, "Class")
print(np.unique(classes))

nx_ids = np.array(list(graph.nodes()), dtype=int)
df_ids = df_adj.index.values.astype(int)
np.array_equal(nx_ids, df_ids)


def proportional_search(adj, class_map, or_classes, ids, thresh):
    """finds the cell ids of neurons who receive a certain proportion of their 
    input from one of the cells in or_classes 
    
    Parameters
    ----------
    adj : np.array
        adjacency matrix, assumed to be normalized so that columns sum to 1
    class_map : dict
        keys are class names, values are arrays of indices describing where that class
        can be found in the adjacency matrix
    or_classes : list 
        which classes to consider for the input thresholding. Neurons will be selected 
        which satisfy ANY of the input threshold criteria
    ids : np.array
        names of each cell 
    """

    pred_cell_ids = []
    for i, class_name in enumerate(or_classes):
        inds = class_map[class_name]  # indices for neurons of that class
        from_class_adj = adj[inds, :]  # select the rows corresponding to that class
        prop_input = from_class_adj.sum(axis=0)  # sum input from that class
        flag_inds = np.where(prop_input >= thresh[i])[0]  # inds above threshold
        pred_cell_ids += list(ids[flag_inds])  # append to cells which satisfied

    pred_cell_ids = np.unique(pred_cell_ids)

    return pred_cell_ids


#%% Map MW classes to the indices of cells belonging to them
unique_classes, inverse_classes = np.unique(classes, return_inverse=True)
class_map = {}
for i, class_name in enumerate(unique_classes):
    inds = np.where(inverse_classes == i)[0]
    class_map[class_name] = inds
class_map


#%% Estimate the LHN neurons
# must received summed input of >= 5% from at least a SINGLE class of projection neurs
pn_types = ["ORN mPNs", "ORN uPNs", "tPNs", "vPNs"]
lhn_thresh = [0.05, 0.05, 0.05, 0.05]

pred_lhn_ids = proportional_search(adj, class_map, pn_types, df_ids, lhn_thresh)

true_lhn_inds = np.concatenate((class_map["LHN"], class_map["LHN; CN"]))
true_lhn_ids = df_ids[true_lhn_inds]

print("LHN")
print("Recall:")
print(np.isin(true_lhn_ids, pred_lhn_ids).mean())  # how many of the og lhn i got
print("Precision:")
print(np.isin(pred_lhn_ids, true_lhn_ids).mean())  # this is how many of mine are in og
print(len(pred_lhn_ids))

#%% Estimate CN neurons
innate_input_types = ["ORN mPNs", "ORN uPNs", "tPNs", "vPNs", "LHN"]
innate_thresh = 5 * [0.05]

mb_input_types = ["MBON", "MBON; CN"]
mb_thresh = 2 * [0.05]

pred_innate_ids = proportional_search(
    adj, class_map, innate_input_types, df_ids, thresh=innate_thresh
)
pred_learn_ids = proportional_search(
    adj, class_map, mb_input_types, df_ids, thresh=mb_thresh
)
pred_cn_ids = np.intersect1d(pred_learn_ids, pred_innate_ids)  # get input from

true_cn_inds = (class_map["CN"], class_map["LHN; CN"], class_map["MBON; CN"])
true_cn_inds = np.concatenate(true_cn_inds)
true_cn_ids = df_ids[true_cn_inds]

print("CN")
print("Recall:")
print(np.isin(true_cn_ids, pred_cn_ids).mean())  # how many of the og lhn i got
print("Precision:")
print(np.isin(pred_cn_ids, true_cn_ids).mean())  # this is how many of mine are in og
print(len(pred_cn_ids))
#%%
gridplot([adj], inner_hier_labels=classes, height=20, sort_nodes=True)
