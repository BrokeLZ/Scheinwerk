# Scheinwerk HDAs

The five Scheinwerk HDAs, put on Houdini's path by the package:

- `sw_publish_sop.hdalc` (*Scheinwerk Publish*, SOP: publish or task cache, Load from Disk)
- `sw_publish_lop.hdalc` (*Scheinwerk Publish USD*, LOP: publish or task cache, Load from Disk)
- `sw_render.hdalc` (*Scheinwerk Render*, LOP; work in progress, far from done)
- `sw_import_sop.hdalc` (*Scheinwerk Import*, SOP)
- `sw_import_lop.hdalc` (*Scheinwerk Import USD*, LOP)

`.hdalc` because they were saved with Houdini Indie. `sw_render` is built by hand; the other four by `../build_hdas.py` (run it with hython to rebuild them; that replaces hand edits). What is inside them: "Building the HDAs" in `docs/usage.md`. `uv run pytest -m houdini` uses each one.
