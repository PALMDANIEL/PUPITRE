"""
Apprentissage du reconnaisseur d'altérations (signes.py) sur les exemples de make_signes.py : petit réseau (une couche
cachée), en numpy seul (rien de plus à livrer avec le moteur). Contrôle sur des chorals jamais vus à l'apprentissage.

Usage : python train_signes.py <exemples.npz> <sortie: engine/modeles/signes.npz>
"""
import sys

import numpy as np


def forward(W, X):
    h = np.maximum(0, X @ W["W1"] + W["b1"])
    z = h @ W["W2"] + W["b2"]
    z -= z.max(1, keepdims=True)
    p = np.exp(z)
    return h, p / p.sum(1, keepdims=True)


def main(src, out):
    d = np.load(src)
    X = d["X"].reshape(len(d["X"]), -1).astype(np.float32)
    Y = d["Y"].astype(np.int64)
    G = d["G"]
    groups = np.unique(G)
    rng = np.random.default_rng(1)
    test_groups = set(rng.choice(groups, max(1, len(groups) // 5), replace=False).tolist())
    te = np.array([g in test_groups for g in G])
    Xtr, Ytr, Xte, Yte = X[~te], Y[~te], X[te], Y[te]
    mu, sd = Xtr.mean(0), Xtr.std(0) + 0.05
    Xtr, Xte = (Xtr - mu) / sd, (Xte - mu) / sd
    n_in, n_h, n_out = X.shape[1], 96, 4
    W = {"W1": rng.normal(0, np.sqrt(2 / n_in), (n_in, n_h)).astype(np.float32), "b1": np.zeros(n_h, np.float32),
         "W2": rng.normal(0, np.sqrt(2 / n_h), (n_h, n_out)).astype(np.float32), "b2": np.zeros(n_out, np.float32)}
    counts = np.bincount(Ytr, minlength=n_out)
    cw = (len(Ytr) / (n_out * np.maximum(counts, 1))) ** 0.5  # classes rares un peu renforcées
    m = {k: np.zeros_like(v) for k, v in W.items()}
    v = {k: np.zeros_like(v) for k, v in W.items()}
    lr, b1, b2, step = 2e-3, 0.9, 0.999, 0
    for epoch in range(30):
        order = rng.permutation(len(Xtr))
        for i in range(0, len(order), 256):
            idx = order[i:i + 256]
            x, y = Xtr[idx], Ytr[idx]
            h, p = forward(W, x)
            g = p.copy()
            g[np.arange(len(y)), y] -= 1
            g *= cw[y][:, None] / len(y)
            grads = {"W2": h.T @ g, "b2": g.sum(0)}
            dh = (g @ W["W2"].T) * (h > 0)
            grads.update({"W1": x.T @ dh + 1e-4 * W["W1"], "b1": dh.sum(0)})
            step += 1
            for k in W:
                m[k] = b1 * m[k] + (1 - b1) * grads[k]
                v[k] = b2 * v[k] + (1 - b2) * grads[k] ** 2
                W[k] -= lr * (m[k] / (1 - b1 ** step)) / (np.sqrt(v[k] / (1 - b2 ** step)) + 1e-8)
        if epoch % 5 == 4 or epoch == 29:
            _h, pt = forward(W, Xte)
            pred = pt.argmax(1)
            acc = (pred == Yte).mean()
            conf = np.zeros((n_out, n_out), int)
            for a, b in zip(Yte, pred):
                conf[a, b] += 1
            print(f"époque {epoch + 1} : justesse contrôle {acc:.4f}\n{conf}", flush=True)
    # seuils : part des faux signes (rien → signe) et des signes trouvés selon la confiance exigée
    _h, pt = forward(W, Xte)
    for tau in (0.5, 0.7, 0.8, 0.9, 0.95):
        best = pt.argmax(1)
        sure = pt.max(1) >= tau
        said = sure & (best > 0)
        false = (said & (Yte == 0)).sum() / max(1, (Yte == 0).sum())
        found = (said & (best == Yte) & (Yte > 0)).sum() / max(1, (Yte > 0).sum())
        wrong = (said & (best != Yte) & (Yte > 0)).sum()
        print(f"seuil {tau} : signes trouvés {found:.3f}, faux signes {false:.4f}, signe confondu {wrong}")
    np.savez_compressed(out, mu=mu, sd=sd, **W, shape=np.array([26, 16]))
    print("écrit", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
