"""Maintainer-owned solution used only to validate the test fixture, never sent to the model."""

# This library handles the actual table operations in the cloud sandbox.
import polars as pl


def align_metrics(days, counts):
    """Polars 2 requires explicit permission to pad unequal-height tables."""
    left = pl.DataFrame({"day": pl.Series(days, dtype=pl.String)})
    right = pl.DataFrame({"count": pl.Series(counts, dtype=pl.Int64)})
    return pl.concat([left, right], how="horizontal_extend")


def decode_categories(codes, labels):
    """Use the dedicated category conversion with the caller's label ordering."""
    return pl.Series("category", codes, dtype=pl.UInt32).cat.to(pl.Enum(labels))


def parse_dates(values):
    """Use the dedicated date parser with a fixed format and strict validation."""
    return pl.Series("date", values, dtype=pl.String).str.to_date("%Y-%m-%d", strict=True)
