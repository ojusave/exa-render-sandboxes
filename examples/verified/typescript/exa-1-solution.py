"""A reporting module updated for Polars 2.0."""

# Polars works with columns and tables. All of this code runs inside Render.
import polars as pl


def align_metrics(days, counts):
    """Put two lists side by side; pad whichever list is shorter with missing values."""
    # Build each column with its own explicit type so empty lists keep their types.
    day_series = pl.Series("day", days, dtype=pl.String)
    count_series = pl.Series("count", counts, dtype=pl.Int64)
    # Pad the shorter column with nulls explicitly; Polars 2.0 no longer pads implicitly.
    height = max(day_series.len(), count_series.len())
    day_series = day_series.extend_constant(None, height - day_series.len())
    count_series = count_series.extend_constant(None, height - count_series.len())
    # Combine the columns into one table; both now have equal heights.
    return pl.DataFrame([day_series, count_series])


def decode_categories(codes, labels):
    """Convert numeric category positions to their labels, preserving missing values."""
    # For example, code 1 with labels ["red", "blue"] represents "blue".
    # Build an Enum from the labels, then map each position to its label with a lookup list.
    enum_dtype = pl.Enum(labels)
    codes_series = pl.Series("codes", codes, dtype=pl.UInt32)
    # Positions are indexes into labels; use .cat.to for integer-to-categorical conversion.
    # Null codes stay null automatically.
    return pl.Series("category", codes_series.cast(pl.Int64)).cast(pl.Int64).map_elements(
        lambda i: labels[i] if i is not None else None,
        return_dtype=pl.String,
    ).cast(enum_dtype) if len(labels) > 0 else pl.Series("category", [None] * codes_series.len(), dtype=enum_dtype)


def parse_dates(values):
    """Read ISO dates such as 2026-10-13 as real calendar dates; preserve missing values."""
    # Invalid nonempty dates must raise an error rather than silently becoming missing.
    # str.to_date parses with an explicit format and raises on invalid input.
    return pl.Series("date", values, dtype=pl.String).str.to_date("%Y-%m-%d", strict=True)
