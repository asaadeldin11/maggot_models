import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import seaborn as sns
from src.visualization import gridmap, remove_spines
from mpl_toolkits.axes_grid1 import make_axes_locatable
import matplotlib as mpl
from matplotlib.colors import ListedColormap


def sort_meta(meta, sort_class, sort_item=None, class_order="size"):
    if sort_item is None:
        sort_item = []
    if isinstance(class_order, str):
        class_order = [class_order]
    meta = meta.copy()
    total_sort_by = []
    for sc in sort_class:
        if class_order == "size":
            class_size = meta.groupby(sc).size()
            # negative so we can sort alphabetical still in one line
            meta[f"{sc}_size"] = -meta[sc].map(class_size)
            total_sort_by.append(f"{sc}_size")
        elif class_order is not None:
            for co in class_order:
                class_value = meta.groupby(sc)[co].mean()
                meta[f"{sc}_{co}_order"] = meta[sc].map(class_value)
                total_sort_by.append(f"{sc}_{co}_order")
        total_sort_by.append(sc)
    total_sort_by += sort_item
    meta["sort_idx"] = range(len(meta))
    if len(total_sort_by) > 0:
        meta.sort_values(total_sort_by, inplace=True)
    perm_inds = meta["sort_idx"].values
    return perm_inds, meta


def remove_shared_ax(ax):
    shax = ax.get_shared_x_axes()
    shay = ax.get_shared_y_axes()
    shax.remove(ax)
    shay.remove(ax)
    for axis in [ax.xaxis, ax.yaxis]:
        ticker = mpl.axis.Ticker()
        axis.major = ticker
        axis.minor = ticker
        loc = mpl.ticker.NullLocator()
        fmt = mpl.ticker.NullFormatter()
        axis.set_major_locator(loc)
        axis.set_major_formatter(fmt)
        axis.set_minor_locator(loc)
        axis.set_minor_formatter(fmt)


def get_colors(labels, palette, desat=0.7):
    if isinstance(palette, dict):
        colors = np.vectorize(palette.get)(labels)
        return colors
    elif isinstance(palette, str):
        uni_labels = np.unique(labels)
        palette = sns.color_palette(palette, n_colors=len(uni_labels), desat=desat)
        return get_colors(labels, dict(zip(uni_labels, palette)))


def draw_colors(
    ax, divider=None, ax_type="x", colors=None, palette="tab10", sort_meta=None
):
    if colors is not None:
        if ax_type == "x":
            cax = divider.append_axes("top", size="3%", pad=0, sharex=ax)
        elif ax_type == "y":
            cax = divider.append_axes("left", size="3%", pad=0, sharey=ax)

        if isinstance(colors, str):  # string indexes a column in meta
            classes = sort_meta[colors]
        elif isinstance(colors, (list, np.ndarray, pd.Series)):
            classes = colors  # TODO make sure this is a series

        if isinstance(palette, dict):
            color_dict = palette
        elif isinstance(palette, str):
            color_dict = dict(
                zip(classes.unique(), sns.color_palette(palette, classes.nunique()))
            )
        # make colormap
        uni_classes = np.unique(classes)
        class_map = dict(zip(uni_classes, range(len(uni_classes))))
        color_sorted = np.vectorize(color_dict.get)(uni_classes)
        # HACK fix the below 3 lines
        color_sorted = np.array(color_sorted)
        if len(color_sorted) != len(uni_classes):
            color_sorted = color_sorted.T
        lc = ListedColormap(color_sorted)
        # map each class to an integer to use to make the color heatmap
        class_indicator = np.vectorize(class_map.get)(classes)

        if ax_type == "x":
            class_indicator = class_indicator.reshape(1, len(classes))
        elif ax_type == "y":
            class_indicator = class_indicator.reshape(len(classes), 1)
        sns.heatmap(
            class_indicator,
            cmap=lc,
            cbar=False,
            yticklabels=False,
            xticklabels=False,
            ax=cax,
            square=False,
        )
        return cax
    else:
        return ax


# def _get_tick_info(sort_meta, all_sort_class, level_sort_class):
#     """ Assumes meta is already sorted
#     """
#     if sort_meta is not None and all_sort_class is not None:
#         # get locations
#         sort_meta["sort_idx"] = range(len(sort_meta))

#         # for the gridlines
#         first_df = sort_meta.groupby(all_sort_class, sort=False).first()
#         first_df.reset_index(inplace=True)f
#         first_df = first_df.groupby(level_sort_class, sort=False).first()
#         first_inds = list(first_df["sort_idx"].values)
#         last_df = sort_meta.groupby(all_sort_class, sort=False).last()
#         last_df.reset_index(inplace=True)
#         last_df = last_df.groupby(level_sort_class, sort=False).last()
#         first_inds.append(last_df["sort_idx"].values[-1] + 1)

#         # for the tic locs
#         ind = np.where(np.array(all_sort_class) == level_sort_class)[0][0]
#         middle_df = sort_meta.groupby(all_sort_class[: ind + 1], sort=False).mean()
#         # middle_df.reset_index(inplace=True)
#         # middle_df.groupby(level_sort_class, sort=False).mean()
#         middle_inds = np.array(middle_df["sort_idx"].values) + 0.5

#         # middle_labels = list(middle_df.index)
#         middle_labels = list(middle_df.index.get_level_values(level_sort_class))
#         return first_inds, middle_inds, middle_labels
#     else:
#         return None, None, None


def _get_separator_info(sort_meta, sort_class):
    """ Assumes meta is already sorted
    """
    if sort_meta is None and sort_class is None:
        return None

    sort_meta["sort_idx"] = range(len(sort_meta))
    first_df = sort_meta.groupby(sort_class, sort=False).first()
    sep_inds = list(first_df["sort_idx"].values)
    last_df = sort_meta.groupby(sort_class, sort=False).last()
    sep_inds.append(last_df["sort_idx"].values[-1] + 1)
    return sep_inds


def _get_tick_info(sort_meta, sort_class):
    if sort_meta is None and sort_class is None:
        return None, None

    # first_df = sort_meta.groupby(sort_class, sort=False).first()

    middle_df = sort_meta.groupby(sort_class, sort=False).mean()
    middle_inds = np.array(middle_df["sort_idx"].values) + 0.5
    middle_labels = list(middle_df.index.get_level_values(sort_class[0]))

    # need to return the location of the tick, the label, and the divider
    return middle_inds, middle_labels


def draw_ticks(
    tick_ax,
    sort_meta=None,
    sort_class=None,
    ax_type="x",
    tick_rot=0,
    tick_ax_border=True,
):
    tick_inds, tick_labels = _get_tick_info(sort_meta, sort_class)
    if tick_rot != 0:
        ha = "left"
    else:
        ha = "center"
    if ax_type == "x":
        tick_ax.set_xticks(tick_inds)
        tick_ax.set_xticklabels(tick_labels, rotation=tick_rot, ha=ha, va="bottom")
        tick_ax.xaxis.tick_top()
    else:
        tick_ax.set_yticks(tick_inds)
        tick_ax.set_yticklabels(tick_labels, ha="right", va="center")

    if tick_ax_border:
        sep_inds = _get_separator_info(sort_meta, sort_class)
        for t in sep_inds:
            if ax_type == "x":
                tick_ax.axvline(t, color="black", linestyle="-", alpha=1, linewidth=2)
            else:
                tick_ax.axhline(t, color="black", linestyle="-", alpha=1, linewidth=2)


def draw_separators(
    ax,
    ax_type="x",
    sort_meta=None,
    sort_class=None,
    plot_type="heatmap",
    gridline_kws=None,
):
    """[summary]
    
    Parameters
    ----------
    ax : [type]
        [description]
    ax_type : str, optional
        [description], by default "x"
    sort_meta : [type], optional
        [description], by default None
    sort_class : [type], optional
        [description], by default None
    divider : [type], optional
        [description], by default None
    colors : dict or string, optional
        By default, None, no colors are plotted for categorical labels
        if dict, should map elements of `sort_class` to a color
        if string, should be a palette specification (see mpl/sns) # TODO broken
    plot_type : str, optional
        [description], by default "heatmap"
    gridline_kws : [type], optional
        [description], by default None
    use_ticks : bool, optional
        [description], by default True
    tick_fontsize : int, optional
        [description], by default 10
    minor_ticking : bool, optional
        [description], by default False
    tick_rot : int, optional
        [description], by default 45
    
    Returns
    -------
    [type]
        [description]
    """

    if gridline_kws is None:
        gridline_kws = dict(color="grey", linestyle="--", alpha=0.7, linewidth=1)

    if plot_type == "heatmap":
        boost = 0
    elif plot_type == "scattermap":
        boost = 0.5

    # get info about the separators
    # first_inds, middle_inds, middle_labels = _get_tick_info(
    #     sort_meta, all_sort_class, level_sort_class
    # )

    sep_inds = _get_separator_info(sort_meta, sort_class)

    if ax_type == "x":
        lims = ax.get_xlim()
        drawer = ax.axvline
        # if tick_ax_border:
        #     tick_drawer = tick_ax.axvline
    else:
        lims = ax.get_ylim()
        drawer = ax.axhline
        # if tick_ax_border:
        #     tick_drawer = tick_ax.axhline

    # draw the border lines
    for t in sep_inds:
        if t not in lims:
            drawer(t - boost, **gridline_kws)
        # if tick_ax_border:
        #     tick_drawer(t - boost, color="black", linestyle="-", alpha=1, linewidth=2)

    # if use_ticks:
    #     # add tick labels and locs
    #     if ax_type == "x":
    #         tick_ax.set_xticks(middle_inds)
    #         if minor_ticking:
    #             tick_ax.set_xticklabels(middle_labels[0::2])
    #             tick_ax.set_xticklabels(middle_labels[1::2], minor=True)
    #         else:
    #             if tick_rot != 0:
    #                 tick_ax.set_xticklabels(
    #                     middle_labels, rotation=tick_rot, ha="left", va="bottom"
    #                 )
    #             else:
    #                 tick_ax.set_xticklabels(
    #                     middle_labels, rotation=tick_rot, ha="center", va="bottom"
    #                 )
    #         tick_ax.xaxis.tick_top()
    #     elif ax_type == "y":
    #         tick_ax.set_yticks(middle_inds)
    #         if minor_ticking:
    #             tick_ax.set_yticklabels(middle_labels[0::2])
    #             tick_ax.set_yticklabels(middle_labels[1::2], minor=True)
    #         else:
    #             tick_ax.set_yticklabels(
    #                 middle_labels, rotation=tick_rot, ha="right", va="center"
    #             )


def _process_meta(meta, sort_class):
    if meta is None and sort_class is None:
        return None, None
    elif meta is not None and sort_class is None:
        return meta, []
    elif isinstance(meta, pd.DataFrame):
        # TODO need to check if string first
        if isinstance(sort_class, str):
            sort_class = [sort_class]
        else:
            try:  # if sort class is a single element
                iter(sort_class)
            except TypeError:
                raise TypeError("`sort_class` must be an iterable or string")
    elif isinstance(sort_class, pd.Series) and meta is None:
        meta = sort_class.to_frame(name=0)
        sort_class = [0]
    elif isinstance(sort_class, list) and meta is None:
        meta = pd.DataFrame({i: elem for i, elem in enumerate(sort_class)})
        sort_class = list(range(meta.shape[1]))
    elif isinstance(sort_class, np.ndarray) and meta is None:
        meta = pd.DataFrame(sort_class)
        sort_class = [0]
    else:
        raise ValueError("Improper metadata spec for matrixplot")
    return meta, sort_class


def matrixplot(
    data,
    ax=None,
    plot_type="heatmap",
    row_meta=None,
    col_meta=None,
    row_sort_class=None,
    col_sort_class=None,
    row_class_order=None,
    col_class_order=None,
    row_ticks=True,
    col_ticks=True,
    row_item_order=None,
    col_item_order=None,
    row_colors=None,
    col_colors=None,
    row_palette="tab10",
    col_palette="tab10",
    col_highlight=None,
    row_highlight=None,
    border=True,
    minor_ticking=False,
    tick_rot=0,
    center=0,
    cmap="RdBu_r",
    sizes=(10, 40),
    square=False,
    gridline_kws=None,
    spinestyle_kws=None,
    highlight_kws=None,
    **kws,
):
    """Plotting matrices
    
    Parameters
    ----------
    data : np.ndarray, ndim=2
        matrix to plot
    ax : matplotlib axes object, optional
        [description], by default None
    plot_type : str, optional
        One of "heatmap" or "scattermap", by default "heatmap"
    row_meta : pd.DataFrame, pd.Series, list of pd.Series or np.array, optional
        [description], by default None
    col_meta : [type], optional
        [description], by default None
    row_sort_class : list or np.ndarray, optional
        [description], by default None
    col_sort_class : list or np.ndarray, optional
        [description], by default None
    row_colors : dict, optional
        [description], by default None
    col_colors : dict, optional
        [description], by default None
    row_class_order : str, optional
        [description], by default "size"
    col_class_order : str, optional
        [description], by default "size"
    row_item_order : string or list of string, optional
        attribute in meta by which to sort elements within a class, by default None
    col_item_order : [type], optional
        [description], by default None
    row_ticks : bool, optional
        [description], by default True
    col_ticks : bool, optional
        [description], by default True
    border : bool, optional
        [description], by default True
    minor_ticking : bool, optional
        [description], by default False
    cmap : str, optional
        [description], by default "RdBu_r"
    sizes : tuple, optional
        [description], by default (10, 40)
    square : bool, optional
        [description], by default False
    gridline_kws : [type], optional
        [description], by default None
    spinestyle_kws : [type], optional
        [description], by default None
    tick_rot : int, optional
        [description], by default 0
    
    Returns
    -------
    [type]
        [description]
    """
    row_meta = row_meta.copy()
    col_meta = col_meta.copy()
    # TODO probably remove these
    tick_fontsize = 10
    tick_pad = [0, 0]
    base_tick_pad = 5

    plot_type_opts = ["scattermap", "heatmap"]
    if plot_type not in plot_type_opts:
        raise ValueError(f"`plot_type` must be one of {plot_type_opts}")

    if spinestyle_kws is None:
        spinestyle_kws = dict(linestyle="-", linewidth=1, alpha=0.7, color="black")

    # verify and convert inout
    row_meta, row_sort_class = _process_meta(row_meta, row_sort_class)
    col_meta, col_sort_class = _process_meta(col_meta, col_sort_class)

    if isinstance(col_item_order, str):
        col_item_order = [col_item_order]
    if isinstance(row_item_order, str):
        row_item_order = [row_item_order]

    # sort the data and metadata
    if row_meta is not None:
        row_perm_inds, row_meta = sort_meta(
            row_meta,
            row_sort_class,
            class_order=row_class_order,
            sort_item=row_item_order,
        )
    else:
        row_perm_inds = np.arange(data.shape[0])
    if col_meta is not None:
        col_perm_inds, col_meta = sort_meta(
            col_meta,
            col_sort_class,
            class_order=col_class_order,
            sort_item=col_item_order,
        )
    else:
        col_perm_inds = np.arange(data.shape[1])
    data = data[np.ix_(row_perm_inds, col_perm_inds)]

    # do the actual plotting!
    if ax is None:
        _, ax = plt.subplots(1, 1, figsize=(10, 10))

    if plot_type == "heatmap":
        sns.heatmap(data, cmap=cmap, ax=ax, center=center, **kws)  # TODO stop hard code
    elif plot_type == "scattermap":
        gridmap(data, ax=ax, sizes=sizes, border=False, **kws)

    if square:
        ax.axis("square")

    ax.set_ylim(data.shape[0], 0)
    ax.set_xlim(0, data.shape[1])

    divider = make_axes_locatable(ax)

    # draw colors
    # note that top_cax and left_cax may = ax if no colors are required
    top_cax = draw_colors(
        ax,
        divider=divider,
        ax_type="x",
        colors=col_colors,
        palette=col_palette,
        sort_meta=col_meta,
    )

    left_cax = draw_colors(
        ax,
        divider=divider,
        ax_type="y",
        colors=row_colors,
        palette=row_palette,
        sort_meta=row_meta,
    )

    remove_shared_ax(ax)

    # draw separators
    if len(col_sort_class) > 0:
        draw_separators(
            ax,
            ax_type="x",
            sort_meta=col_meta,
            sort_class=col_sort_class,
            plot_type=plot_type,
            gridline_kws=gridline_kws,
        )
    if len(col_sort_class) > 0:
        draw_separators(
            ax,
            ax_type="y",
            sort_meta=row_meta,
            sort_class=row_sort_class,
            plot_type=plot_type,
            gridline_kws=gridline_kws,
        )

    # draw ticks

    if col_sort_class is not None and col_ticks:
        tick_ax = top_cax  # prime the loop
        tick_ax_border = False
        rev_col_sort_class = list(col_sort_class[::-1])

        for i, sc in enumerate(rev_col_sort_class):
            if i > 0:
                tick_ax = divider.append_axes("top", size="1%", pad=0.5, sharex=ax)
                remove_shared_ax(tick_ax)
                tick_ax.spines["right"].set_visible(True)
                tick_ax.spines["top"].set_visible(True)
                tick_ax.spines["left"].set_visible(True)
                tick_ax.spines["bottom"].set_visible(False)
                tick_ax_border = True

            draw_ticks(
                tick_ax,
                col_meta,
                rev_col_sort_class[i:],
                ax_type="x",
                tick_rot=tick_rot,
                tick_ax_border=tick_ax_border,
            )
            ax.xaxis.set_label_position("top")

    if row_sort_class is not None and row_ticks:
        tick_ax = left_cax  # prime the loop
        tick_ax_border = False
        rev_row_sort_class = list(row_sort_class[::-1])

        for i, sc in enumerate(rev_row_sort_class):
            if i > 0:
                tick_ax = divider.append_axes("left", size="1%", pad=0.5, sharey=ax)
                remove_shared_ax(tick_ax)
                tick_ax.spines["right"].set_visible(False)
                tick_ax.spines["top"].set_visible(True)
                tick_ax.spines["bottom"].set_visible(True)
                tick_ax.spines["left"].set_visible(True)
                tick_ax_border = True

            draw_ticks(
                tick_ax,
                row_meta,
                rev_row_sort_class[i:],
                ax_type="y",
                tick_ax_border=tick_ax_border,
            )

        # if col_sort_class is not None:
        #     tick_ax = top_cax  # prime the loop
        #     tick_ax_border = False
        #     rev_sc = col_sort_class[::-1]
        #     for i, sc in enumerate(col_sort_class[::-1]):
        #         if i > 0:
        #             tick_ax = divider.append_axes("top", size="1%", pad=0.5, sharex=ax)
        #             remove_shared_ax(tick_ax)
        #             tick_ax.spines["right"].set_visible(True)
        #             tick_ax.spines["top"].set_visible(True)
        #             tick_ax.spines["left"].set_visible(True)
        #             tick_ax.spines["bottom"].set_visible(False)
        #             tick_ax_border = True
        #         draw_separators(
        #             ax,
        #             divider=divider,
        #             tick_ax=tick_ax,
        #             ax_type="x",
        #             sort_meta=col_meta,
        #             all_sort_class=rev_sc,
        #             level_sort_class=sc,
        #             plot_type=plot_type,
        #             use_ticks=col_ticks,
        #             tick_rot=tick_rot,
        #             gridline_kws=gridline_kws,
        #             tick_ax_border=tick_ax_border,
        #         )

    # if row_sort_class is not None:
    #     tick_ax = left_cax  # prime the loop
    #     tick_ax_border = False
    #     for i, sc in enumerate(row_sort_class[::-1]):
    #         if i > 0:
    #             tick_ax = divider.append_axes("left", size="1%", pad=0.5, sharey=ax)
    #             remove_shared_ax(tick_ax)
    #             # remove_spines(tick_ax)
    #             tick_ax.spines["right"].set_visible(False)
    #             tick_ax.spines["top"].set_visible(True)
    #             tick_ax.spines["bottom"].set_visible(True)
    #             tick_ax.spines["left"].set_visible(True)
    #             tick_ax_border = True
    #         draw_separators(
    #             ax,
    #             divider=divider,
    #             tick_ax=tick_ax,
    #             ax_type="y",
    #             sort_meta=row_meta,
    #             all_sort_class=row_sort_class,
    #             level_sort_class=sc,
    #             plot_type=plot_type,
    #             use_ticks=row_ticks,
    #             tick_rot=0,
    #             gridline_kws=gridline_kws,
    #             tick_ax_border=tick_ax_border,
    #         )

    # if highlight_kws is None:
    #     highlight_kws = dict(color="black", linestyle="-", linewidth=1)
    # if col_highlight is not None:
    #     draw_separators(
    #         ax,
    #         divider=divider,
    #         # tick_ax=tick_ax,
    #         ax_type="x",
    #         sort_meta=col_meta,
    #         all_sort_class=col_sort_class,
    #         level_sort_class=col_highlight,
    #         plot_type=plot_type,
    #         use_ticks=False,
    #         gridline_kws=highlight_kws,
    #         tick_ax_border=False,
    #     )
    # if row_highlight is not None:
    #     draw_separators(
    #         ax,
    #         divider=divider,
    #         # tick_ax=tick_ax,
    #         ax_type="y",
    #         sort_meta=row_meta,
    #         all_sort_class=row_sort_class,
    #         level_sort_class=row_highlight,
    #         plot_type=plot_type,
    #         use_ticks=False,
    #         gridline_kws=highlight_kws,
    #         tick_ax_border=False,
    #     )

    # spines
    if border:
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color(spinestyle_kws["color"])
            spine.set_linewidth(spinestyle_kws["linewidth"])
            spine.set_linestyle(spinestyle_kws["linestyle"])
            spine.set_alpha(spinestyle_kws["alpha"])

    return ax, divider, top_cax, left_cax


def adjplot(
    data,
    ax=None,
    plot_type="heatmap",
    meta=None,
    sort_class=None,
    class_order=None,
    item_order=None,
    colors=None,
    highlight=None,
    palette="tab10",
    ticks=True,
    border=True,
    minor_ticking=False,
    tick_rot=0,
    center=0,
    cmap="RdBu_r",
    sizes=(10, 40),
    square=True,
    gridline_kws=None,
    spinestyle_kws=None,
    highlight_kws=None,
    **kws,
):
    outs = matrixplot(
        data,
        ax=ax,
        plot_type=plot_type,
        row_meta=meta,
        col_meta=meta,
        row_sort_class=sort_class,
        col_sort_class=sort_class,
        row_class_order=class_order,
        col_class_order=class_order,
        row_item_order=item_order,
        col_item_order=item_order,
        row_colors=colors,
        col_colors=colors,
        row_palette=palette,
        col_palette=palette,
        row_highlight=highlight,
        col_highlight=highlight,
        row_ticks=ticks,
        col_ticks=ticks,
        border=border,
        tick_rot=tick_rot,
        center=center,
        cmap=cmap,
        sizes=sizes,
        square=square,
        gridline_kws=gridline_kws,
        spinestyle_kws=spinestyle_kws,
        highlight_kws=highlight_kws,
        **kws,
    )
    return outs

