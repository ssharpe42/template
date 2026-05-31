"""Exact, no-duplicate distributed evaluation.

Why a custom loop? HF's iterable eval path pads each rank to equal length and
relies on de-duplication bookkeeping; with uneven shards this is awkward and can
double-count. We avoid it entirely:

* Eval files are assigned **disjointly** across ranks, so every eval row is
  scored exactly once -- no padding-induced duplicates, no drops.
* Evaluation runs under ``no_grad``, so DDP performs **no** per-step
  all-reduce. Ranks may therefore process different numbers of samples safely;
  we only synchronise once, at the end.
* The final gather pads each rank's tensor to the max length, all-gathers, then
  trims back to the true per-rank length -- exact reconstruction.

This module imports torch lazily so the package imports without it.
"""

from __future__ import annotations

from typing import Callable, Iterator, Tuple


def _gather_concat(t, device):
    """All-gather variable-length tensors along dim 0 and concatenate exactly."""

    import torch
    import torch.distributed as dist

    if not (dist.is_available() and dist.is_initialized()) or dist.get_world_size() == 1:
        return t.detach().cpu()

    t = t.to(device)
    world = dist.get_world_size()

    local_n = torch.tensor([t.shape[0]], device=device, dtype=torch.long)
    sizes = [torch.zeros_like(local_n) for _ in range(world)]
    dist.all_gather(sizes, local_n)
    sizes = [int(s.item()) for s in sizes]
    max_n = max(sizes)

    if t.shape[0] < max_n:
        pad = torch.zeros((max_n - t.shape[0], *t.shape[1:]), dtype=t.dtype, device=device)
        t = torch.cat([t, pad], dim=0)

    gathered = [torch.zeros_like(t) for _ in range(world)]
    dist.all_gather(gathered, t)
    # Trim each rank's padding back to its true length -> no duplicates.
    pieces = [g[:n] for g, n in zip(gathered, sizes)]
    return torch.cat(pieces, dim=0).cpu()


def run_distributed_eval(
    model,
    eval_iter: Iterator,
    forward_fn: Callable,
    device,
) -> Tuple["object", "object"]:
    """Run eval over this rank's disjoint files and gather all predictions.

    Parameters
    ----------
    model:
        The (possibly DDP-wrapped) model. Set to ``eval()`` here.
    eval_iter:
        Iterator over this rank's eval batches (see ``stream.build_eval_iter``).
    forward_fn:
        ``(model, batch) -> (preds, labels)`` returning 1-D-or-batched tensors.
    device:
        Device to run on / gather through.

    Returns ``(all_preds, all_labels)`` -- identical on every rank, covering the
    whole eval set exactly once. Compute your metric on these.
    """

    import torch

    model.eval()
    preds, labels = [], []
    with torch.no_grad():
        for batch in eval_iter:
            p, y = forward_fn(model, batch)
            preds.append(p.detach().cpu())
            labels.append(y.detach().cpu())

    local_pred = torch.cat(preds, dim=0) if preds else torch.empty(0)
    local_label = torch.cat(labels, dim=0) if labels else torch.empty(0)

    all_pred = _gather_concat(local_pred, device)
    all_label = _gather_concat(local_label, device)
    return all_pred, all_label
