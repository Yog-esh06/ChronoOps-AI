from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.stattools import acf, adfuller, pacf


SEVERITY_THRESHOLDS = [
    (3.0, "LOW"),
    (4.5, "MEDIUM"),
    (6.0, "HIGH"),
    (8.0, "CRITICAL"),
]


def _severity_for_zscore(score: float) -> str:
    for threshold, level in reversed(SEVERITY_THRESHOLDS):
        if abs(score) >= threshold:
            return level
    return "LOW"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _detect_timestamp_column(df: pd.DataFrame) -> Optional[str]:
    candidates = [c for c in df.columns if any(key in str(c).lower() for key in ["time", "date", "stamp", "ts"]) ]
    if not candidates:
        return None
    for col in candidates:
        try:
            sample = pd.to_datetime(df[col], errors="raise")
            if sample.notna().sum() > max(1, len(sample) * 0.8):
                return col
        except Exception:
            continue
    return None


def _normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    numeric = df.select_dtypes(include=[np.number]).copy()
    for col in numeric.columns:
        numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    return numeric


def _count_missing(df: pd.DataFrame) -> Dict[str, int]:
    missing = {col: int(df[col].isna().sum()) for col in df.columns}
    return missing


def _correlation_summary(df: pd.DataFrame) -> Dict[str, float]:
    corr = df.corr(numeric_only=True)
    if corr.empty:
        return {}
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    flattened = upper.stack().dropna()
    if flattened.empty:
        return {}
    return {f"{a}->{b}": round(float(v), 4) for (a, b), v in list(flattened.items())[:10]}


def _approximate_change_points(series: pd.Series) -> List[Dict[str, Any]]:
    if len(series) < 10:
        return []
    values = series.astype(float).to_numpy()
    diffs = np.abs(np.diff(values))
    if diffs.size == 0:
        return []
    threshold = np.percentile(diffs, 85)
    change_points: List[Dict[str, Any]] = []
    for idx, delta in enumerate(diffs, start=1):
        if delta >= threshold and idx > 0:
            change_points.append({"index": int(idx), "delta": round(float(delta), 4)})
    return change_points[:5]


def _quality_score(df: pd.DataFrame) -> float:
    numeric = _normalize_numeric(df)
    total_score = 100.0
    missing_ratio = df.isna().mean().mean() if not df.empty else 0.0
    total_score -= missing_ratio * 40.0
    duplicate_ratio = float(df.duplicated().mean()) if len(df) > 0 else 0.0
    total_score -= duplicate_ratio * 20.0
    if not numeric.empty:
        constant_ratio = (numeric.nunique(dropna=True) == 1).mean()
        total_score -= constant_ratio * 15.0
        outlier_ratio = (np.abs((numeric - numeric.median()) / numeric.std(ddof=0)).gt(4).sum().sum() / max(1, numeric.size))
        total_score -= outlier_ratio * 20.0
    return round(max(0.0, min(100.0, total_score)), 2)


def _estimate_irregularity(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    time_series = pd.to_datetime(df.index, errors="coerce") if isinstance(df.index, pd.DatetimeIndex) else None
    if time_series is None:
        return 0.0
    diffs = time_series.to_series().diff().dropna()
    if diffs.empty:
        return 0.0
    mean_gap = diffs.dt.total_seconds().mean()
    std_gap = diffs.dt.total_seconds().std(ddof=0)
    if not np.isfinite(mean_gap) or mean_gap == 0:
        return 0.0
    return round(float(std_gap / mean_gap), 4)


def _symmetric_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = (np.abs(actual) + np.abs(predicted)) > 0
    if not mask.any():
        return float("nan")
    denom = np.abs(actual[mask]) + np.abs(predicted[mask])
    return float(np.mean(2.0 * np.abs(predicted[mask] - actual[mask]) / denom) * 100.0)


def _target_candidates(df: pd.DataFrame) -> List[str]:
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    preferred = ["target", "value", "metric", "usage", "cpu", "memory", "latency", "error", "network", "demand"]
    scored: List[Tuple[str, int]] = []
    for col in numeric:
        score = sum(1 for token in preferred if token in col.lower())
        scored.append((col, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [col for col, _ in scored] if scored else numeric


def _infer_forecast_target(df: pd.DataFrame, timestamp_col: str) -> str:
    cols = [col for col in df.columns if col != timestamp_col and pd.api.types.is_numeric_dtype(df[col])]
    if not cols:
        return df.columns[0]
    candidates = _target_candidates(df)
    for col in candidates:
        if col in cols:
            return col
    return cols[0]


def _prepare_lag_features(series: pd.Series, max_lags: int = 12) -> pd.DataFrame:
    frame = pd.DataFrame({"target": series})
    for lag in range(1, max_lags + 1):
        frame[f"lag_{lag}"] = series.shift(lag)
    return frame.dropna().copy()


def _rolling_model_metrics(actual: np.ndarray, predicted: np.ndarray) -> Dict[str, float]:
    mae = mean_absolute_error(actual, predicted)
    rmse = math.sqrt(mean_squared_error(actual, predicted))
    r2 = r2_score(actual, predicted) if len(actual) > 1 else 0.0
    try:
        mape = np.mean(np.abs((actual - predicted) / actual)) * 100.0
    except ZeroDivisionError:
        mape = float("nan")
    smape = _symmetric_mape(actual, predicted)
    return {
        "MAE": round(float(mae), 4),
        "RMSE": round(float(rmse), 4),
        "MAPE": round(float(mape), 4) if np.isfinite(mape) else None,
        "sMAPE": round(float(smape), 4) if np.isfinite(smape) else None,
        "R2": round(float(r2), 4),
    }


def _train_and_compare_models(series: pd.Series, horizon: int) -> Dict[str, Any]:
    if len(series) == 0:
        raise ValueError("The selected target series is empty.")

    validation_horizon = min(horizon, max(1, len(series) // 2))
    if len(series) <= 2:
        validation = series.tail(1)
        train = series.iloc[:-1]
    else:
        split_index = max(1, len(series) - validation_horizon)
        train = series.iloc[:split_index]
        validation = series.iloc[split_index:]
        if validation.empty:
            validation = series.tail(1)
            train = series.iloc[:-1]

    models: List[Dict[str, Any]] = []

    if len(validation) > 0:
        naive_pred = np.array([train.iloc[-1]] * len(validation), dtype=float)
        models.append({
            "name": "Naive Baseline",
            "predictions": naive_pred.tolist(),
            "actual": validation.to_numpy(dtype=float).tolist(),
            "metrics": _rolling_model_metrics(validation.to_numpy(dtype=float), naive_pred),
        })

        moving_window = max(2, min(12, len(train) // 2 or 1))
        moving_pred = np.array([train.iloc[-moving_window:].mean()] * len(validation), dtype=float)
        models.append({
            "name": "Moving Average",
            "predictions": moving_pred.tolist(),
            "actual": validation.to_numpy(dtype=float).tolist(),
            "metrics": _rolling_model_metrics(validation.to_numpy(dtype=float), moving_pred),
        })

    try:
        seasonal_period = max(2, min(12, len(train) // 4)) if len(train) > 4 else 2
        fit = ExponentialSmoothing(train, trend="add", seasonal="add", seasonal_periods=seasonal_period).fit(optimized=True)
        sm_pred = fit.forecast(len(validation))
        models.append({
            "name": "Exponential Smoothing",
            "predictions": sm_pred.to_numpy(dtype=float).tolist(),
            "actual": validation.to_numpy(dtype=float).tolist(),
            "metrics": _rolling_model_metrics(validation.to_numpy(dtype=float), sm_pred.to_numpy(dtype=float)),
        })
    except Exception:
        pass

    lag_frame = _prepare_lag_features(train, max_lags=min(12, max(2, len(train) - 1)))
    if len(lag_frame) > 3 and len(validation) > 0:
        X = lag_frame.drop(columns=["target"])
        y = lag_frame["target"]
        lin_model = LinearRegression()
        lin_model.fit(X, y)
        recent_values = train.tail(len(X.columns)).to_numpy().reshape(1, -1)
        pred_frame = pd.DataFrame(np.tile(recent_values, (len(validation), 1)), columns=X.columns)
        pred = lin_model.predict(pred_frame)
        models.append({
            "name": "Linear Lag Model",
            "predictions": pred.tolist(),
            "actual": validation.to_numpy(dtype=float).tolist(),
            "metrics": _rolling_model_metrics(validation.to_numpy(dtype=float), pred),
        })

    if len(train) > 5 and len(validation) > 0:
        try:
            lag_features = _prepare_lag_features(series, max_lags=min(9, max(2, len(series) - 1)))
            X = lag_features.drop(columns=["target"])
            y = lag_features["target"]
            booster = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=200)
            booster.fit(X, y)
            recent = series.tail(X.shape[1]).to_numpy().reshape(1, -1)
            pred_frame = pd.DataFrame(np.tile(recent, (len(validation), 1)), columns=X.columns)
            pred = booster.predict(pred_frame)
            models.append({
                "name": "Gradient Boosting",
                "predictions": pred.tolist(),
                "actual": validation.to_numpy(dtype=float).tolist(),
                "metrics": _rolling_model_metrics(validation.to_numpy(dtype=float), pred),
            })
        except Exception:
            pass

    if not models:
        raise ValueError("No forecasting models could be trained.")

    best = min(models, key=lambda m: m["metrics"].get("RMSE", float("inf")))
    last_value = float(series.iloc[-1])
    if len(series) > 1:
        slope = (series.iloc[-1] - series.iloc[0]) / max(1, len(series) - 1)
    else:
        slope = 0.0
    forecast_values: List[float] = []
    for i in range(horizon):
        forecast_values.append(float(last_value + slope * (i + 1)))

    return {"comparison": [{"model": m["name"], "metrics": m["metrics"]} for m in models], "best_model": best["name"], "forecast": forecast_values, "validation_actual": validation.to_list(), "validation_predicted": best["predictions"], "suggested_horizon": horizon}


def _compute_time_series_intelligence(series: pd.Series, timestamp_index: Optional[pd.DatetimeIndex] = None) -> Dict[str, Any]:
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return {"trend": 0.0, "seasonality_score": 0.0, "stationarity_p_value": 1.0, "autocorrelation": 0.0, "change_points": []}

    trend = float(np.polyfit(np.arange(len(series)), series.to_numpy(), 1)[0]) if len(series) > 1 else 0.0
    seasonal_values = np.fft.rfft(series.to_numpy())
    seasonality_score = float(np.abs(seasonal_values[1:len(seasonal_values)]).mean() / max(1e-9, np.abs(seasonal_values).mean())) if len(seasonal_values) > 1 else 0.0
    try:
        adf_result = adfuller(series.to_numpy(), autolag='AIC')
        stationarity_stat = adf_result[0]
        stationarity_p_value = adf_result[1]
    except Exception:
        stationarity_stat = np.nan
        stationarity_p_value = 1.0
    lag_values = acf(series.to_numpy(), nlags=min(10, len(series)-1), fft=True)
    autocorr = float(lag_values[1]) if len(lag_values) > 1 else 0.0
    return {
        "trend": round(trend, 4),
        "seasonality_score": round(seasonality_score, 4),
        "stationarity_p_value": round(float(stationarity_p_value), 6),
        "autocorrelation": round(autocorr, 4),
        "change_points": _approximate_change_points(series),
    }


def analyze_dataset(df: pd.DataFrame, target_column: Optional[str] = None, forecast_horizon: int = 12) -> Dict[str, Any]:
    if df.empty:
        raise ValueError("The uploaded dataset is empty.")

    cleaned_df = df.copy()
    timestamp_col = _detect_timestamp_column(cleaned_df)
    if timestamp_col:
        try:
            cleaned_df[timestamp_col] = pd.to_datetime(cleaned_df[timestamp_col], errors="coerce")
            cleaned_df = cleaned_df.dropna(subset=[timestamp_col]).sort_values(by=timestamp_col).reset_index(drop=True)
        except Exception:
            timestamp_col = None

    if timestamp_col is not None:
        cleaned_df = cleaned_df.set_index(timestamp_col)

    numeric_df = _normalize_numeric(cleaned_df)
    numeric_cols = list(numeric_df.columns)
    if not numeric_cols:
        raise ValueError("The dataset did not contain numeric columns suitable for forecasting or anomaly analysis.")

    if not target_column or target_column not in cleaned_df.columns:
        target_column = _infer_forecast_target(cleaned_df, timestamp_col or "")

    if target_column not in numeric_df.columns:
        target_column = numeric_cols[0]

    dataset_profile = {
        "rows": int(len(cleaned_df)),
        "columns": list(cleaned_df.columns),
        "timestamp_column": timestamp_col,
        "numeric_columns": numeric_cols,
        "categorical_columns": [col for col in cleaned_df.columns if col not in numeric_cols],
        "missing_values": _count_missing(cleaned_df),
        "duplicate_rows": int(cleaned_df.duplicated().sum()),
        "quality_score": _quality_score(cleaned_df),
        "irregular_sampling": _estimate_irregularity(cleaned_df),
        "outlier_summary": {col: int((pd.to_numeric(cleaned_df[col], errors="coerce") - pd.to_numeric(cleaned_df[col], errors="coerce").median()).abs().gt(3 * pd.to_numeric(cleaned_df[col], errors="coerce").std(ddof=0)).sum()) for col in numeric_cols if cleaned_df[col].notna().any()},
        "correlation_summary": _correlation_summary(numeric_df),
        "target_candidates": _target_candidates(cleaned_df),
    }

    target_series = pd.to_numeric(cleaned_df[target_column], errors="coerce").dropna()
    if target_series.empty:
        raise ValueError("Selected target column has no valid numeric values.")

    if timestamp_col:
        target_series = target_series.reindex(cleaned_df.index)
        valid_index = cleaned_df.index[cleaned_df[target_column].notna()]
        target_series = pd.Series(pd.to_numeric(cleaned_df.loc[valid_index, target_column], errors="coerce").values, index=valid_index)
        if target_series.index.inferred_type == "datetime64":
            target_series = target_series.sort_index()

    forecast_results = _train_and_compare_models(target_series, horizon=max(1, forecast_horizon))

    anomalies = []
    for metric in numeric_cols:
        if metric == target_column and len(cleaned_df) < 10:
            continue
        values = pd.to_numeric(cleaned_df[metric], errors="coerce").dropna()
        if values.empty:
            continue
        median = values.median()
        std = values.std(ddof=0) or 1.0
        zscore = (values - median) / std
        baseline = pd.Series(median, index=values.index)
        for idx, value in values.items():
            score = float(zscore.loc[idx]) if idx in zscore.index else 0.0
            if abs(score) < 2.5:
                continue
            anomaly = {
                "timestamp": str(idx) if not isinstance(idx, pd.Timestamp) else idx.isoformat(),
                "metric": metric,
                "observed_value": round(float(value), 4),
                "expected_value": round(float(baseline.loc[idx]), 4),
                "deviation": round(float(abs(value - baseline.loc[idx])), 4),
                "severity": _severity_for_zscore(score),
                "detection_method": "z-score",
                "confidence": round(min(0.98, 0.5 + abs(score) / 10.0), 4),
            }
            anomalies.append(anomaly)

    if len(anomalies) > 0:
        anomalies = sorted(anomalies, key=lambda item: item["deviation"], reverse=True)[:25]

    if target_column in cleaned_df.columns and len(cleaned_df) > 10:
        root_causes = []
        target_values = pd.to_numeric(cleaned_df[target_column], errors="coerce")
        for feature in [col for col in numeric_cols if col != target_column][:8]:
            feature_values = pd.to_numeric(cleaned_df[feature], errors="coerce")
            common = pd.concat([target_values, feature_values], axis=1).dropna()
            if len(common) < 3:
                continue
            corr = common.iloc[:, 0].corr(common.iloc[:, 1])
            if pd.isna(corr):
                continue
            root_causes.append({
                "feature": feature,
                "contribution": round(float(abs(corr) * 100.0), 2),
                "direction": "positive" if corr > 0 else "negative",
            })
        root_causes = sorted(root_causes, key=lambda item: item["contribution"], reverse=True)[:5]
    else:
        root_causes = []

    time_series_intelligence = _compute_time_series_intelligence(target_series)
    return {
        "dataset_profile": dataset_profile,
        "forecast": {
            "target_column": target_column,
            "selected_model": forecast_results["best_model"],
            "comparison": forecast_results["comparison"],
            "forecast_values": forecast_results["forecast"],
            "validation_actual": forecast_results["validation_actual"],
            "validation_predicted": forecast_results["validation_predicted"],
            "time_series": {
                "trend": time_series_intelligence["trend"],
                "seasonality_score": time_series_intelligence["seasonality_score"],
                "stationarity_p_value": time_series_intelligence["stationarity_p_value"],
                "autocorrelation": time_series_intelligence["autocorrelation"],
                "change_points": time_series_intelligence["change_points"],
            },
        },
        "anomalies": anomalies,
        "root_causes": root_causes,
    }
