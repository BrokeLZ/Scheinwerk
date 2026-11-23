# Loaded by Houdini at startup (via the Scheinwerk package). Sets SW_* and $JOB on every
# scene load/save. Houdini 21 reads python3.11libs/, Houdini 22 python3.13libs/.
try:
    import scheinwerk.dcc.houdini as _sw

    _sw.startup()
except Exception:  # never stop Houdini from starting
    import logging

    logging.getLogger("scheinwerk.houdini").exception("Scheinwerk startup failed")
