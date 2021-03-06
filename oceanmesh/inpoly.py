import numpy as np
from numba import jit


def inpoly(vert, node, edge=None, ftol=5.0e-14):
    """
      INPOLY2: compute "points-in-polygon" queries.

      STAT = INPOLY2(VERT, NODE, EDGE) returns the "inside/ou-
      tside" status for a set of vertices VERT and a polygon
      NODE, EDGE embedded in a two-dimensional plane. General
      non-convex and multiply-connected polygonal regions can
      be handled. VERT is an N-by-2 array of XY coordinates to
      be tested. STAT is an associated N-by-1 boolean array,
      with STAT[II] = TRUE if VERT[II, :] is an inside point.

      The polygonal region is defined as a piecewise-straight-
      line-graph, where NODE is an M-by-2 array of polygon ve-
      rtices and EDGE is a P-by-2 array of edge indexing. Each
      row in EDGE represents an edge of the polygon, such that
      NODE[EDGE[KK, 0], :] and NODE[EDGE[KK, 2], :] are the
      coordinates of the endpoints of the KK-TH edge. If the
      argument EDGE is omitted it assumed that the vertices in
      NODE are connected in ascending order.

      STAT, BNDS = INPOLY2(..., FTOL) also returns an N-by-1
      boolean array BNDS, with BNDS[II] = TRUE if VERT[II, :]
      lies "on" a boundary segment, where FTOL is a floating-
      point tolerance for boundary comparisons. By default,
      FTOL ~ EPS ^ 0.85.

      --------------------------------------------------------

      This algorithm is based on a "crossing-number" test,
      counting the number of times a line extending from each
      point past the right-most end of the polygon intersects
      with the polygonal boundary. Points with odd counts are
      "inside". A simple implementation requires that each
      edge intersection be checked for each point, leading to
      O(N*M) complexity...

      This implementation seeks to improve these bounds:

    * Sorting the query points by y-value and determining can-
      didate edge intersection sets via binary-search. Given a
      configuration with N test points, M edges and an average
      point-edge "overlap" of H, the overall complexity scales
      like O(M*H + M*LOG(N) + N*LOG(N)), where O(N*LOG(N))
      operations are required for sorting, O(M*LOG(N)) operat-
      ions required for the set of binary-searches, and O(M*H)
      operations required for the intersection tests, where H
      is typically small on average, such that H << N.

    * Carefully checking points against the bounding-box asso-
      ciated with each polygon edge. This minimises the number
      of calls to the (relatively) expensive edge intersection
      test.

      Updated: 23 September, 2020

      Authors: Darren Engwirda, Keith Roberts

    """

    vert = np.asarray(vert)
    node = np.asarray(node)

    if edge is None:
        # ----------------------------------- set edges if not passed
        indx = np.arange(0, node.shape[0] - 1)

        edge = np.zeros((node.shape[0], 2), dtype=np.int32)
        edge[:-1, 0] = indx + 0
        edge[:-1, 1] = indx + 1
        edge[-1, 0] = node.shape[0] - 1

    else:
        edge = np.asarray(edge)

    STAT = np.full(vert.shape[0], False, dtype=np.bool_)
    BNDS = np.full(vert.shape[0], False, dtype=np.bool_)

    # ----------------------------------- prune points using bbox
    mask = np.logical_and.reduce(
        (
            vert[:, 0] >= np.nanmin(node[:, 0]),
            vert[:, 1] >= np.nanmin(node[:, 1]),
            vert[:, 0] <= np.nanmax(node[:, 0]),
            vert[:, 1] <= np.nanmax(node[:, 1]),
        )
    )

    vert = vert[mask, :]

    # ------------------ flip to ensure y-axis is the `long` axis
    vmin = np.amin(vert, axis=0)
    vmax = np.amax(vert, axis=0)
    ddxy = vmax - vmin

    lbar = np.sum(ddxy) / 2.0

    if ddxy[0] > ddxy[1]:
        vert = vert[:, (1, 0)]
        node = node[:, (1, 0)]

    # ----------------------------------- sort points via y-value
    swap = node[edge[:, 1], 1] < node[edge[:, 0], 1]
    temp = edge[swap]
    edge[swap, :] = temp[:, (1, 0)]

    ivec = np.argsort(vert[:, 1])
    vert = vert[ivec]

    # ----------------------------------- call crossing-no kernel
    stmp, btmp = _inpoly(vert, node, edge, ftol, lbar)

    # ----------------------------------- unpack array reindexing
    stat = np.full(vert.shape[0], False, dtype=np.bool_)
    bnds = np.full(vert.shape[0], False, dtype=np.bool_)

    stat[ivec] = stmp
    bnds[ivec] = btmp

    STAT[mask] = stat
    BNDS[mask] = bnds

    return STAT, BNDS


@jit(nopython=True)
def _inpoly(vert, node, edge, ftol, lbar):
    """
    _INPOLY: the local pycode version of the crossing-number
    test. Loop over edges; do a binary-search for the first
    vertex that intersects with the edge y-range; crossing-
    number comparisons; break when the local y-range is met.

    """

    feps = ftol * (lbar ** +2)
    veps = ftol * (lbar ** +1)

    stat = np.full(vert.shape[0], False, dtype=np.bool_)
    bnds = np.full(vert.shape[0], False, dtype=np.bool_)

    # ----------------------------------- compute y-range overlap
    XONE = node[edge[:, 0], 0]
    XTWO = node[edge[:, 1], 0]
    YONE = node[edge[:, 0], 1]
    YTWO = node[edge[:, 1], 1]

    XMIN = np.minimum(XONE, XTWO)
    XMAX = np.maximum(XONE, XTWO)

    XMAX = XMAX + veps
    YMIN = YONE - veps
    YMAX = YTWO + veps

    YDEL = YTWO - YONE
    XDEL = XTWO - XONE

    ione = np.searchsorted(vert[:, 1], YMIN, "left")
    itwo = np.searchsorted(vert[:, 1], YMAX, "right")

    # ----------------------------------- loop over polygon edges
    for epos in range(edge.shape[0]):

        xone = XONE[epos]
        xtwo = XTWO[epos]
        yone = YONE[epos]
        ytwo = YTWO[epos]

        xmin = XMIN[epos]
        xmax = XMAX[epos]

        xdel = XDEL[epos]
        ydel = YDEL[epos]

        # ------------------------------- calc. edge-intersection
        for jpos in range(ione[epos], itwo[epos]):

            if bnds[jpos]:
                continue

            xpos = vert[jpos, 0]
            ypos = vert[jpos, 1]

            if xpos >= xmin:
                if xpos <= xmax:
                    # ------------------- compute crossing number
                    mul1 = ydel * (xpos - xone)
                    mul2 = xdel * (ypos - yone)

                    if feps >= np.abs(mul2 - mul1):
                        # ------------------- BNDS -- approx. on edge
                        bnds[jpos] = True
                        stat[jpos] = True

                    elif (ypos == yone) and (xpos == xone):
                        # ------------------- BNDS -- match about ONE
                        bnds[jpos] = True
                        stat[jpos] = True

                    elif (ypos == ytwo) and (xpos == xtwo):
                        # ------------------- BNDS -- match about TWO
                        bnds[jpos] = True
                        stat[jpos] = True

                    elif (mul1 < mul2) and (ypos >= yone) and (ypos < ytwo):
                        # ------------------- advance crossing number
                        stat[jpos] = not stat[jpos]

            elif (ypos >= yone) and (ypos < ytwo):
                # ----------------------- advance crossing number
                stat[jpos] = not stat[jpos]

    return stat, bnds


# def inpoly(vert, node, edge=None, ftol=4.9485e-16):
#    """A port of Darren Engwirda's `inpoly` routine into Python.
#
#       Returns the "inside/outside" status for a set of vertices VERT and
#       a polygon {NODE,EDGE}  embedded in a two-dimensional plane. General
#       non-convex and multiply-connected polygonal regions can be handled.
#
#
#    Parameters
#    ----------
#    vert: array-like
#        VERT is an N-by-2 array of XY coordinates to query.
#
#    node: array-like
#        NODE is an M-by-2 array of polygon vertices.
#
#    edge: array-like, optional
#        EDGE is a P-by-2 array of edge indexing. Each
#        row in EDGE represents an edge of the polygon, such that
#        node(edge(KK,1),:) and node(edge(KK,2),:) are the coord-
#        inates of the endpoints of the KK-TH edge. If the argum-
#        ent EDGE is omitted it assumed that the vertices in NODE
#        are connected in ascending order.
#
#    ftol: float, otpional
#        FTOL is a floating-point tolerance for boundary comparisons.
#        By default, FTOL = EPS ^ 0.85.
#
#
#    Returns:
#    --------
#    STAT: array-like
#        STAT is an associated N-by-1 logical array,
#        with STAT(II) = TRUE if VERT(II,:) is an interior point.
#
#    BNDS: array-like
#        N-by-1 logical array BNDS, with BNDS(II) = TRUE if VERT(II,:)
#        lies "on" a boundary segment,
#
#
#    Notes
#    -----
#
#    ALL CREDIT GOES TO THE ORIGINAL AUTHOR: Darren Engwirda
#
#    Darren Engwirda : 2017 --
#    Email           : de2363@columbia.edu
#    Last updated    : 31/03/2020
#
#
#    Author of port:
#
#    Keith J. Roberts (2020)
#    Email: krober@usp.br
#    Date: 2020-13-09
#
#    """
#
#    nnod = len(node)
#    nvrt = len(vert)
#
#    # create edge if not supplied
#    if edge is None:
#        edge = np.vstack((np.arange(0, nnod - 1), np.arange(1, nnod))).T
#        edge = np.concatenate((edge, [[nnod - 1, 0]]))
#
#    STAT = np.zeros((nvrt), dtype=int)
#    BNDS = np.zeros((nvrt), dtype=int)
#
#    # prune points using bbox
#    mask = (
#        (vert[:, 0] >= np.nanmin(node[:, 0]))
#        & (vert[:, 0] <= np.nanmax(node[:, 0]))
#        & (vert[:, 1] >= np.nanmin(node[:, 1]))
#        & (vert[:, 1] <= np.nanmax(node[:, 1]))
#    )
#
#    vert = vert[mask]
#
#    # flip to ensure y-axis is the `long` axis
#    vmin = np.amin(vert, axis=0)
#    vmax = np.amax(vert, axis=0)
#    ddxy = vmax - vmin
#
#    lbar = np.sum(ddxy) / 2.0
#
#    if ddxy[0] > ddxy[1]:
#        vert = vert[:, [1, 0]]
#        node = node[:, [1, 0]]
#
#    # sort points via y-value
#    swap = node[edge[:, 1], 1] < node[edge[:, 0], 1]
#
#    tmp = edge[swap]
#    edge[swap, :] = tmp[:, [1, 0]]
#
#    ivec = np.argsort(vert[:, 1])
#    vert = vert[ivec]
#
#    t_stat, t_bnds = _inpoly(vert, node, edge, ftol, lbar)
#
#    stat = np.ones(len(vert))
#    bnds = np.ones(len(vert))
#    stat[ivec] = t_stat
#    bnds[ivec] = t_bnds
#
#    STAT[mask] = stat
#    BNDS[mask] = bnds
#
#    return STAT, BNDS
#
#
# @jit(nopython=True)
# def _inpoly(vert, node, edge, ftol, lbar):
#
#    feps = ftol * lbar ** 2
#    veps = ftol * lbar ** 1
#
#    _nvrt = len(vert)
#    _nedge = len(edge)
#
#    _stat = np.zeros((_nvrt))
#    _bnds = np.zeros((_nvrt))
#
#    # loop over polygon edges
#    for epos in range(_nedge):
#
#        inod = edge[epos, 0]
#        jnod = edge[epos, 1]
#
#        # calc. edge bounding-box
#        yone = node[inod, 1]
#        ytwo = node[jnod, 1]
#        xone = node[inod, 0]
#        xtwo = node[jnod, 0]
#
#        xmin = np.minimum(xone, xtwo)
#        xmax = np.maximum(xone, xtwo)
#
#        xmax += veps
#
#        ymin = yone - veps
#        ymax = ytwo + veps
#
#        ydel = ytwo - yone
#        xdel = xtwo - xone
#
#        # find top VERT[:,1]<YONE
#        ilow = 0  # for python
#        iupp = _nvrt
#
#        while ilow < iupp - 1:  # binary search
#            imid = int(ilow + np.floor((iupp - ilow) / 2))
#            if vert[imid, 1] < ymin:
#                ilow = imid
#            else:
#                iupp = imid
#
#        if vert[ilow, 1] >= ymin:
#            ilow -= 1
#
#        # calc. edge-intersection
#        for jpos in range(ilow + 1, _nvrt):
#
#            if _bnds[jpos]:
#                continue
#
#            xpos = vert[jpos, 0]
#            ypos = vert[jpos, 1]
#
#            if ypos <= ymax:
#                if xpos >= xmin:
#                    if xpos <= xmax:
#                        # compute crossing number
#                        mul1 = ydel * (xpos - xone)
#                        mul2 = xdel * (ypos - yone)
#                        if feps >= np.abs(mul2 - mul1):
#                            # BNDS -- approx. on edge
#                            _bnds[jpos] = 1
#                            _stat[jpos] = 1
#                        elif (ypos == yone) & (xpos == xone):
#                            # BNDS -- match about ONE
#                            _bnds[jpos] = 1
#                            _stat[jpos] = 1
#                        elif (ypos == ytwo) & (xpos == xtwo):
#                            # BNDS -- match about TWO
#                            _bnds[jpos] = 1
#                            _stat[jpos] = 1
#                        elif mul1 < mul2:
#                            if (ypos >= yone) & (ypos < ytwo):
#                                # advance crossing number
#                                _stat[jpos] = 1 - _stat[jpos]
#
#                else:
#                    if (ypos >= yone) & (ypos < ytwo):
#                        # advance crossing number
#                        _stat[jpos] = 1 - _stat[jpos]
#            else:
#                # done -- due to the sort
#                break
#    return _stat, _bnds
