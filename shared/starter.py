"""An older reporting module, deliberately incompatible with Polars 2.0."""

# Polars works with columns and tables. All of this code runs inside Render.
import polars as pl


def align_metrics(days, counts):
    """Put two lists side by side; pad whichever list is shorter with missing values."""
    # Explicit types also describe an empty list. The old horizontal mode padded rows.
    left = pl.DataFrame({"day": pl.Series(days, dtype=pl.String)})
    right = pl.DataFrame({"count": pl.Series(counts, dtype=pl.Int64)})
    return pl.concat([left, right], how="horizontal")


def decode_categories(codes, labels):
    """Convert numeric category positions to their labels, preserving missing values."""
    # For example, code 1 with labels ["red", "blue"] represents "blue".
    return pl.Series("category", codes, dtype=pl.UInt32).cast(pl.Enum(labels))


def parse_dates(values):
    """Read ISO dates such as 2026-10-13 as real calendar dates; preserve missing values."""
    # Invalid nonempty dates must raise an error rather than silently becoming missing.
    return pl.Series("date", values, dtype=pl.String).cast(pl.Date)
