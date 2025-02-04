import numpy as np
from anytree import LevelOrderGroupIter, NodeMixin, PostOrderIter, RenderTree
from anytree.util import leftsibling

from graspy.cluster import GaussianCluster, AutoGMMCluster

valid_methods = ["graspy-gmm", "auto-gmm"]


class DivisiveCluster(NodeMixin):
    def __init__(
        self,
        name="",
        min_split_samples=5,
        parent=None,
        children=None,
        n_init=50,
        cluster_method="graspy-gmm",
    ):
        self.name = name
        self.parent = parent
        if children:
            self.children = children
        self.min_split_samples = min_split_samples
        self.samples_ = None
        self.y_ = None
        self.n_init = n_init
        self.cluster_method = cluster_method

    def fit(self, X, y=None):
        n_samples = X.shape[0]
        self.n_samples_ = n_samples
        self.cum_dist_ = 0
        if n_samples > self.min_split_samples:
            if self.cluster_method == "graspy-gmm":
                cluster = GaussianCluster(
                    min_components=1,
                    max_components=2,
                    n_init=self.n_init,
                    covariance_type="all",
                )
            elif self.cluster_method == "auto-gmm":
                cluster = AutoGMMCluster(
                    min_components=1, max_components=2, max_agglom_size=None
                )
            elif self.cluster_method == "vmm":
                # cluster = VonMisesFisherMixture(n)
                pass
            else:
                raise ValueError(f"`cluster_method` must be one of {valid_methods}")
            cluster.fit(X)
            pred_labels = cluster.predict(X)
            self.pred_labels_ = pred_labels
            self.model_ = cluster
            if hasattr(cluster, "bic_"):
                bics = cluster.bic_
                self.bics_ = bics
                bic_ratio = bics.loc[2].min() / bics.loc[1].min()
                self.bic_ratio_ = bic_ratio
            if cluster.n_components_ != 1:  # recurse
                indicator = pred_labels == 0
                self.X_children_ = (X[indicator, :], X[~indicator, :])
                children = []
                for i, X_child in enumerate(self.X_children_):
                    child = DivisiveCluster(
                        name=self.name + str(i),
                        parent=self,
                        min_split_samples=self.min_split_samples,
                        n_init=self.n_init,
                        cluster_method=self.cluster_method,
                    )
                    child = child.fit(X_child)
                    children.append(child)
                self.children = children
        return self

    def predict_sample(self, sample, label):
        """depricated
        
        Parameters
        ----------
        sample : [type]
            [description]
        label : [type]
            [description]
        
        Returns
        -------
        [type]
            [description]
        """
        if not self.children:
            if not self.samples_:
                self.samples_ = []
            self.samples_.append(sample)
            if not self.y_:
                self.y_ = []
            self.y_.append(label)
            return self
        else:
            pred = self.model_.predict([sample])[0]
            if pred == 0:
                return self.children[0].predict_sample(sample, label)
            else:
                return self.children[1].predict_sample(sample, label)

    def predict(self, X, y=None):
        if not self.children:
            prediction = np.array(X.shape[0] * [self.name])
            return prediction
        else:
            node_preds = self.model_.predict(X, y=None)
            indicator = node_preds == 0
            left_preds = self.children[0].predict(X[indicator, :])
            right_preds = self.children[1].predict(X[~indicator, :])
            # this is a hacky way of making sure arrays have sufficiently large string
            # datatype to not lose information, without making any assumptions about
            # number of splits ahead of time. Sure there is a better way.
            if np.can_cast(left_preds.dtype, right_preds.dtype):
                # everything in left can be safely cast to right
                preds = np.zeros(X.shape[0], dtype=right_preds.dtype)
            elif np.can_cast(right_preds.dtype, left_preds.dtype):
                preds = np.zeros(X.shape[0], dtype=left_preds.dtype)
            else:
                print(left_preds.dtype, right_preds.dtype)
                raise ValueError("Cannot cast strings to proper size")
            preds[indicator] = left_preds
            preds[~indicator] = right_preds
        return preds

    def print_tree(self, print_val="n_samples"):
        for pre, _, node in RenderTree(self):
            if print_val == "n_samples":
                to_print = node.n_samples_
            elif print_val == "bic_ratio":
                if hasattr(node, "bic_ratio_"):
                    to_print = node.bic_ratio_
                else:
                    to_print = None
            treestr = "%s%s (%s)" % (pre, node.name, to_print)
            print(treestr.ljust(8))

    def build_linkage(self, bic_distance=False):
        # get a tuple of node at each level
        levels = []
        for group in LevelOrderGroupIter(self):
            levels.append(group)

        # just find how many nodes are leaves
        # this is necessary only because we need to add n to non-leaf clusters
        num_leaves = 0
        for node in PostOrderIter(self):
            if not node.children:
                num_leaves += 1

        link_count = 0
        node_index = 0
        linkages = []
        labels = []

        for g, group in enumerate(levels[::-1][:-1]):  # reversed and skip the last
            for i in range(len(group) // 2):
                # get partner nodes
                left_node = group[2 * i]
                right_node = group[2 * i + 1]
                # just double check that these are always partners
                assert leftsibling(right_node) == left_node

                # check if leaves, need to add some new fields to track for linkage
                if not left_node.children:
                    left_node._ind = node_index
                    left_node._n_clusters = 1
                    node_index += 1
                    labels.append(left_node.name)

                if not right_node.children:
                    right_node._ind = node_index
                    right_node._n_clusters = 1
                    node_index += 1
                    labels.append(right_node.name)

                # find the parent, count samples
                parent_node = left_node.parent
                n_clusters = left_node._n_clusters + right_node._n_clusters
                parent_node._n_clusters = n_clusters

                # assign an ind to this cluster for the dendrogram
                parent_node._ind = link_count + num_leaves
                link_count += 1

                if not bic_distance:
                    distance = g + 1  # equal height for all links
                else:
                    raise NotImplementedError()
                    # tried to use BIC as linkage distance, but not monotonic.
                    # would need to sort somehow by BIC ratios, but this may not be
                    # possible while preserving splitting nature of the tree

                    # self.cum_dist_ += (left_node.cum_dist_ + right_node.cum_dist_) / 2
                    # self.cum_dist_ += parent_node.bic_ratio_ - 1
                    # distance = self.cum_dist_
                    distance = parent_node.bic_ratio_ - 1

                # add a row to the linkage matrix
                linkages.append([left_node._ind, right_node._ind, distance, n_clusters])

        labels = np.array(labels)
        linkages = np.array(linkages, dtype=np.double)  # needs to be a double for scipy
        return (linkages, labels)

