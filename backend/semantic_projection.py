"""Deterministic centered PCA via the small sample Gram matrix (at most 10x10)."""

import math


def pca_2d(vectors):
    if not vectors:
        return {'coordinates': [], 'explained_variance_ratio': [0.0, 0.0], 'rank': 0}
    n, dimensions = len(vectors), len(vectors[0])
    if n > 10 or not dimensions or any(len(row) != dimensions for row in vectors):
        raise ValueError('Invalid projection dimensions')
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
           for row in vectors for v in row):
        raise ValueError('Invalid projection values')
    means = [math.fsum(row[j] for row in vectors) / n for j in range(dimensions)]
    centered = [[value - mean for value, mean in zip(row, means)] for row in vectors]
    gram = [[math.fsum(a * b for a, b in zip(first, second)) for second in centered] for first in centered]
    basis = [[float(i == j) for j in range(n)] for i in range(n)]
    total = sum(gram[i][i] for i in range(n))
    # Jacobi symmetric eigensolver: no random initialization, no ML dependency.
    for _ in range(100 * n * n):
        if n < 2:
            break
        p, q = max(((i, j) for i in range(n) for j in range(i + 1, n)), key=lambda pair: abs(gram[pair[0]][pair[1]]))
        if abs(gram[p][q]) <= max(total * 1e-13, 1e-15):
            break
        angle = .5 * math.atan2(2 * gram[p][q], gram[q][q] - gram[p][p])
        c, s = math.cos(angle), math.sin(angle)
        app, aqq, apq = gram[p][p], gram[q][q], gram[p][q]
        for k in range(n):
            if k not in (p, q):
                a, b = gram[k][p], gram[k][q]
                gram[k][p] = gram[p][k] = c * a - s * b
                gram[k][q] = gram[q][k] = s * a + c * b
            a, b = basis[k][p], basis[k][q]
            basis[k][p], basis[k][q] = c * a - s * b, s * a + c * b
        gram[p][p] = c*c*app - 2*s*c*apq + s*s*aqq
        gram[q][q] = s*s*app + 2*s*c*apq + c*c*aqq
        gram[p][q] = gram[q][p] = 0.0
    eigenvalues = [max(0.0, gram[i][i]) for i in range(n)]
    order = sorted(range(n), key=lambda i: (-eigenvalues[i], i))
    axes, ratios = [], []
    tolerance = max(total * 1e-12, 1e-15)
    for axis in order[:2]:
        values = [basis[i][axis] * math.sqrt(eigenvalues[axis]) for i in range(n)]
        if eigenvalues[axis] <= tolerance:
            values = [0.0] * n
        elif values[max(range(n), key=lambda i: abs(values[i]))] < 0:
            values = [-value for value in values]
        axes.append(values)
        ratios.append(eigenvalues[axis] / total if total > tolerance else 0.0)
    while len(axes) < 2:
        axes.append([0.0] * n)
        ratios.append(0.0)
    return {'coordinates': [[axes[0][i], axes[1][i]] for i in range(n)],
            'explained_variance_ratio': ratios,
            'rank': sum(value > tolerance for value in eigenvalues)}
