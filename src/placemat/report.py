#!/usr/bin/env python3
"""How a gate hands back its answer.

Two audiences, one at a time. A person reads the summary; a program reads the
JSON. Printing both means the machine-readable form arrives with a table
wrapped round it, and a pipe gets something no parser wants.

So `--json` REPLACES the text rather than accompanying it:

    placemat airwires widget                 the summary, for a person
    placemat airwires widget --json          the measure, on stdout
    placemat airwires widget --json out.json the measure, into a file

`--json` with no value and `--json -` both mean stdout. Writing to a file says
so on STDERR, so the confirmation never lands in something being piped.
"""
import io
import json
import sys

STDOUT = ("-", "stdout")


def json_option(ap, what="the measure"):
    """Declare `--json` on a gate's parser, the same way everywhere."""
    ap.add_argument("--json", nargs="?", const="-", metavar="PATH",
                    help="write %s as JSON; no value, or '-', writes it to stdout "
                         "instead of the summary" % what)


def emit(data, dest, indent=1):
    """Write the machine-readable answer. True when it replaced the summary."""
    if dest is None:
        return False
    if dest in STDOUT:
        json.dump(data, sys.stdout, indent=indent)
        sys.stdout.write("\n")
    else:
        with open(dest, "w") as fh:
            json.dump(data, fh, indent=indent)
        sys.stderr.write("placemat: wrote %s\n" % dest)
    return True


def hush(dest):
    """Hold the summary back while a gate works, when `--json` will answer.

        saved = hush(a.json)
        ...                      the gate does its work and prints as it goes
        unhush(saved)
        emit(data, a.json)

    A gate that prints as it works cannot decide at the end to have said
    nothing, and its printing is rarely all in one function - so this holds
    stdout itself rather than one function's `print`, and covers whatever the
    gate calls. Restore before emitting, or `--json -` would write the answer
    into the bin along with the summary.
    """
    saved = sys.stdout
    if dest is not None:
        sys.stdout = io.StringIO()
    return saved


def unhush(saved):
    """Put stdout back."""
    sys.stdout = saved
