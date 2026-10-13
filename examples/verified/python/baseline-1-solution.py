"""Reporting helpers repaired for Polars 2.0.0."""

import polars as pl


def align_metrics(days, counts):
    """Put two lists side by side; pad the shorter one with nulls."""
    # Build each column with an explicit type so empty inputs keep their schema.
    left = pl.Series("day", days, dtype=pl.String)
    right = pl.Series("count", counts, dtype=pl.Int64)
    # Pad the shorter column with nulls so both columns have the same height.
    height = max(left.len(), right.len())
    left = left.extend_constant(None, height - left.len())
    right = right.extend_constant(None, height - right.len())
    # Build the table from the two aligned columns, keeping input order.
    return pl.DataFrame([left, right])


def decode_categories(codes, labels):
    """Convert zero-based positions to labels, preserving nulls."""
    # Use an ordered Enum of the labels so the result keeps the label order.
    enum_type = pl.Enum(labels)
    codes_series = pl.Series("codes", codes, dtype=pl.Int64)
    # Look up each position in the label list; nulls and out-of-range positions give null.
    label_series = pl.Series("labels", labels, dtype=pl.String)
    decoded = codes_series.map_elements(
        lambda i: label_series[i] if i is not None and 0 <= i < label_series.len() else None,
        return_dtype=pl.String,
    )
    # Cast the decoded strings to the ordered Enum type with the `cat` helper.
    return pl.Series("category", decoded, dtype=pl.String).cast(enum_type)


def parse_dates(values):
    """Read YYYY-MM-DD strings as calendar dates; preserve nulls; reject invalid dates."""
    # Convert with str.to_date using the strict format, so bad strings raise an error.
    series = pl.Series("date", values, dtype=pl.String)
    return series.str.to_date(format="%Y-%m-%d", strict=True)
