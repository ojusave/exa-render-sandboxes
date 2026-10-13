"""A reporting module updated for Polars 2.0."""

# Polars works with columns and tables. All of this code runs inside Render.
import polars as pl


def align_metrics(days, counts):
    """Put two lists side by side; pad whichever list is shorter with missing values."""
    # Build each column separately so the lists can have different lengths.
    # Explicit types also describe an empty list.
    left = pl.Series("day", days, dtype=pl.String)
    right = pl.Series("count", counts, dtype=pl.Int64)
    # Pad the shorter column with nulls, keeping input order.
    height = max(left.len(), right.len())
    left = left.extend_constant(None, height - left.len())
    right = right.extend_constant(None, height - right.len())
    # "horizontal_extend" is the Polars 2.0 way to pad shorter frames with nulls.
    return pl.concat(
        [left.to_frame(), right.to_frame()],
        how="horizontal_extend",
    )


def decode_categories(codes, labels):
    """Convert numeric category positions to their labels, preserving missing values."""
    # For example, code 1 with labels ["red", "blue"] represents "blue".
    # Polars 2.0 uses .cat.to(...) instead of casting integers to an Enum.
    return pl.Series("category", codes, dtype=pl.UInt32).cat.to(pl.Enum(labels))


def parse_dates(values):
    """Read ISO dates such as 2026-10-13 as real calendar dates; preserve missing values."""
    # Invalid nonempty dates must raise an error rather than silently becoming missing.
    # Polars 2.0 uses str.to_date(...) instead of casting strings to Date.
    # strict=True makes invalid dates raise instead of becoming null.
    return (
        pl.Series("date", values, dtype=pl.String)
        .str.to_date("%Y-%m-%d", strict=True)
    )
