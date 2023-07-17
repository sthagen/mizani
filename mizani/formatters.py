"""
Scales have guides and these are what help users make sense of
the data mapped onto the scale. Common examples of guides include
the x-axis, the y-axis, the keyed legend and a colorbar legend.
The guides have demarcations(breaks), some of which must be labelled.

The `*_format` functions below create functions that convert data
values as understood by a specific scale and return string
representations of those values. Manipulating the string
representation of a value helps improve readability of the guide.
"""
from __future__ import annotations

import re
import typing
from bisect import bisect_right
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np

from .breaks import timedelta_helper
from .utils import (
    match,
    precision,
    round_any,
    same_log10_order_of_magnitude,
)

if typing.TYPE_CHECKING:
    from datetime import datetime, tzinfo
    from typing import Literal, Optional, Sequence

    from mizani.typing import (
        BytesSymbol,
        DurationUnit,
        FloatArrayLike,
        NDArrayTimedelta,
        TupleInt2,
    )

__all__ = [
    "comma_format",
    "custom_format",
    "currency_format",
    "dollar_format",
    "percent_format",
    "scientific_format",
    "date_format",
    "number_format",
    "log_format",
    "timedelta_format",
    "pvalue_format",
    "ordinal_format",
    "number_bytes_format",
]

UTC = ZoneInfo("UTC")


@dataclass
class custom_format:
    """
    Custom format

    Parameters
    ----------
    fmt : str, optional
        Format string. Default is the generic new style
        format braces, ``{}``.
    style : 'new' | 'old'
        Whether to use new style or old style formatting.
        New style uses the :meth:`str.format` while old
        style uses ``%``. The format string must be written
        accordingly.

    Examples
    --------
    >>> formatter = custom_format('{:.2f} USD')
    >>> formatter([3.987, 2, 42.42])
    ['3.99 USD', '2.00 USD', '42.42 USD']
    """

    fmt: str = "{}"
    style: Literal["old", "new"] = "new"

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        if self.style == "new":
            return [self.fmt.format(val) for val in x]
        elif self.style == "old":
            return [self.fmt % val for val in x]
        else:
            raise ValueError("style should be either 'new' or 'old'")


# formatting functions
@dataclass
class currency_format:
    """
    Currency formatter

    Parameters
    ----------
    prefix : str
        What to put before the value.
    suffix : str
        What to put after the value.
    digits : int
        Number of significant digits
    big_mark : str
        The thousands separator. This is usually
        a comma or a dot.

    Examples
    --------
    >>> x = [1.232, 99.2334, 4.6, 9, 4500]
    >>> currency_format()(x)
    ['$1.23', '$99.23', '$4.60', '$9.00', '$4500.00']
    >>> currency_format('C$', digits=0, big_mark=',')(x)
    ['C$1', 'C$99', 'C$5', 'C$9', 'C$4,500']
    """

    prefix: str = "$"
    suffix: str = ""
    digits: int = 2
    big_mark: str = ""

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        # create {:.2f} or {:,.2f}
        big_mark = self.big_mark
        comma = "," if big_mark else ""
        tpl = "".join(
            (
                self.prefix,
                "{:",
                comma,
                ".",
                str(self.digits),
                "f}",
                self.suffix,
            )
        )

        labels = [tpl.format(val) for val in x]
        if big_mark and big_mark != ",":
            labels = [val.replace(",", big_mark) for val in labels]
        return labels


dollar_format = currency_format
dollar = dollar_format()


@dataclass
class comma_format:
    """
    Format number with commas separating thousands

    Parameters
    ----------
    digits : int
        Number of digits after the decimal point.

    Examples
    --------
    >>> comma_format()([1000, 2, 33000, 400])
    ['1,000', '2', '33,000', '400']
    """

    digits: int = 0

    def __post_init__(self):
        self.formatter = currency_format(
            prefix="", digits=self.digits, big_mark=","
        )

    def __call__(self, x):
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        return self.formatter(x)


@dataclass
class percent_format:
    """
    Percent formatter

    Multiply by one hundred and display percent sign

    Parameters
    ----------
    use_comma : bool
        If True, use a comma to separate the thousands.
        Default is False.

    Examples
    --------
    >>> formatter = percent_format()
    >>> formatter([.45, 9.515, .01])
    ['45%', '952%', '1%']
    >>> formatter([.654, .8963, .1])
    ['65.4%', '89.6%', '10.0%']
    """

    use_comma: bool = False

    def __post_init__(self):
        self.big_mark = "," if self.use_comma else ""

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        if len(x) == 0:
            return []

        _precision = precision(x)
        x = round_any(x, _precision / 100) * 100

        # When the precision is less than 1, we show
        if _precision > 1:
            digits = 0
        else:
            digits = abs(int(np.log10(_precision)))

        formatter = currency_format(
            prefix="", suffix="%", digits=digits, big_mark=self.big_mark
        )
        labels = formatter(x)
        # Remove unnecessary zeros after the decimal
        pattern = re.compile(r"\.0+%$")
        if all(pattern.search(val) for val in labels):
            labels = [pattern.sub("%", val) for val in labels]
        return labels


percent = percent_format()


@dataclass
class scientific_format:
    """
    Scientific formatter

    Parameters
    ----------
    digits : int
        Significant digits.

    Examples
    --------
    >>> x = [.12, .23, .34, 45]
    >>> scientific_format()(x)
    ['1.2e-01', '2.3e-01', '3.4e-01', '4.5e+01']

    Notes
    -----
    Be careful when using many digits (15+ on a 64
    bit computer). Consider of the `machine epsilon`_.

    .. _machine epsilon: https://en.wikipedia.org/wiki/Machine_epsilon
    """

    digits: int = 3

    def __post_init__(self):
        tpl = f"{{:.{self.digits}e}}"
        self.formatter = custom_format(tpl)
        self.trailling_zeros_pattern = re.compile(r"(0+)e")

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        if len(x) == 0:
            return []

        def count_zeros(s):
            match = self.trailling_zeros_pattern.search(s)
            if match:
                return len(match.group(1))
            else:
                return 0

        # format and then remove superfluous zeros
        labels = self.formatter(x)
        n = min([count_zeros(val) for val in labels])
        if n:
            labels = [val.replace("0" * n + "e", "e") for val in labels]
        return labels


scientific = scientific_format()


@dataclass
class number_format:
    """
    Format floats

    Parameters
    ----------
    digits : int
        Number of digits after the decimal point.

    Examples
    --------
    >>> number_format()([.654, .8963, .1])
    ['0.6540', '0.8963', '0.1000']
    """

    digits: int = 4

    def __post_init__(self):
        # New style format string e.g. '{:1.4f}'
        self.fmt = f"{{:1.{self.digits}f}}".format
        self._zeros_pattern = re.compile(r"\.0+$")

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        labels = [self.fmt(val) for val in x]
        for i, label in enumerate(labels):
            match = self._zeros_pattern.search(label)
            if match:
                labels[i] = self._zeros_pattern.sub("", label)
        return labels


@dataclass
class log_format:
    """
    Log Formatter

    Parameters
    ----------
    base : int
        Base of the logarithm. Default is 10.
    exponent_limits : tuple
        limits (int, int) where if the any of the powers of the
        numbers falls outside, then the labels will be in
        exponent form. This only applies for base 10.
    mathtex : bool
        If True, return the labels in mathtex format as understood
        by Matplotlib.

    Examples
    --------
    >>> log_format()([0.001, 0.1, 100])
    ['0.001', '0.1', '100']

    >>> log_format()([0.0001, 0.1, 10000])
    ['1e-4', '1e-1', '1e4']

    >>> log_format(mathtex=True)([0.0001, 0.1, 10000])
    ['$10^{-4}$', '$10^{-1}$', '$10^{4}$']
    """

    base: float = 10
    exponent_limits: TupleInt2 = (-4, 4)
    mathtex: bool = False

    def _tidyup_labels(self, labels: Sequence[str]) -> Sequence[str]:
        """
        Make all labels uniform in format

        Remove redundant zeros for labels in exponential format.

        Parameters
        ----------
        labels : list-like
            Labels to be tidied.

        Returns
        -------
        out : list-like
            Labels
        """

        def remove_zeroes(s: str) -> str:
            """
            Remove unnecessary zeros for float string s
            """
            tup = s.split("e")
            if len(tup) == 2:
                mantissa = tup[0].rstrip("0").rstrip(".")
                exponent = int(tup[1])
                if exponent:
                    s = "%se%d" % (mantissa, exponent)
                else:
                    s = mantissa
            return s

        def as_exp(s: str) -> str:
            """
            Float string s as in exponential format
            """
            return s if "e" in s else "{:1.0e}".format(float(s))

        def as_mathtex(s: str) -> str:
            """
            Mathtex for maplotlib
            """
            if "e" not in s:
                assert s == "1", f"Unexpected value {s = }, instead of '1'"
                return f"${self.base}^{{0}}$"

            exp = s.split("e")[1]
            return f"${self.base}^{{{exp}}}$"

        # If any are in exponential format, make all of
        # them expontential
        has_e = ["e" in x for x in labels]
        if not all(has_e) and sum(has_e):
            labels = [as_exp(x) for x in labels]

        labels = [remove_zeroes(x) for x in labels]

        has_e = ["e" in x for x in labels]
        if self.mathtex and any(has_e):
            labels = [as_mathtex(x) for x in labels]

        return labels

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        if len(x) == 0:
            return []

        # Decide on using exponents
        if self.base == 10:
            xmin = int(np.floor(np.log10(np.min(x))))
            xmax = int(np.ceil(np.log10(np.max(x))))
            emin, emax = self.exponent_limits
            all_multiples = np.all([np.log10(num).is_integer() for num in x])
            beyond_threshold = xmin <= emin or emax <= xmax
            use_exponents = (
                same_log10_order_of_magnitude(x) or all_multiples
            ) and beyond_threshold
            fmt = "{:1.0e}" if use_exponents else "{:g}"
            labels = [fmt.format(num) for num in x]
            return self._tidyup_labels(labels)
        else:

            def _exp(num, base):
                e = np.log(num) / np.log(base)
                e_round = np.round(e)
                if np.isclose(e, e_round):
                    e = int(e_round)
                else:
                    e = np.round(e, 3)
                return e

            base_txt = f"{self.base}"
            if self.base == np.e:
                base_txt = "e"

            if self.mathtex:
                fmt_parts = (f"${base_txt}^", "{{{e}}}$")
            else:
                fmt_parts = (f"{base_txt}^", "{e}")

            fmt = "".join(fmt_parts)
            exps = [_exp(num, self.base) for num in x]
            labels = [fmt.format(e=e) for e in exps]
            return labels


@dataclass
class date_format:
    """
    Datetime formatter

    Parameters
    ----------
    fmt : str
        Format string. See
        :ref:`strftime <strftime-strptime-behavior>`.
    tz : datetime.tzinfo, optional
        Time zone information. If none is specified, the
        time zone will be that of the first date. If the
        first date has no time information then a time zone
        is chosen by other means.

    Examples
    --------
    >>> from datetime import datetime
    >>> x = [datetime(x, 1, 1) for x in [2010, 2014, 2018, 2022]]
    >>> date_format()(x)
    ['2010-01-01', '2014-01-01', '2018-01-01', '2022-01-01']
    >>> date_format('%Y')(x)
    ['2010', '2014', '2018', '2022']

    Can format time

    >>> x = [datetime(2017, 12, 1, 16, 5, 7)]
    >>> date_format("%Y-%m-%d %H:%M:%S")(x)
    ['2017-12-01 16:05:07']

    Time zones are respected

    >>> UTC = ZoneInfo('UTC')
    >>> UG = ZoneInfo('Africa/Kampala')
    >>> x = [datetime(2010, 1, 1, i) for i in [8, 15]]
    >>> x_tz = [datetime(2010, 1, 1, i, tzinfo=UG) for i in [8, 15]]
    >>> date_format('%Y-%m-%d %H:%M')(x)
    ['2010-01-01 08:00', '2010-01-01 15:00']
    >>> date_format('%Y-%m-%d %H:%M')(x_tz)
    ['2010-01-01 08:00', '2010-01-01 15:00']

    Format with a specific time zone

    >>> date_format('%Y-%m-%d %H:%M', tz=UTC)(x_tz)
    ['2010-01-01 05:00', '2010-01-01 12:00']
    >>> date_format('%Y-%m-%d %H:%M', tz='EST')(x_tz)
    ['2010-01-01 00:00', '2010-01-01 07:00']
    """

    fmt: str = "%Y-%m-%d"
    tz: Optional[tzinfo] = None

    def __post_init__(self):
        if isinstance(self.tz, str):
            self.tz = ZoneInfo(self.tz)

    def __call__(self, x: Sequence[datetime]) -> Sequence[str]:
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        if self.tz is not None:
            x = [d.astimezone(self.tz) for d in x]
        return [d.strftime(self.fmt) for d in x]


@dataclass
class timedelta_format:
    """
    Timedelta formatter

    Parameters
    ----------
    units : str, optional
        The units in which the breaks will be computed.
        If None, they are decided automatically. Otherwise,
        the value should be one of::

            'ns'    # nanoseconds
            'us'    # microseconds
            'ms'    # milliseconds
            's'     # secondss
            'm'     # minute
            'h'     # hour
            'd'     # day
            'w'     # week
            'M'     # month
            'y'     # year

    add_units : bool
        Whether to append the units identifier string
        to the values.
    usetext : bool
        If True, they microseconds identifier string is
        rendered with greek letter *mu*. Default is False.

    Examples
    --------
    >>> from datetime import timedelta
    >>> x = [timedelta(days=31*i) for i in range(5)]
    >>> timedelta_format()(x)
    ['0', '1 month', '2 months', '3 months', '4 months']
    >>> timedelta_format(units='d')(x)
    ['0', '31 days', '62 days', '93 days', '124 days']
    >>> timedelta_format(units='d', add_units=False)(x)
    ['0', '31', '62', '93', '124']
    """

    units: Optional[DurationUnit] = None
    add_units: bool = True
    usetex: bool = False

    def __post_init__(self):
        self._base_format = number_format()
        self.abbreviations = {
            "ns": "ns",
            "us": "us",
            "ms": "ms",
            "s": "s",
            "m": " minute",
            "h": " hour",
            "d": " day",
            "w": " week",
            "M": " month",
            "y": " year",
        }

    def __call__(self, x: NDArrayTimedelta) -> Sequence[str]:
        if len(x) == 0:
            return []

        labels = []
        values, _units = timedelta_helper.format_info(x, self.units)
        plural = "" if _units.endswith("s") else "s"
        ulabel = self.abbreviations[_units]
        if ulabel == "us" and self.usetex:
            ulabel = r"$\mu s$"
        _labels = self._base_format(values)

        if not self.add_units:
            return _labels

        for num, num_label in zip(values, _labels):
            s = "" if num == 1 else plural
            # 0 has no units
            _ulabel = "" if num == 0 else ulabel + s
            labels.append("".join([num_label, _ulabel]))

        return labels


@dataclass
class pvalue_format:
    """
    p-values Formatter

    Parameters
    ----------
    accuracy : float
        Number to round to
    add_p : bool
        Whether to prepend "p=" or "p<" to the output

    Examples
    --------
    >>> x = [.90, .15, .015, .009, 0.0005]
    >>> pvalue_format()(x)
    ['0.9', '0.15', '0.015', '0.009', '<0.001']
    >>> pvalue_format(0.1)(x)
    ['0.9', '0.1', '<0.1', '<0.1', '<0.1']
    >>> pvalue_format(0.1, True)(x)
    ['p=0.9', 'p=0.1', 'p<0.1', 'p<0.1', 'p<0.1']
    """

    accuracy: float = 0.001
    add_p: float = False

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        """
        Format a sequence of inputs

        Parameters
        ----------
        x : array
            Input

        Returns
        -------
        out : list
            List of strings.
        """
        x = round_any(x, self.accuracy)
        below = [num < self.accuracy for num in x]

        if self.add_p:
            eq_fmt = "p={:g}".format
            below_label = f"p<{self.accuracy:g}"
        else:
            eq_fmt = "{:g}".format
            below_label = f"<{self.accuracy:g}"

        labels = [below_label if b else eq_fmt(i) for i, b in zip(x, below)]
        return labels


def ordinal(n: float, prefix="", suffix="", big_mark=""):
    # General Case: 0th, 1st, 2nd, 3rd, 4th, 5th, 6th, 7th, 8th, 9th
    # Special Case: 10th, 11th, 12th, 13th
    n = int(n)
    idx = np.min((n % 10, 4))
    _suffix = ("th", "st", "nd", "rd", "th")[idx]
    if 11 <= (n % 100) <= 13:
        _suffix = "th"

    if big_mark:
        s = f"{n:,}"
        if big_mark != ",":
            s = s.replace(",", big_mark)
    else:
        s = f"{n}"

    return f"{prefix}{s}{_suffix}{suffix}"


@dataclass
class ordinal_format:
    """
    Ordinal Formatter

    Parameters
    ----------
    prefix : str
        What to put before the value.
    suffix : str
        What to put after the value.
    big_mark : str
        The thousands separator. This is usually
        a comma or a dot.

    Examples
    --------
    >>> ordinal_format()(range(8))
    ['0th', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th']
    >>> ordinal_format(suffix=' Number')(range(11, 15))
    ['11th Number', '12th Number', '13th Number', '14th Number']
    """

    prefix: str = ""
    suffix: str = ""
    big_mark: str = ""

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        labels = [
            ordinal(num, self.prefix, self.suffix, self.big_mark) for num in x
        ]
        return labels


@dataclass
class number_bytes_format:
    """
    Bytes Formatter

    Parameters
    ----------
    symbol : str
        Valid symbols are "B", "kB", "MB", "GB", "TB", "PB", "EB",
        "ZB", and "YB" for SI units, and the "iB" variants for
        binary units. Default is "auto" where the symbol to be
        used is determined separately for each value of 1x.
    units : "binary" | "si"
        Which unit base to use, 1024 for "binary" or 1000 for "si".
    fmt : str, optional
        Format sting. Default is ``{:.0f}``.

    Examples
    --------
    >>> x = [1000, 1000000, 4e5]
    >>> number_bytes_format()(x)
    ['1000 B', '977 KiB', '391 KiB']
    >>> number_bytes_format(units='si')(x)
    ['1 kB', '1 MB', '400 kB']
    """

    symbol: Literal["auto"] | BytesSymbol = "auto"
    units: Literal["binary", "si"] = "binary"
    fmt: str = "{:.0f} "

    def __post_init__(self):
        if self.units == "si":
            self.base = 1000
            self._all_symbols = (
                "B",
                "kB",
                "MB",
                "GB",
                "TB",
                "PB",
                "EB",
                "ZB",
                "YB",
            )
        else:
            self.base = 1024
            self._all_symbols = (
                "B",
                "KiB",
                "MiB",
                "GiB",
                "TiB",
                "PiB",
                "EiB",
                "ZiB",
                "YiB",
            )

        # possible exponents of base: eg 1000^1, 1000^2, 1000^3, ...
        exponents = np.arange(1, len(self._all_symbols) + 1, dtype=float)
        self._powers = self.base**exponents
        self._validate_symbol(self.symbol, ("auto",) + self._all_symbols)

    def __call__(self, x: FloatArrayLike) -> Sequence[str]:
        _all_symbols = self._all_symbols
        symbol = self.symbol
        if symbol == "auto":
            power = [bisect_right(self._powers, val) for val in x]
            symbols = [_all_symbols[p] for p in power]
        else:
            power = np.array(match([symbol], _all_symbols))
            symbols = [symbol] * len(x)

        x = np.asarray(x)
        power = np.asarray(power, dtype=float)
        values = x / self.base**power
        fmt = (self.fmt + "{}").format
        labels = [fmt(v, s) for v, s in zip(values, symbols)]
        return labels

    def _validate_symbol(self, symbol: str, allowed_symbols: Sequence[str]):
        if symbol not in allowed_symbols:
            raise ValueError(
                "Symbol must be one of {}".format(allowed_symbols)
            )
