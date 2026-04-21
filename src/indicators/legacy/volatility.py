import numpy as np

def BollingerBands(closes, period, dev):
    ma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    upper = ma + dev * std
    lower = ma - dev * std
    return upper, lower, ma


def ATR(highs, lows, closes, period=20):
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return np.mean(trs[-period:]) if len(trs) >= period else 0