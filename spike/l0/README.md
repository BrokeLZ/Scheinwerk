# L0 spike (spec §17.12)

Throwaway scripts that answer the *(L0)* questions of spec §17 with the real Houdini 21 tools.
Not part of Scheinwerk: nothing in `src/` imports them, and they can be deleted once the findings
are in the spec.

| Script | Runs in | Question |
| --- | --- | --- |
| `s01_textures.py` | Python 3.11 | Which texture tools ship with Houdini 21, and which flags do colour conversion, half float, lat-long, UDIM, data roles, normal flip, gloss invert, spec/gloss maths, previews |
| `s02_karma_tx.py` | hython | Do Karma CPU and XPU use the `.tx` MIP levels and the `colorSpace` metadata |
| `s03_search_path.py` | Python 3.11 | `PXR_AR_DEFAULT_SEARCH_PATH` in Ar, LOPs, the USD ROP's *Use Relative Paths*, husk and Karma texture lookups; a Houdini package that sets it |
| `s04_domelight.py` | hython | What the Dome Light LOP authors, and which hand-written DomeLight looks the same |
| `s05_variants.py` | hython | A component whose `variant` set switches payloads across version folders, from a shot, as PointInstancer prototypes and native instances |
| `s06_triplanar.py` | hython | MaterialX image and triplanar nodes in Karma, normal maps under triplanar |
| `s07_model_import.py` | hython | Headless fbx / gltf / glb / obj / abc → USD |
| `s08_preview.py` | hython | Preview scene as USDA text, framing, husk renders, JPEG thumbnails |

Results go to `spike/l0/out/<os>/` (ignored by git): one `<script>.md` per script, the rendered
images, and `REPORT.md` with everything together.

## macOS

```bash
uv run --no-project --python 3.11 python spike/l0/run_all.py
```

## Windows

Houdini 21 must be installed in the default place (`C:\Program Files\Side Effects Software\Houdini 21.0.*`).
If it is somewhere else, set `SW_SPIKE_HFS` to that folder first. From the repository root in PowerShell:

```powershell
uv run --no-project --python 3.11 python spike\l0\run_all.py
```

Without uv, Houdini's own Python works too:

```powershell
& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" spike\l0\run_all.py
```

It takes about 10–15 minutes (s06 renders the most). Karma XPU uses the GPU on Windows, so the
XPU lines there are the interesting ones. Send back `spike\l0\out\windows\REPORT.md`.

Single scripts: `run_all.py s03 s05`, or run a script directly with `python` / `hython`.
