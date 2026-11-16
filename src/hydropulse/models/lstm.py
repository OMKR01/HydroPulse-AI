"""PyTorch LSTM-based multi-horizon flood discharge forecasting.

Two architectures:
    PerStationLSTM    — trained independently per station; seq2seq direct output.
    MultiStationLSTM  — trained on all stations simultaneously with learnable
                        station embeddings (dim=8) concatenated to met. features.

Interface matches baselines.py: .fit(train_df) / .predict(df) -> np.ndarray (n, 7).

Design decisions:
    - seq_len=30 days sliding window.
    - 2-layer LSTM, hidden=128, dropout=0.2.
    - Adam optimiser, lr=1e-3, cosine LR scheduler.
    - Early stopping: patience=15 epochs on validation loss.
    - CPU default (device="cuda" if available).
    - All seeds fixed via RANDOM_SEED=42.
    - Gradient-based feature attribution as SHAP proxy (cheap, no external dep).

AGENTS.md: GloFAS residual correction identical to lgbm.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
    TORCH_AVAILABLE = True
except (ImportError, OSError):
    torch = None  # type: ignore
    nn = None  # type: ignore
    DataLoader = None  # type: ignore
    Dataset = object  # type: ignore
    TORCH_AVAILABLE = False

logger = logging.getLogger(__name__)

FORECAST_HORIZONS = 7
SEQ_LEN = 30
HIDDEN_SIZE = 128
NUM_LAYERS = 2
DROPOUT = 0.2
EMBED_DIM = 8
BATCH_SIZE = 64
MAX_EPOCHS = 100
PATIENCE = 15
LEARNING_RATE = 1e-3
RANDOM_SEED = 42

FEATURE_EXCLUDE = {
    "date", "station_id", "provenance", "is_interpolated",
    "is_outlier_precip", "is_outlier_discharge", "outlier_reason",
    "discharge_m3s",
    *[f"target_discharge_h{h}" for h in range(1, FORECAST_HORIZONS + 1)],
}


# ──────────────────────────── helpers ──────────────────────────────────────


def _set_seed(seed: int = RANDOM_SEED) -> None:
    torch.manual_seed(seed)
    np.random.seed(seed)


def _get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _select_features(df: pd.DataFrame) -> list[str]:
    return [
        c for c in df.columns
        if c not in FEATURE_EXCLUDE and pd.api.types.is_numeric_dtype(df[c])
    ]


def _normalise_df(
    df: pd.DataFrame,
    feature_cols: list[str],
    stats: dict[str, tuple[float, float]] | None = None,
) -> tuple[pd.DataFrame, dict[str, tuple[float, float]]]:
    """Robust normalise feature columns. Computes stats from df if not provided (train split)."""
    df_n = df.copy()
    if stats is None:
        stats = {}
        for col in feature_cols:
            med = float(df_n[col].median()) if col in df_n else 0.0
            iqr = float(df_n[col].quantile(0.75) - df_n[col].quantile(0.25)) if col in df_n else 1.0
            iqr = iqr if iqr > 1e-6 else float(df_n[col].std() or 1.0)
            stats[col] = (med, iqr)

    for col in feature_cols:
        if col in df_n.columns:
            m, s = stats[col]
            df_n[col] = (df_n[col] - m) / max(s, 1e-9)

    return df_n, stats


# ──────────────────────────── dataset ──────────────────────────────────────


class DischargeSequenceDataset(Dataset):
    """Sliding-window sequence dataset for LSTM training.

    Each sample: (X_seq [seq_len, n_features], y [7])
    """

    def __init__(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
        seq_len: int = SEQ_LEN,
        station_id_map: dict[str, int] | None = None,
    ) -> None:
        self.seq_len = seq_len
        self.feature_cols = feature_cols
        self.station_id_map = station_id_map  # for multi-station embedding

        target_cols = [f"target_discharge_h{h}" for h in range(1, FORECAST_HORIZONS + 1)]
        available_targets = [c for c in target_cols if c in df.columns]

        df_clean = df[feature_cols + available_targets + (["station_id"] if station_id_map else [])].copy()
        df_clean[feature_cols] = df_clean[feature_cols].astype(float).fillna(0.0)
        df_clean[available_targets] = df_clean[available_targets].astype(float)

        self.X_arr = df_clean[feature_cols].to_numpy(dtype=np.float32)
        self.y_arr = df_clean[available_targets].to_numpy(dtype=np.float32) if available_targets else None

        if station_id_map and "station_id" in df.columns:
            self.station_ids = np.array([
                station_id_map.get(str(s), 0) for s in df["station_id"]
            ], dtype=np.int64)
        else:
            self.station_ids = None

    def __len__(self) -> int:
        return max(0, len(self.X_arr) - self.seq_len)

    def __getitem__(self, idx: int) -> tuple[Any, ...]:
        x = torch.from_numpy(self.X_arr[idx: idx + self.seq_len])           # (seq_len, n_features)
        target_idx = idx + self.seq_len - 1

        if self.y_arr is not None and target_idx < len(self.y_arr):
            y = torch.from_numpy(self.y_arr[target_idx])                     # (7,)
        else:
            y = torch.full((FORECAST_HORIZONS,), float("nan"))

        if self.station_ids is not None:
            sid = torch.tensor(self.station_ids[target_idx], dtype=torch.long)
            return x, y, sid
        return x, y


# ──────────────────────────── network architectures ────────────────────────


class _LSTMNet(nn.Module):
    """Per-station LSTM: input features -> hidden -> 7-horizon output."""

    def __init__(self, input_size: int, hidden_size: int = HIDDEN_SIZE,
                 num_layers: int = NUM_LAYERS, dropout: float = DROPOUT) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, FORECAST_HORIZONS)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, seq_len, input_size) -> (batch, 7)."""
        out, _ = self.lstm(x)              # (batch, seq_len, hidden)
        last = out[:, -1, :]               # take last time step
        return self.fc(self.dropout(last))


class _MultiStationLSTMNet(nn.Module):
    """Multi-station LSTM with learnable station embeddings (dim=8)."""

    def __init__(self, input_size: int, n_stations: int,
                 embed_dim: int = EMBED_DIM,
                 hidden_size: int = HIDDEN_SIZE,
                 num_layers: int = NUM_LAYERS,
                 dropout: float = DROPOUT) -> None:
        super().__init__()
        self.embedding = nn.Embedding(n_stations + 1, embed_dim, padding_idx=0)
        # Embed repeated across sequence before concat
        self.lstm = nn.LSTM(
            input_size=input_size + embed_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, FORECAST_HORIZONS)

    def forward(self, x: torch.Tensor, station_id: torch.Tensor) -> torch.Tensor:
        """x: (batch, seq, features), station_id: (batch,) -> (batch, 7)."""
        emb = self.embedding(station_id)               # (batch, embed_dim)
        emb_expanded = emb.unsqueeze(1).expand(-1, x.size(1), -1)  # (batch, seq, embed_dim)
        x_cat = torch.cat([x, emb_expanded], dim=2)   # (batch, seq, features+embed_dim)
        out, _ = self.lstm(x_cat)
        last = out[:, -1, :]
        return self.fc(self.dropout(last))


# ──────────────────────────── training loop ────────────────────────────────


def _train_loop(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader | None,
    device: torch.device,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    lr: float = LEARNING_RATE,
    multi_station: bool = False,
) -> dict[str, list[float]]:
    """Generic training loop with early stopping."""
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=max_epochs)
    criterion = nn.MSELoss()

    history: dict[str, list[float]] = {"train_loss": [], "val_loss": []}
    best_val_loss = float("inf")
    patience_counter = 0
    best_state: dict[str, Any] | None = None

    for epoch in range(max_epochs):
        model.train()
        epoch_loss = 0.0
        n_batches = 0

        for batch in train_loader:
            if multi_station:
                x_seq, y_true, sid = [b.to(device) for b in batch]
                y_pred = model(x_seq, sid)
            else:
                x_seq, y_true = batch[0].to(device), batch[1].to(device)
                y_pred = model(x_seq)

            # Mask NaN targets (short series may not have all 7 horizons filled)
            valid_mask = ~torch.isnan(y_true)
            if valid_mask.sum() == 0:
                continue

            loss = criterion(y_pred[valid_mask], y_true[valid_mask])
            optimiser.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimiser.step()
            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_train = epoch_loss / max(n_batches, 1)
        history["train_loss"].append(avg_train)

        # Validation
        if val_loader is not None:
            model.eval()
            val_loss = 0.0
            n_val = 0
            with torch.no_grad():
                for vbatch in val_loader:
                    if multi_station:
                        x_seq, y_true, sid = [b.to(device) for b in vbatch]
                        y_pred = model(x_seq, sid)
                    else:
                        x_seq, y_true = vbatch[0].to(device), vbatch[1].to(device)
                        y_pred = model(x_seq)
                    valid_mask = ~torch.isnan(y_true)
                    if valid_mask.sum() == 0:
                        continue
                    val_loss += criterion(y_pred[valid_mask], y_true[valid_mask]).item()
                    n_val += 1
            avg_val = val_loss / max(n_val, 1)
            history["val_loss"].append(avg_val)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                patience_counter = 0
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    logger.info("Early stopping at epoch %d (best val=%.4f).", epoch + 1, best_val_loss)
                    break

        if epoch % 10 == 0:
            val_str = f"val={history['val_loss'][-1]:.4f}" if history["val_loss"] else ""
            logger.debug("Epoch %d/%d  train=%.4f  %s", epoch + 1, max_epochs, avg_train, val_str)

    if best_state is not None:
        model.load_state_dict({k: v.to(device) for k, v in best_state.items()})

    return history


# ──────────────────────────── public classes ──────────────────────────────


class PerStationLSTM:
    """LSTM trained independently on a single station's time-series."""

    name: str = "lstm_per_station"

    def __init__(
        self,
        seq_len: int = SEQ_LEN,
        hidden_size: int = HIDDEN_SIZE,
        num_layers: int = NUM_LAYERS,
        dropout: float = DROPOUT,
        max_epochs: int = MAX_EPOCHS,
        patience: int = PATIENCE,
    ) -> None:
        _set_seed()
        self._seq_len = seq_len
        self._hidden = hidden_size
        self._layers = num_layers
        self._dropout = dropout
        self._max_epochs = max_epochs
        self._patience = patience
        self._device = _get_device()
        self._model: _LSTMNet | None = None
        self._feature_cols: list[str] = []
        self._norm_stats: dict[str, tuple[float, float]] = {}
        self.train_history_: dict[str, list[float]] = {}

    def fit(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame | None = None,
    ) -> PerStationLSTM:
        """Fit LSTM on training DataFrame."""
        _set_seed()
        self._feature_cols = _select_features(train_df)
        if not self._feature_cols:
            logger.error("[%s] No feature columns; cannot fit.", self.name)
            return self

        train_n, self._norm_stats = _normalise_df(train_df, self._feature_cols)

        train_ds = DischargeSequenceDataset(train_n, self._feature_cols, self._seq_len)
        if len(train_ds) == 0:
            logger.warning("[%s] Empty training dataset.", self.name)
            return self

        train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=False, drop_last=True)

        val_loader: DataLoader | None = None
        if val_df is not None and len(val_df) > self._seq_len:
            val_n, _ = _normalise_df(val_df, self._feature_cols, stats=self._norm_stats)
            val_ds = DischargeSequenceDataset(val_n, self._feature_cols, self._seq_len)
            if len(val_ds) > 0:
                val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

        input_size = len(self._feature_cols)
        self._model = _LSTMNet(input_size, self._hidden, self._layers, self._dropout)
        self._model.to(self._device)

        self.train_history_ = _train_loop(
            self._model, train_loader, val_loader, self._device,
            max_epochs=self._max_epochs, patience=self._patience,
        )
        logger.info("[%s] Training complete. Best val_loss=%s",
                    self.name,
                    f"{min(self.train_history_.get('val_loss', [float('nan')])):.4f}" if self.train_history_.get("val_loss") else "N/A")
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Predict discharge, shape (n, 7). Rows without a full seq_len window -> NaN."""
        n = len(df)
        preds = np.full((n, FORECAST_HORIZONS), np.nan)

        if self._model is None or not self._feature_cols:
            logger.warning("[%s] Not fitted.", self.name)
            return preds

        df_n, _ = _normalise_df(df, self._feature_cols, stats=self._norm_stats)
        X_arr = df_n.reindex(columns=self._feature_cols).fillna(0.0).to_numpy(dtype=np.float32)

        self._model.eval()
        all_preds: list[np.ndarray] = []

        with torch.no_grad():
            for i in range(self._seq_len - 1, n):
                x_seq = torch.from_numpy(X_arr[i - self._seq_len + 1: i + 1]).unsqueeze(0).to(self._device)
                y_hat = self._model(x_seq).squeeze(0).cpu().numpy()
                all_preds.append(y_hat)

        # Align: predictions start at index seq_len-1
        for j, pred in enumerate(all_preds):
            preds[j + self._seq_len - 1] = pred

        return preds

    def compute_gradient_sensitivity(
        self, df: pd.DataFrame, max_samples: int = 200
    ) -> dict[str, float]:
        """Compute mean |gradient| of output w.r.t. input features as attribution proxy.

        Returns dict: feature_name -> mean |gradient| over sampled windows.
        """
        if self._model is None or not self._feature_cols:
            return {}

        df_n, _ = _normalise_df(df, self._feature_cols, stats=self._norm_stats)
        X_arr = df_n.reindex(columns=self._feature_cols).fillna(0.0).to_numpy(dtype=np.float32)
        n = len(X_arr)

        grads_accum = np.zeros(len(self._feature_cols), dtype=np.float64)
        n_computed = 0

        self._model.eval()
        indices = list(range(self._seq_len - 1, n))
        if len(indices) > max_samples:
            rng = np.random.default_rng(42)
            indices = rng.choice(indices, size=max_samples, replace=False).tolist()

        for i in indices:
            x_np = X_arr[i - self._seq_len + 1: i + 1]
            x_t = torch.from_numpy(x_np).unsqueeze(0).to(self._device)
            x_t.requires_grad_(True)
            y_hat = self._model(x_t)                # (1, 7)
            scalar = y_hat.sum()
            scalar.backward()
            if x_t.grad is not None:
                g = x_t.grad.abs().mean(dim=1).squeeze(0).cpu().numpy()  # mean over seq_len
                grads_accum += g
                n_computed += 1

        if n_computed == 0:
            return {}

        mean_grads = grads_accum / n_computed
        return dict(zip(self._feature_cols, mean_grads.tolist(), strict=False))

    def save(self, path: str | Path) -> None:
        """Save model state dict and metadata."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "state_dict": self._model.state_dict() if self._model else None,
            "feature_cols": self._feature_cols,
            "norm_stats": self._norm_stats,
            "config": {
                "seq_len": self._seq_len,
                "hidden_size": self._hidden,
                "num_layers": self._layers,
                "dropout": self._dropout,
            },
        }, p)
        logger.info("[%s] Saved model to %s.", self.name, p)

    @classmethod
    def load(cls, path: str | Path) -> PerStationLSTM:
        """Load model from saved state dict."""
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        cfg = checkpoint.get("config", {})
        instance = cls(**cfg)
        instance._feature_cols = checkpoint["feature_cols"]
        instance._norm_stats = checkpoint["norm_stats"]
        if checkpoint["state_dict"] is not None:
            n_feats = len(instance._feature_cols)
            instance._model = _LSTMNet(n_feats, instance._hidden, instance._layers, instance._dropout)
            instance._model.load_state_dict(checkpoint["state_dict"])
            instance._model.to(instance._device)
        return instance


class MultiStationLSTM:
    """Multi-station LSTM with station embeddings, trained on all stations jointly.

    Uses the same sliding window but also takes a station ID integer for embedding
    lookup, allowing the model to learn station-specific biases while sharing
    temporal dynamics representations.
    """

    name: str = "lstm_multi_station"

    def __init__(
        self,
        seq_len: int = SEQ_LEN,
        hidden_size: int = HIDDEN_SIZE,
        num_layers: int = NUM_LAYERS,
        dropout: float = DROPOUT,
        embed_dim: int = EMBED_DIM,
        max_epochs: int = MAX_EPOCHS,
        patience: int = PATIENCE,
    ) -> None:
        _set_seed()
        self._seq_len = seq_len
        self._hidden = hidden_size
        self._layers = num_layers
        self._dropout = dropout
        self._embed_dim = embed_dim
        self._max_epochs = max_epochs
        self._patience = patience
        self._device = _get_device()
        self._model: _MultiStationLSTMNet | None = None
        self._feature_cols: list[str] = []
        self._norm_stats: dict[str, tuple[float, float]] = {}
        self._station_id_map: dict[str, int] = {}
        self.train_history_: dict[str, list[float]] = {}

    def fit(
        self,
        train_dfs: dict[str, pd.DataFrame],
        val_dfs: dict[str, pd.DataFrame] | None = None,
    ) -> MultiStationLSTM:
        """Fit on a dictionary of {station_id: DataFrame}.

        Args:
            train_dfs: training data per station.
            val_dfs:   validation data per station (optional).
        """
        _set_seed()
        if not train_dfs:
            logger.error("[%s] No training data provided.", self.name)
            return self

        # Build station index map (1-based, 0 = padding)
        self._station_id_map = {sid: i + 1 for i, sid in enumerate(sorted(train_dfs.keys()))}

        # Discover feature columns from first station
        first_df = next(iter(train_dfs.values()))
        self._feature_cols = _select_features(first_df)

        # Normalise all stations using combined train stats
        combined = pd.concat(list(train_dfs.values()), ignore_index=True)
        _, self._norm_stats = _normalise_df(combined, self._feature_cols)

        # Build combined dataset
        train_datasets = []
        for sid, df in train_dfs.items():
            df_n, _ = _normalise_df(df.copy(), self._feature_cols, stats=self._norm_stats)
            df_n["station_id"] = sid
            ds = DischargeSequenceDataset(
                df_n, self._feature_cols, self._seq_len,
                station_id_map=self._station_id_map,
            )
            if len(ds) > 0:
                train_datasets.append(ds)

        if not train_datasets:
            logger.warning("[%s] All training datasets empty.", self.name)
            return self

        from torch.utils.data import ConcatDataset
        combined_train = ConcatDataset(train_datasets)
        train_loader = DataLoader(combined_train, batch_size=BATCH_SIZE, shuffle=False, drop_last=True)

        val_loader: DataLoader | None = None
        if val_dfs:
            val_datasets = []
            for sid, df in val_dfs.items():
                if len(df) <= self._seq_len:
                    continue
                df_n, _ = _normalise_df(df.copy(), self._feature_cols, stats=self._norm_stats)
                df_n["station_id"] = sid
                ds = DischargeSequenceDataset(
                    df_n, self._feature_cols, self._seq_len,
                    station_id_map=self._station_id_map,
                )
                if len(ds) > 0:
                    val_datasets.append(ds)
            if val_datasets:
                val_combined = ConcatDataset(val_datasets)
                val_loader = DataLoader(val_combined, batch_size=BATCH_SIZE, shuffle=False)

        n_stations = len(self._station_id_map)
        input_size = len(self._feature_cols)
        self._model = _MultiStationLSTMNet(
            input_size, n_stations, self._embed_dim, self._hidden, self._layers, self._dropout
        )
        self._model.to(self._device)

        self.train_history_ = _train_loop(
            self._model, train_loader, val_loader, self._device,
            max_epochs=self._max_epochs, patience=self._patience, multi_station=True,
        )
        logger.info("[%s] Multi-station training complete on %d stations.", self.name, n_stations)
        return self

    def predict(self, df: pd.DataFrame, station_id: str | None = None) -> np.ndarray:
        """Predict for a single station DataFrame, shape (n, 7)."""
        n = len(df)
        preds = np.full((n, FORECAST_HORIZONS), np.nan)

        if self._model is None or not self._feature_cols:
            logger.warning("[%s] Not fitted.", self.name)
            return preds

        sid_int = self._station_id_map.get(str(station_id), 0) if station_id else 0
        df_n, _ = _normalise_df(df, self._feature_cols, stats=self._norm_stats)
        X_arr = df_n.reindex(columns=self._feature_cols).fillna(0.0).to_numpy(dtype=np.float32)

        self._model.eval()
        with torch.no_grad():
            for i in range(self._seq_len - 1, n):
                x_seq = torch.from_numpy(X_arr[i - self._seq_len + 1: i + 1]).unsqueeze(0).to(self._device)
                sid_t = torch.tensor([sid_int], dtype=torch.long).to(self._device)
                y_hat = self._model(x_seq, sid_t).squeeze(0).cpu().numpy()
                preds[i] = y_hat

        return preds

    def save(self, path: str | Path) -> None:
        """Save multi-station model."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "state_dict": self._model.state_dict() if self._model else None,
            "feature_cols": self._feature_cols,
            "norm_stats": self._norm_stats,
            "station_id_map": self._station_id_map,
            "config": {
                "seq_len": self._seq_len,
                "hidden_size": self._hidden,
                "num_layers": self._layers,
                "dropout": self._dropout,
                "embed_dim": self._embed_dim,
            },
        }, p)
        logger.info("[%s] Saved to %s.", self.name, p)
