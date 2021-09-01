def ensure_path(path):
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def read_fq(fname):
    import gzip
    from more_itertools import grouper

    if fname.endswith(".gz"):
        src = gzip.open(fname, mode="rt")
    elif type(fname) is str:
        src = open(fname)
    else:
        src = fname  # assume its a stream or file-like object already

    for name, seq, _, qual in grouper(src, 4):
        yield name.rstrip()[1:], seq.rstrip(), qual.rstrip()

def dge_to_sparse(dge_path):
    import anndata
    import numpy as np
    import gzip
    import pandas as pd
    from scipy.sparse import csr_matrix, vstack

    ix = 0
    mix = 0
    matrices = []
    gene_names = []

    with gzip.open(dge_path, 'rt') as dge:
        first_line = dge.readline().strip().split('\t')

        barcodes = first_line[1:]
        ncol = len(barcodes)
        M = np.zeros((1000, ncol))

        for line in dge:
            vals = line.strip().split('\t')
            # first element contains the gene name
            gene_names.append(vals[0])
            vals = vals[1:]
            vals = np.array(vals, dtype=np.int64)

            M[ix] = vals

            if ix % 1000 == 999:
                print(mix)
                mix = mix + 1
                matrices.append(csr_matrix(M))
                ix = 0
                M = np.zeros((1000, ncol))
            else:
                ix = ix + 1

        # get the leftovers
        M = M[:ix]
        matrices.append(csr_matrix(M))

        # sparse expression matrix
        X = vstack(matrices, format='csr')
        print(len(gene_names))
        
        adata = anndata.AnnData(X.T, obs = pd.DataFrame(index=barcodes), var = pd.DataFrame(index=gene_names))

        return adata

def compute_neighbors(adata, min_dist=None, max_dist=None):
    '''Compute all direct neighbors of all spots in the adata. Currently
        tailored for 10X Visium.
    Args:
        adata: an AnnData object
        min_dist: int, minimum distance to consider neighbors
        max_dist: int, maximum distance to consider neighbors
    Returns:
        neighbors: a dictionary holding the spot IDs for every spot
    '''
    import numpy as np
    from scipy.spatial.distance import cdist

    # Calculate all Euclidean distances on the adata
    dist_mtrx = cdist(adata.obsm['spatial'],
                      adata.obsm['spatial'])
    neighbors = dict()

    for i in range(adata.obs.shape[0]):
        neighbors[i] = np.where((dist_mtrx[i,:] > min_dist) & (dist_mtrx[i,:] < max_dist))[0]

    return neighbors

def compute_islands(adata, min_umi):
    '''Find contiguity islands

    Args:
        adata: an AnnData object
        cluster: a cell type label to compute the islands for
    Returns:
        islands: A list of lists of spots forming contiguity islands
    '''
    import numpy as np
    import itertools

    # this is hard coded for now for visium, to have 6 neighbors per spot
    # TODO: define an iterative approach where the key is to have around 6 
    # neighbors per spot on average
    neighbors = compute_neighbors(adata, min_dist = 0, max_dist=3)
    spots_cluster = np.where(np.array(adata.obs['total_counts']) < min_umi)[0]

    # create a new dict holding only neighbors of the cluster
    islands = []

    for spot in neighbors:
        if spot not in spots_cluster:
            continue
        islands.append({spot}.union({x for x in neighbors[spot] if x in spots_cluster}))

    # merge islands with common spots
    island_spots = set(itertools.chain.from_iterable(islands)) 

    for each in island_spots:
        components = [x for x in islands if each in x]
        for i in components:
            islands.remove(i)
        islands += [list(set(itertools.chain.from_iterable(components)))]

    return islands

def detect_tissue(adata, min_umi):
    ''' Detect tissue: first find beads with at least min_umi UMIs, then detect island in the rest
    
    Args
        adata: an AnnData object, with spatial coordinates
        min_umi: integer, the min umi to be assigned as tissue bead by default
    Returns:
        tissue_indices: a list of indices which should be kept for this AnnData object
    '''
    import numpy as np

    islands = compute_islands(adata, min_umi)

    # find the sizes of the islands. remove the biggest, as either the tissue has a big hole in it
    # or there are not so many big islands in which case removal is OK.
    # to be evaluated later...
    island_sizes = [len(island) for island in islands]

    tissue_islands = np.delete(islands, np.argmax(island_sizes))

    # get the indices of the islands
    tissue_indices = np.where(np.array(adata.obs['total_counts']) >= min_umi)[0]

    tissue_indices = np.append(tissue_indices, np.hstack(tissue_islands))

    return tissue_indices
