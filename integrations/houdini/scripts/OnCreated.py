"""Houdini runs this for every new node (spec §13.2): Camera and Light LOPs start under
/world, where the shot structure puts them (§9.2)."""

import scheinwerk.dcc.houdini as sw

sw.on_created(kwargs["node"])  # noqa: F821 (Houdini passes kwargs)
