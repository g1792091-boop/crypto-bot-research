from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pandas as pd


EPSILON = 1e-12


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average."""
    return series.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    previous_close = df["close"].shift(1)
    parts = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return parts.max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return rma(true_range(df), length)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = rma(gain, length)
    average_loss = rma(loss, length)
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100.0 - (100.0 / (1.0 + relative_strength))
    result = result.where(average_loss > EPSILON, 100.0)
    result = result.where(average_gain > EPSILON, 0.0)
    both_zero = (average_gain <= EPSILON) & (average_loss <= EPSILON)
    return result.where(~both_zero, 50.0)


def roc(close: pd.Series, length: int = 9) -> pd.Series:
    previous = close.shift(length)
    return (close / previous - 1.0) * 100.0


def cmo(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(length, min_periods=length).sum()
    down = (-delta.clip(upper=0)).rolling(length, min_periods=length).sum()
    denominator = up + down
    return 100.0 * (up - down) / denominator.replace(0, np.nan)


def bollinger_bands(
    close: pd.Series, length: int = 20, standard_deviations: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(length, min_periods=length).mean()
    deviation = close.rolling(length, min_periods=length).std(ddof=0)
    upper = middle + deviation * standard_deviations
    lower = middle - deviation * standard_deviations
    bandwidth = (upper - lower) / middle.replace(0, np.nan) * 100.0
    return upper, middle, lower, bandwidth


def bull_bear_power(df: pd.DataFrame, length: int = 13) -> Tuple[pd.Series, pd.Series, pd.Series]:
    baseline = ema(df["close"], length)
    bull = df["high"] - baseline
    bear = df["low"] - baseline
    net = bull + bear
    return bull, bear, net


def mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    raw_flow = typical * df["volume"]
    direction = typical.diff()
    positive_flow = raw_flow.where(direction > 0, 0.0)
    negative_flow = raw_flow.where(direction < 0, 0.0)
    positive_sum = positive_flow.rolling(length, min_periods=length).sum()
    negative_sum = negative_flow.rolling(length, min_periods=length).sum()
    ratio = positive_sum / negative_sum.replace(0, np.nan)
    result = 100.0 - (100.0 / (1.0 + ratio))
    result = result.where(negative_sum > EPSILON, 100.0)
    both_zero = (positive_sum <= EPSILON) & (negative_sum <= EPSILON)
    return result.where(~both_zero, 50.0)


def dmi_adx(
    df: pd.DataFrame, di_length: int = 14, adx_smoothing: int = 14
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
        dtype=float,
    )
    average_true_range = rma(true_range(df), di_length)
    plus_di = 100.0 * rma(plus_dm, di_length) / average_true_range.replace(0, np.nan)
    minus_di = 100.0 * rma(minus_dm, di_length) / average_true_range.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = rma(dx, adx_smoothing)
    return plus_di, minus_di, adx


def donchian_channel(
    df: pd.DataFrame, length: int = 20, shift_previous: bool = True
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    upper = df["high"].rolling(length, min_periods=length).max()
    lower = df["low"].rolling(length, min_periods=length).min()
    if shift_previous:
        upper = upper.shift(1)
        lower = lower.shift(1)
    middle = (upper + lower) / 2.0
    return upper, middle, lower


def supertrend(
    df: pd.DataFrame, atr_length: int = 10, multiplier: float = 3.0
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return supertrend line, direction (+1/-1), final upper, final lower."""
    average_true_range = atr(df, atr_length)
    hl2 = (df["high"] + df["low"]) / 2.0
    basic_upper = hl2 + multiplier * average_true_range
    basic_lower = hl2 - multiplier * average_true_range

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    direction = pd.Series(np.nan, index=df.index, dtype=float)
    line = pd.Series(np.nan, index=df.index, dtype=float)

    if len(df) == 0:
        return line, direction, final_upper, final_lower

    for i in range(1, len(df)):
        if pd.isna(average_true_range.iloc[i]):
            continue
        previous_index = df.index[i - 1]
        current_index = df.index[i]
        previous_close = df["close"].iloc[i - 1]

        if pd.isna(final_upper.loc[previous_index]) or (
            basic_upper.iloc[i] < final_upper.loc[previous_index]
            or previous_close > final_upper.loc[previous_index]
        ):
            final_upper.loc[current_index] = basic_upper.iloc[i]
        else:
            final_upper.loc[current_index] = final_upper.loc[previous_index]

        if pd.isna(final_lower.loc[previous_index]) or (
            basic_lower.iloc[i] > final_lower.loc[previous_index]
            or previous_close < final_lower.loc[previous_index]
        ):
            final_lower.loc[current_index] = basic_lower.iloc[i]
        else:
            final_lower.loc[current_index] = final_lower.loc[previous_index]

        previous_direction = direction.loc[previous_index]
        if pd.isna(previous_direction):
            previous_direction = 1.0 if df["close"].iloc[i] >= final_lower.loc[current_index] else -1.0

        if previous_direction < 0 and df["close"].iloc[i] > final_upper.loc[current_index]:
            current_direction = 1.0
        elif previous_direction > 0 and df["close"].iloc[i] < final_lower.loc[current_index]:
            current_direction = -1.0
        else:
            current_direction = previous_direction

        direction.loc[current_index] = current_direction
        line.loc[current_index] = (
            final_lower.loc[current_index] if current_direction > 0 else final_upper.loc[current_index]
        )

    return line, direction, final_upper, final_lower


def chop_zone_proxy(
    df: pd.DataFrame,
    ema_length: int = 34,
    angle_threshold: float = 1.0,
    strong_angle: float = 5.0,
    atr_length: int = 14,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Image-derived Chop Zone proxy.

    The Instagram image did not disclose the original formula. This proxy uses the
    EMA slope normalized by ATR and converts it to an angle. Direction values:
    +2 strong up, +1 up, 0 choppy, -1 down, -2 strong down.
    """
    baseline = ema(df["close"], ema_length)
    average_true_range = atr(df, atr_length)
    normalized_slope = (baseline - baseline.shift(1)) / average_true_range.replace(0, np.nan)
    angle = np.degrees(np.arctan(normalized_slope))
    direction = pd.Series(0.0, index=df.index)
    direction = direction.mask(angle >= angle_threshold, 1.0)
    direction = direction.mask(angle >= strong_angle, 2.0)
    direction = direction.mask(angle <= -angle_threshold, -1.0)
    direction = direction.mask(angle <= -strong_angle, -2.0)
    strength = angle.abs().clip(lower=0, upper=90) / 90.0 * 100.0
    return angle, direction, strength


def crossed_above(left: pd.Series, right: pd.Series | float) -> pd.Series:
    if isinstance(right, pd.Series):
        return (left > right) & (left.shift(1) <= right.shift(1))
    return (left > right) & (left.shift(1) <= right)


def crossed_below(left: pd.Series, right: pd.Series | float) -> pd.Series:
    if isinstance(right, pd.Series):
        return (left < right) & (left.shift(1) >= right.shift(1))
    return (left < right) & (left.shift(1) >= right)


def occurred_recently(event: pd.Series, bars: int) -> bool:
    if event.empty:
        return False
    tail = event.fillna(False).astype(bool).iloc[-max(1, bars) :]
    return bool(tail.any())


def bars_since_last_true(event: pd.Series, max_bars: int) -> int | None:
    tail = event.fillna(False).astype(bool).iloc[-max(1, max_bars) :].to_numpy()
    for offset, value in enumerate(tail[::-1]):
        if value:
            return offset
    return None


def rolling_percentile_threshold(series: pd.Series, lookback: int, percentile: float) -> pd.Series:
    percentile = min(1.0, max(0.0, percentile))
    return series.rolling(lookback, min_periods=lookback).quantile(percentile)


def slope(series: pd.Series, bars: int = 1) -> pd.Series:
    return series - series.shift(bars)


def finite_last(series: pd.Series, default: float = 0.0) -> float:
    if series.empty:
        return default
    value = series.iloc[-1]
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return default
    return value_float if math.isfinite(value_float) else default


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def macd(
    close: pd.Series,
    fast_length: int = 12,
    slow_length: int = 26,
    signal_length: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    fast = ema(close, fast_length)
    slow = ema(close, slow_length)
    line = fast - slow
    signal = ema(line, signal_length)
    histogram = line - signal
    return line, signal, histogram


def awesome_oscillator(
    df: pd.DataFrame, fast_length: int = 5, slow_length: int = 34
) -> pd.Series:
    median = (df["high"] + df["low"]) / 2.0
    return sma(median, fast_length) - sma(median, slow_length)


def williams_r(df: pd.DataFrame, length: int = 14) -> pd.Series:
    highest = df["high"].rolling(length, min_periods=length).max()
    lowest = df["low"].rolling(length, min_periods=length).min()
    return -100.0 * (highest - df["close"]) / (highest - lowest).replace(0, np.nan)


def aroon(df: pd.DataFrame, length: int = 25) -> Tuple[pd.Series, pd.Series]:
    """Aroon up/down using bars since rolling highest/lowest, range 0..100."""
    length = max(2, int(length))

    def _up(values: np.ndarray) -> float:
        # np.argmax returns the oldest occurrence; use reversed for latest tie.
        idx_from_end = int(np.argmax(values[::-1]))
        return 100.0 * (length - idx_from_end) / length

    def _down(values: np.ndarray) -> float:
        idx_from_end = int(np.argmin(values[::-1]))
        return 100.0 * (length - idx_from_end) / length

    up = df["high"].rolling(length, min_periods=length).apply(_up, raw=True)
    down = df["low"].rolling(length, min_periods=length).apply(_down, raw=True)
    return up, down


def ichimoku(
    df: pd.DataFrame,
    tenkan_length: int = 9,
    kijun_length: int = 26,
    span_b_length: int = 52,
    displacement: int = 26,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return Tenkan, Kijun and the *visible-at-current-bar* cloud spans.

    Senkou spans are calculated and shifted forward on a chart. For a no-lookahead
    trading engine the value visible at the current bar is the raw value computed
    ``displacement`` bars earlier, hence ``shift(displacement)``.
    """
    tenkan = (
        df["high"].rolling(tenkan_length, min_periods=tenkan_length).max()
        + df["low"].rolling(tenkan_length, min_periods=tenkan_length).min()
    ) / 2.0
    kijun = (
        df["high"].rolling(kijun_length, min_periods=kijun_length).max()
        + df["low"].rolling(kijun_length, min_periods=kijun_length).min()
    ) / 2.0
    span_a_raw = (tenkan + kijun) / 2.0
    span_b_raw = (
        df["high"].rolling(span_b_length, min_periods=span_b_length).max()
        + df["low"].rolling(span_b_length, min_periods=span_b_length).min()
    ) / 2.0
    span_a = span_a_raw.shift(displacement)
    span_b = span_b_raw.shift(displacement)
    return tenkan, kijun, span_a, span_b


def parabolic_sar(
    df: pd.DataFrame,
    acceleration: float = 0.02,
    acceleration_step: float = 0.02,
    acceleration_max: float = 0.2,
) -> Tuple[pd.Series, pd.Series]:
    """Classic non-lookahead Parabolic SAR.

    Returns SAR value and direction (+1 uptrend / -1 downtrend). The implementation
    uses only information available up to each bar and is suitable for PAPER
    signal evaluation.
    """
    n = len(df)
    sar = pd.Series(np.nan, index=df.index, dtype=float)
    direction = pd.Series(np.nan, index=df.index, dtype=float)
    if n < 2:
        return sar, direction

    uptrend = bool(df["close"].iloc[1] >= df["close"].iloc[0])
    ep = float(df["high"].iloc[:2].max() if uptrend else df["low"].iloc[:2].min())
    current_sar = float(df["low"].iloc[:2].min() if uptrend else df["high"].iloc[:2].max())
    af = float(acceleration)
    sar.iloc[1] = current_sar
    direction.iloc[1] = 1.0 if uptrend else -1.0

    for i in range(2, n):
        current_sar = current_sar + af * (ep - current_sar)
        if uptrend:
            current_sar = min(current_sar, float(df["low"].iloc[i - 1]), float(df["low"].iloc[i - 2]))
            if float(df["low"].iloc[i]) < current_sar:
                uptrend = False
                current_sar = ep
                ep = float(df["low"].iloc[i])
                af = float(acceleration)
            else:
                high = float(df["high"].iloc[i])
                if high > ep:
                    ep = high
                    af = min(float(acceleration_max), af + float(acceleration_step))
        else:
            current_sar = max(current_sar, float(df["high"].iloc[i - 1]), float(df["high"].iloc[i - 2]))
            if float(df["high"].iloc[i]) > current_sar:
                uptrend = True
                current_sar = ep
                ep = float(df["high"].iloc[i])
                af = float(acceleration)
            else:
                low = float(df["low"].iloc[i])
                if low < ep:
                    ep = low
                    af = min(float(acceleration_max), af + float(acceleration_step))
        sar.iloc[i] = current_sar
        direction.iloc[i] = 1.0 if uptrend else -1.0
    return sar, direction


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Return deterministic Heikin-Ashi OHLC, while preserving the source index."""
    out = pd.DataFrame(index=df.index)
    out["ha_close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    ha_open = pd.Series(np.nan, index=df.index, dtype=float)
    if len(df):
        ha_open.iloc[0] = (float(df["open"].iloc[0]) + float(df["close"].iloc[0])) / 2.0
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + out["ha_close"].iloc[i - 1]) / 2.0
    out["ha_open"] = ha_open
    out["ha_high"] = pd.concat([df["high"], out["ha_open"], out["ha_close"]], axis=1).max(axis=1)
    out["ha_low"] = pd.concat([df["low"], out["ha_open"], out["ha_close"]], axis=1).min(axis=1)
    return out


def keltner_channel(
    df: pd.DataFrame,
    ema_length: int = 20,
    atr_length: int = 10,
    multiplier: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    middle = ema(df["close"], ema_length)
    width = atr(df, atr_length) * float(multiplier)
    return middle + width, middle, middle - width


def kst(
    close: pd.Series,
    roc_lengths: Tuple[int, int, int, int] = (10, 15, 20, 30),
    sma_lengths: Tuple[int, int, int, int] = (10, 10, 10, 15),
    signal_length: int = 9,
) -> Tuple[pd.Series, pd.Series]:
    components = []
    for index, (roc_length, smooth_length) in enumerate(zip(roc_lengths, sma_lengths), start=1):
        components.append(sma(roc(close, roc_length), smooth_length) * float(index))
    line = components[0] + components[1] + components[2] + components[3]
    signal = sma(line, signal_length)
    return line, signal


def klinger_oscillator(
    df: pd.DataFrame,
    fast_length: int = 34,
    slow_length: int = 55,
    signal_length: int = 13,
) -> Tuple[pd.Series, pd.Series]:
    """Klinger Volume Oscillator approximation using trend-signed volume force.

    The infographic did not disclose a formula. This implementation follows the
    standard KVO idea (trend-signed volume force with fast/slow EMA difference)
    and is tagged RESEARCH_APPROX in strategy metadata.
    """
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3.0
    trend = pd.Series(np.where(hlc3.diff().fillna(0.0) >= 0.0, 1.0, -1.0), index=df.index)
    spread = (df["high"] - df["low"]).replace(0, np.nan)
    force = trend * df["volume"] * ((2.0 * df["close"] - df["high"] - df["low"]) / spread).fillna(0.0) * 100.0
    line = ema(force, fast_length) - ema(force, slow_length)
    signal = ema(line, signal_length)
    return line, signal


def rolling_volume_profile_poc(
    df: pd.DataFrame,
    lookback: int = 100,
    bins: int = 32,
    *,
    full_series: bool = False,
) -> pd.Series:
    """OHLCV-derived Point of Control approximation.

    The live strategy only needs the POC for the latest completed candle.  The
    previous implementation recalculated every historical rolling window on
    every 5-minute close, which was unnecessarily expensive with 310 Shadow
    variants.  By default this function therefore computes only the latest
    window and places the result at the final index.  Offline walk-forward code
    still obtains a historical series naturally because it evaluates each
    growing slice at its then-current last bar.  ``full_series=True`` remains
    available for diagnostics.

    Binance klines do not contain the exact price-at-volume distribution.  Each
    bar's volume is spread evenly over the bins intersecting its high/low range,
    so this remains a versioned RESEARCH_APPROX rather than a TradingView Volume
    Profile clone.
    """
    result = pd.Series(np.nan, index=df.index, dtype=float)
    lookback = max(10, int(lookback))
    bins = max(8, int(bins))
    if len(df) < lookback:
        return result

    def _window_poc(window: pd.DataFrame) -> float:
        low = float(window["low"].min())
        high = float(window["high"].max())
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            return float("nan")
        edges = np.linspace(low, high, bins + 1)
        profile = np.zeros(bins, dtype=float)
        lows = window["low"].to_numpy(dtype=float)
        highs = window["high"].to_numpy(dtype=float)
        closes = window["close"].to_numpy(dtype=float)
        volumes = np.maximum(0.0, window["volume"].to_numpy(dtype=float))
        for row_low, row_high, row_close, volume in zip(lows, highs, closes, volumes):
            if row_high <= row_low:
                idx = min(
                    bins - 1,
                    max(0, int(np.searchsorted(edges, row_close, side="right") - 1)),
                )
                profile[idx] += volume
                continue
            left = max(0, int(np.searchsorted(edges, row_low, side="right") - 1))
            right = min(bins - 1, int(np.searchsorted(edges, row_high, side="left")))
            count = max(1, right - left + 1)
            profile[left : right + 1] += volume / count
        idx = int(np.argmax(profile))
        return float((edges[idx] + edges[idx + 1]) / 2.0)

    if not full_series:
        result.iloc[-1] = _window_poc(df.iloc[-lookback:])
        return result

    for i in range(lookback - 1, len(df)):
        result.iloc[i] = _window_poc(df.iloc[i - lookback + 1 : i + 1])
    return result


def mapped_rsi_bollinger(
    df: pd.DataFrame,
    bb_length: int = 20,
    bb_std: float = 2.0,
    rsi_length: int = 14,
    signal_length: int = 5,
    map_scale: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Research approximation of ChartPrime's on-chart BB Range RSI oscillator.

    The public description says normalized RSI is mapped *relative to the middle
    basis and band width* and can push beyond half-deviation and outer-band
    extremes. Mapping RSI strictly between lower and upper would make those
    documented outer-band events mathematically impossible. This approximation
    therefore centers RSI 50 on the Bollinger basis and scales the normalized
    -1..+1 RSI range by ``map_scale`` band widths. With the versioned default
    ``map_scale=2``, RSI 75/25 maps near the outer upper/lower band and more
    extreme RSI can move outside it. The exact proprietary/source expression is
    still not claimed; N16 remains RESEARCH_APPROX until Pine output is verified.
    """
    upper, middle, lower, _ = bollinger_bands(df["close"], bb_length, bb_std)
    raw_rsi = rsi(df["close"], rsi_length)
    half_width = (upper - middle).abs()
    normalized_rsi = (raw_rsi - 50.0) / 50.0
    mapped = middle + normalized_rsi * half_width * float(map_scale)
    signal = ema(mapped, signal_length)
    return upper, middle, lower, raw_rsi, mapped, signal


def confirmed_pivot_low(series: pd.Series, left: int = 3, right: int = 3) -> Tuple[pd.Series, pd.Series]:
    """Return confirmation-event bool and pivot value, emitted at confirmation bar."""
    event = pd.Series(False, index=series.index)
    value = pd.Series(np.nan, index=series.index, dtype=float)
    left, right = max(1, int(left)), max(1, int(right))
    for i in range(left + right, len(series)):
        pivot_i = i - right
        window = series.iloc[pivot_i - left : pivot_i + right + 1]
        pivot = series.iloc[pivot_i]
        if pd.notna(pivot) and pivot <= window.min():
            event.iloc[i] = True
            value.iloc[i] = float(pivot)
    return event, value


def confirmed_pivot_high(series: pd.Series, left: int = 3, right: int = 3) -> Tuple[pd.Series, pd.Series]:
    event = pd.Series(False, index=series.index)
    value = pd.Series(np.nan, index=series.index, dtype=float)
    left, right = max(1, int(left)), max(1, int(right))
    for i in range(left + right, len(series)):
        pivot_i = i - right
        window = series.iloc[pivot_i - left : pivot_i + right + 1]
        pivot = series.iloc[pivot_i]
        if pd.notna(pivot) and pivot >= window.max():
            event.iloc[i] = True
            value.iloc[i] = float(pivot)
    return event, value


def vwma(df: pd.DataFrame, length: int = 20) -> pd.Series:
    volume_sum = df["volume"].rolling(length, min_periods=length).sum().replace(0, np.nan)
    return (df["close"] * df["volume"]).rolling(length, min_periods=length).sum() / volume_sum


def cci(df: pd.DataFrame, length: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    mean = typical.rolling(length, min_periods=length).mean()
    mean_deviation = typical.rolling(length, min_periods=length).apply(
        lambda values: float(np.mean(np.abs(values - np.mean(values)))), raw=True
    )
    return (typical - mean) / (0.015 * mean_deviation.replace(0, np.nan))


def vortex_indicator(df: pd.DataFrame, length: int = 14) -> tuple[pd.Series, pd.Series]:
    tr = true_range(df).rolling(length, min_periods=length).sum().replace(0, np.nan)
    plus_vm = (df["high"] - df["low"].shift(1)).abs().rolling(length, min_periods=length).sum()
    minus_vm = (df["low"] - df["high"].shift(1)).abs().rolling(length, min_periods=length).sum()
    return plus_vm / tr, minus_vm / tr


def research_chop_zone(df: pd.DataFrame, ema_length: int = 34, atr_length: int = 14) -> pd.Series:
    """Direction/regime proxy. It is explicitly research-only, not claimed as TradingView source parity."""
    base = ema(df["close"], ema_length)
    atr_line = atr(df, atr_length).replace(0, np.nan)
    slope = (base - base.shift(3)) / atr_line
    result = pd.Series("YELLOW", index=df.index, dtype="object")
    result.loc[slope >= 0.75] = "BLUE"
    result.loc[(slope >= 0.20) & (slope < 0.75)] = "GREEN"
    result.loc[(slope <= -0.20) & (slope > -0.75)] = "RED"
    result.loc[slope <= -0.75] = "DARK_RED"
    return result


def research_chop_regime(df: pd.DataFrame, adx_length: int = 14) -> pd.Series:
    """Research-only regime colour proxy used for N20; separate from directional Chop proxy."""
    adx_line, _, _ = adx_dmi(df, adx_length)
    result = pd.Series("RED", index=df.index, dtype="object")
    result.loc[(adx_line >= 15) & (adx_line < 20)] = "YELLOW"
    result.loc[(adx_line >= 20) & (adx_line < 30)] = "GREEN"
    result.loc[adx_line >= 30] = "BLUE"
    return result


# ---------------------------------------------------------------------------
# V2 strategy compatibility helpers.  The audited V1 indicators keep their
# original return signatures; V2 research strategies use these explicit
# wrappers so existing S1..N16 logic is not silently changed.
# ---------------------------------------------------------------------------
def cross_up(left: pd.Series, right: pd.Series) -> pd.Series:
    return crossed_above(left, right)


def cross_down(left: pd.Series, right: pd.Series) -> pd.Series:
    return crossed_below(left, right)


def adx_dmi(df: pd.DataFrame, length: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    plus_di, minus_di, adx_line = dmi_adx(df, length, length)
    return adx_line, plus_di, minus_di


def supertrend_v2(
    df: pd.DataFrame, atr_length: int = 10, multiplier: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    line, direction, _upper, _lower = supertrend(df, atr_length, multiplier)
    return line, direction.fillna(0.0) > 0.0
