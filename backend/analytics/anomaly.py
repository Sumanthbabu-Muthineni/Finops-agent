import numpy as np
import pandas as pd
from typing import Tuple
from backend.core.models import AnomalyInfo

class IQRAnomalyDetector:
    def __init__(self, multiplier: float = 1.5, min_samples: int = 4):
        self.multiplier = multiplier
        self.min_samples = min_samples

    def detect(self, df: pd.DataFrame, amount_col: str = "amount") -> Tuple[pd.DataFrame, AnomalyInfo]:
        """
        Runs Interquartile Range (IQR) outlier detection over amount series.
        Appends 'is_outlier' boolean column to DataFrame.
        """
        if df.empty or amount_col not in df.columns:
            df["is_outlier"] = False
            return df, AnomalyInfo(detected=False)

        amounts = df[amount_col].dropna().astype(float)

        if len(amounts) < self.min_samples:
            df["is_outlier"] = False
            return df, AnomalyInfo(detected=False)

        q1 = float(np.percentile(amounts, 25))
        q3 = float(np.percentile(amounts, 75))
        iqr = q3 - q1

        # If IQR is 0 (all values nearly identical), use std deviation or small threshold
        if iqr == 0:
            upper_bound = q3 + (amounts.mean() * 0.5)
        else:
            upper_bound = q3 + (self.multiplier * iqr)

        outlier_mask = amounts > upper_bound
        outlier_count = int(outlier_mask.sum())

        df["is_outlier"] = outlier_mask

        if outlier_count > 0:
            max_outlier = float(amounts[outlier_mask].max())
            typical_range = f"${q1:,.2f} – ${q3:,.2f}"
            msg = (
                f"Statistical Outlier Detected: {outlier_count} payout(s) exceeded the historical "
                f"upper bound of ${upper_bound:,.2f} (highest: ${max_outlier:,.2f}). "
                f"Typical baseline is {typical_range}."
            )
            return df, AnomalyInfo(
                detected=True,
                field=amount_col,
                outlier_value=max_outlier,
                typical_range=typical_range,
                affected_rows=outlier_count,
                message=msg
            )

        return df, AnomalyInfo(detected=False)

iqr_detector = IQRAnomalyDetector()
