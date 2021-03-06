"""
Implementation and management of scan objects.

A scan object (e.g. :class:`artiq.language.scan.LinearScan`) represents a
one-dimensional sweep of a numerical range. Multi-dimensional scans are
constructed by combining several scan objects, for example using
:class:`artiq.language.scan.MultiScanManager`.

Iterate on a scan object to scan it, e.g. ::

    for variable in self.scan:
        do_something(variable)

Iterating multiple times on the same scan object is possible, with the scan
yielding the same values each time. Iterating concurrently on the
same scan object (e.g. via nested loops) is also supported, and the
iterators are independent from each other.
"""

import random
import inspect
from itertools import product

from artiq.language.core import *
from artiq.language.environment import NoDefault, DefaultMissing
from artiq.language import units


__all__ = ["ScanObject",
           "NoScan", "LinearScan", "RandomScan", "ExplicitScan",
           "Scannable", "MultiScanManager"]


class ScanObject:
    pass


class NoScan(ScanObject):
    """A scan object that yields a single value for a specified number
    of repetitions."""
    def __init__(self, value, repetitions=1):
        self.value = value
        self.repetitions = repetitions

    @portable
    def _gen(self):
        for i in range(self.repetitions):
            yield self.value

    @portable
    def __iter__(self):
        return self._gen()

    def __len__(self):
        return self.repetitions

    def describe(self):
        return {"ty": "NoScan", "value": self.value,
                "repetitions": self.repetitions}


class LinearScan(ScanObject):
    """A scan object that yields a fixed number of evenly
    spaced values in a range."""
    def __init__(self, start, stop, npoints):
        self.start = start
        self.stop = stop
        self.npoints = npoints

    @portable
    def _gen(self):
        if self.npoints == 0:
            return
        if self.npoints == 1:
            yield self.start
        else:
            dx = (self.stop - self.start)/(self.npoints - 1)
            for i in range(self.npoints):
                yield i*dx + self.start

    @portable
    def __iter__(self):
        return self._gen()

    def __len__(self):
        return self.npoints

    def describe(self):
        return {"ty": "LinearScan",
                "start": self.start, "stop": self.stop,
                "npoints": self.npoints}


class RandomScan(ScanObject):
    """A scan object that yields a fixed number of randomly ordered evenly
    spaced values in a range."""
    def __init__(self, start, stop, npoints, seed=None):
        self.start = start
        self.stop = stop
        self.npoints = npoints
        self.seed = seed
        self.sequence = list(LinearScan(start, stop, npoints))
        if seed is None:
            rf = random.random
        else:
            rf = Random(seed).random
        random.shuffle(self.sequence, rf)

    @portable
    def __iter__(self):
        return iter(self.sequence)

    def __len__(self):
        return self.npoints

    def describe(self):
        return {"ty": "RandomScan",
                "start": self.start, "stop": self.stop,
                "npoints": self.npoints,
                "seed": self.seed}


class ExplicitScan(ScanObject):
    """A scan object that yields values from an explicitly defined sequence."""
    def __init__(self, sequence):
        self.sequence = sequence

    @portable
    def __iter__(self):
        return iter(self.sequence)

    def __len__(self):
        return len(self.sequence)

    def describe(self):
        return {"ty": "ExplicitScan", "sequence": self.sequence}


_ty_to_scan = {
    "NoScan": NoScan,
    "LinearScan": LinearScan,
    "RandomScan": RandomScan,
    "ExplicitScan": ExplicitScan
}


class Scannable:
    """An argument (as defined in :class:`artiq.language.environment`) that
    takes a scan object.

    When ``scale`` is not specified, and the unit is a common one (i.e.
    defined in ``artiq.language.units``), then the scale is obtained from
    the unit using a simple string match. For example, milliseconds (``"ms"``)
    units set the scale to 0.001. No unit (default) corresponds to a scale of
    1.0.

    For arguments with uncommon or complex units, use both the unit parameter
    (a string for display) and the scale parameter (a numerical scale for
    experiments).
    For example, a scan shown between 1 xyz and 10 xyz in the GUI with
    ``scale=0.001`` and ``unit="xyz"`` results in values between 0.001 and
    0.01 being scanned.

    :param default: The default scan object. This parameter can be a list of
        scan objects, in which case the first one is used as default and the
        others are used to configure the default values of scan types that are
        not initially selected in the GUI.
    :param global_min: The minimum value taken by the scanned variable, common
        to all scan modes. The user interface takes this value to set the
        range of its input widgets.
    :param global_max: Same as global_min, but for the maximum value.
    :param global_step: The step with which the value should be modified by
        up/down buttons in a user interface. The default is the scale divided
        by 10.
    :param unit: A string representing the unit of the scanned variable.
    :param scale: A numerical scaling factor by which the displayed values
        are multiplied when referenced in the experiment.
    :param ndecimals: The number of decimals a UI should use.
    """
    def __init__(self, default=NoDefault, unit="", scale=None,
                 global_step=None, global_min=None, global_max=None,
                 ndecimals=2):
        if scale is None:
            if unit == "":
                scale = 1.0
            else:
                try:
                    scale = getattr(units, unit)
                except AttributeError:
                    raise KeyError("Unit {} is unknown, you must specify "
                                   "the scale manually".format(unit))
        if global_step is None:
            global_step = scale/10.0
        if default is not NoDefault:
            if not isinstance(default, list):
                default = [default]
            self.default_values = default
        self.unit = unit
        self.scale = scale
        self.global_step = global_step
        self.global_min = global_min
        self.global_max = global_max
        self.ndecimals = ndecimals

    def default(self):
        if not hasattr(self, "default_values"):
            raise DefaultMissing
        return self.default_values[0]

    def process(self, x):
        cls = _ty_to_scan[x["ty"]]
        args = dict()
        for arg in inspect.getargspec(cls).args[1:]:
            if arg in x:
                args[arg] = x[arg]
        return cls(**args)

    def describe(self):
        d = {"ty": "Scannable"}
        if hasattr(self, "default_values"):
            d["default"] = [d.describe() for d in self.default_values]
        d["unit"] = self.unit
        d["scale"] = self.scale
        d["global_step"] = self.global_step
        d["global_min"] = self.global_min
        d["global_max"] = self.global_max
        d["ndecimals"] = self.ndecimals
        return d


class MultiScanManager:
    """
    Makes an iterator that returns elements from the first scan object until
    it is exhausted, then proceeds to the next iterable, until all of the
    scan objects are exhausted. Used for treating consecutive scans as a
    single scan.

    Scan objects must be passed as a list of tuples (name, scan_object).
    Íteration produces scan points that have attributes that correspond
    to the names of the scan objects, and have the last value yielded by
    that scan object.
    """
    def __init__(self, *args):
        self.names = [a[0] for a in args]
        self.scan_objects = [a[1] for a in args]

        class ScanPoint:
            def __init__(self, **kwargs):
                self.attr = set()
                for k, v in kwargs.items():
                    setattr(self, k, v)
                    self.attr.add(k)

            def __repr__(self):
                return ("<ScanPoint " +
                    " ".join("{}={}".format(k, getattr(self, k))
                             for k in self.attr) +
                    ">")

        self.scan_point_cls = ScanPoint

    def _gen(self):
        for values in product(*self.scan_objects):
            d = {k: v for k, v in zip(self.names, values)}
            yield self.scan_point_cls(**d)

    def __iter__(self):
        return self._gen()
