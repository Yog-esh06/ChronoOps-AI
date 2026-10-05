import pandas as pd

from app.analytics import analyze_dataset


def _sample_df():
    timestamps = pd.date_range('2026-01-01', periods=80, freq='5min')
    base = pd.DataFrame({
        'timestamp': timestamps,
        'cpu_usage': 50 + 10 * (pd.Series(range(80)) / 80) + [0, 1] * 40,
        'memory_usage': 60 + 5 * (pd.Series(range(80)) / 80),
        'request_latency': 120 + 20 * (pd.Series(range(80)) / 80) + [0, 0, 0, 6] * 20,
        'error_rate': 0.2 + 0.05 * (pd.Series(range(80)) / 80),
        'network_io': 30 + 2 * (pd.Series(range(80)) / 80),
    })
    return base


def test_analyze_dataset_returns_expected_sections():
    df = _sample_df()
    result = analyze_dataset(df, target_column='request_latency', forecast_horizon=6)

    assert 'dataset_profile' in result
    assert 'forecast' in result
    assert 'anomalies' in result
    assert 'root_causes' in result
    assert result['forecast']['selected_model']
    assert result['dataset_profile']['quality_score'] >= 0
