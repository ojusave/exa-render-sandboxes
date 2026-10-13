"""Reporting helpers updated for Polars 2.0."""

import polars as pl


def align_metrics(days, counts):
    """Place days and counts side by side, padding the shorter list with nulls."""
    # Use the list lengths to find how many rows the output needs.
    n = max(len(days), len(counts))
    # Build each column at full height so missing entries become nulls.
    day_values = list(days) + [None] * (n - len(days))
    count_values = list(counts) + [None] * (n - len(counts))
    # Explicit dtypes keep the schema stable, including for empty inputs.
    left = pl.DataFrame({"day": pl.Series("day", day_values, dtype=pl.String)})
    right = pl.DataFrame({"count": pl.Series("count", count_values, dtype=pl.Int64)})
    # Column-wise concat (horizontal) requires equal heights, which we now guarantee.
    return pl.concat([left, right], how="horizontal")


def decode_categories(codes, labels):
    """Map zero-based positions to labels, preserving nulls and input order."""
    # Polars 2.0 no longer casts integers to Enum directly; build the Enum with the labels.
    cats = pl.Enum(list(labels))
    # Look up each position in the label list; nulls stay null.
    series = pl.Series("category", list(codes), dtype=pl.Int64)
    lookup = pl.Series("labels", list(labels), dtype=pl.String)
    # Indexing by position gives the label for each code.
    decoded = [None if c is None else labels[c] for c in series.to_list()]
    # Cast the decoded strings into the Enum category type.
    return pl.Series("category", decoded, dtype=pl.String).cast(cats)


def parse_dates(values):
    """Parse YYYY-MM-DD strings into Date values; nulls stay null, bad dates raise."""
    # Polars 2.0 replaced string-to-date casts with str.to_date.
    series = pl.Series("date", list(values), dtype=pl.String)
    # strict=True makes invalid calendar dates raise instead of becoming null.
    return series.str.to_date(format="%Y-%m-%d", strict=True)
