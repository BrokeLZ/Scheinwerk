# L0 findings (macOS, Houdini 21.0.596 Indie)

Windows: pending (`run_all.py` → `out/windows/REPORT.md`).
First Windows note (Houdini 21.0.596, from the test suite, not `run_all.py`): with `OCIO` unset,
`hoiiotool` uses `ocio://default`, which names the sRGB texture space `sRGB Encoded Rec.709 (sRGB)`
(now accepted by `core/textures.py`). Everything below is from macOS
(Apple Silicon, Karma XPU on the CPU device). Each item: what was found, then the text proposed
for the spec. The proposals below are now in `docs/spec.md` §17.

## 1. Texture tools and flags (§17.5 Tools, §17.2 external tools) — `s01`

**Found**

- `$HFS/bin` has `hoiiotool` (= oiiotool; OIIO 2.5.18, OCIO 2.4.1), `imaketx` (SideFX), `iconvert`,
  `husk`, `hython`. No `maketx`/`oiiotool` by those names. hython also has the Python modules
  `OpenImageIO`, `PyOpenColorIO`, `MaterialX` (1.39.3).
- `imaketx` has no data-type control: its default `.tx` is **uint8 TIFF even after converting to
  ACEScg** (banding). Not usable for colour roles. `hoiiotool` does everything needed.
- `hoiiotool -d half -otex x.tx` writes **float** TIFF (TIFF has no half). Half needs the OpenEXR
  container: `-otex x.exr`, or `-otex:fileformatname=openexr x.tx` (Karma reads both).
  The EXR records `oiio:ColorSpace`; TIFF does not.
- Data roles keep their bit depth: uint8 and uint16 stay integer in a TIFF `.tx`.
- DX → GL normals: `--invert:chbegin=1:chend=2` (or `--mulc 1,-1,1 --addc 0,1,0`). Gloss → roughness:
  `--invert`. Both keep uint8.
- HDRI: `-oenv` writes `textureformat = "LatLong Environment"`. **Half output clamps to 65504**
  (no inf): a 100 000 sun loses a third of its energy. The peak is read with `--stats` (Max).
- `<UDIM>` in a file name **crashes hoiiotool** (SIGABRT). `--frames 1001,1002` + `#` works;
  one call per tile is simplest.
- Spec/gloss → metal/rough works with one hoiiotool command line (`--label`, `--maxchan`, `--subc`,
  `--divc`, `--clamp`, `--sub`, `--mul`, `--add`), values checked against Python maths.
- Thumbnails: `--ociodisplay:from=ACEScg "sRGB - Display" "ACES 1.0 - SDR Video"` + `--fit 512x512`
  → JPEG. The config's default view is *Un-tone-mapped* (clips HDRIs).
- Input formats of Houdini's OIIO: bmp, cineon, dds, dpx, fits, hdr, ico, iff, jpeg, openexr,
  png, pnm, psd, rla, sgi, softimage, targa, tiff, zfile. **No webp, jxl, heif, jpeg2000.**
- Speed: 4k sRGB → ACEScg half tiled EXR in 0.7 s.

**Proposed spec text**

- §17.5 Tools: "It runs `hoiiotool` from the Houdini installation (`oiiotool` on `PATH` works too),
  found as in §17.2. `imaketx` is not used: it cannot set the data type. UDIM tiles are processed
  one call per tile (hoiiotool's `<UDIM>` handling crashes)."
- §17.2: "External tools are found in `$HFS/bin` when `HFS` is set, else in the newest Houdini 21.0
  installation in the OS's default folder (macOS `/Applications/Houdini/Houdini21.0.*`, Windows
  `C:\Program Files\Side Effects Software\Houdini 21.0.*`), else on `PATH`; the user setting `tools`
  overrides each one."
- §17.3 table / §17.5 Output (**decision needed**, see questions): half and float outputs are tiled,
  mipmapped OpenEXR named `.exr`; 8/16-bit data outputs are tiled, mipmapped TIFF named `.tx`.
- §17.5 HDRI: "half unless the source peak (hoiiotool `--stats`) exceeds 65504, then float
  (hoiiotool clamps half at 65504, it doesn't write inf)."
- §17.5 spec/gloss: drop *(L0)*: "computed by hoiiotool alone; specular and diffuse are linearised
  first."
- §17.5 Detection: "Formats hoiiotool can't read (webp, jxl, heif, jp2, …) are listed as unsupported."
- version.json `tools`: `{"hoiiotool": "2.5.18.0"}`.

## 2. Karma: `.tx` MIP levels and `colorSpace` (§17.5, §17.3) — `s02`

**Found**

- Karma CPU and XPU both read the file's own MIP levels (a texture with red level 0 and green
  smaller levels renders green when minified). XPU ignores them only under an **orthographic**
  camera.
- `colorSpace` metadata on `inputs:file` is honoured by CPU and XPU identically, with OCIO names
  (`sRGB - Texture`, `ACEScg`, `Linear Rec.709 (sRGB)`, `Raw`) and MaterialX names (`srgb_texture`,
  `acescg`, `lin_rec709`, `raw`).
- Without metadata Karma guesses: 8-bit → sRGB, float → already in the rendering space. It
  **ignores the colour space stored in the file** (`oiio:ColorSpace = ACEScg` was not converted).
  Data maps without `raw` would be linearised as sRGB.
- Karma renders in the OCIO `scene_linear` role: **Linear Rec.709 (sRGB)** in Houdini 21's default
  config, not ACEScg. ACEScg textures tagged `ACEScg` are converted to it correctly, so
  `working_space` doesn't have to match the renderer.
- Houdini's `mtlximage` writes `colorSpace` from its `filecolorspace` parm, and expands `$HIP` into
  an absolute path when it authors the file value (confirms "never `$SW_LIBRARY` in USD").

**Proposed spec text**

- §17.3: "Every texture input carries `colorSpace`: `working_space` for colour roles, `raw` for data
  roles (names as in the OCIO config; Karma also accepts the MaterialX names). Karma ignores the
  colour space recorded inside a file and guesses without the metadata (8-bit = sRGB), so the
  metadata is required."
- §17.5: "Karma converts from the tagged space to its rendering space (the config's `scene_linear`,
  Linear Rec.709 in Houdini's default config), so `working_space` need not be the rendering space."
- Drop *(L0)* in §17.12 for this item.

## 3. Library-relative paths through the search path (§17.2, §17.8) — `s03`

**Found**

- With `PXR_AR_DEFAULT_SEARCH_PATH` = the library root, set **before the process starts** (Ar reads
  it once): Ar resolves `model/<id>/v001/<id>.usd` and non-USD `hdri/<id>/v001/<file>.exr`; the
  file-relative paths inside library files (`./textures/…`) resolve; the Reference LOP loads it;
  husk CPU and XPU render the model, its textures and a DomeLight texture given library-relative.
  Without the variable nothing resolves.
- The USD ROP with *Use Relative Paths* leaves library-relative references and texture paths
  untouched.
- `$SW_LIBRARY/model/…` typed into a Reference LOP ends up as a **file-relative path**
  (`../../../../../../../library/model/…`) after the ROP: not absolute, but tied to where project
  and library sit relative to each other.
- A Houdini package sets `SW_LIBRARY` and `"PXR_AR_DEFAULT_SEARCH_PATH": "$SW_LIBRARY"`.
  **`"method": "prepend"` replaces a value already set in the OS environment** instead of
  prepending (Houdini 21, macOS).
- Library-relative paths must not start with `./`, `../` or `/` (those are anchored, not searched).

**Proposed spec text**

- §17.2: "The Houdini package sets `SW_LIBRARY` and `PXR_AR_DEFAULT_SEARCH_PATH` to the library root
  (as a plain value: a package `prepend` replaces a value set outside Houdini). Every husk or
  hython job started by `sw lib` gets both in its environment. Ar reads the variable once at
  startup, so changing the library needs a restart of Houdini."
- §17.8: drop *(L0)*; add "A `$SW_LIBRARY/…` path in a USD-authoring parm becomes a file-relative
  path to the library when the layer is saved, which breaks on machines where the library sits
  elsewhere relative to the project: library tools always write library-relative paths."

## 4. DomeLight orientation (§17.8) — `s04`

**Found**

- Houdini 21's Dome Light LOP (`domelight::3.0`) authors `DomeLight_1` at `/world/lights/domelight1`
  with `poleAxis = "scene"`, an identity `xformOp:transform`, and no `karma:light:renderlightgeo`.
- In a Y-up stage, `DomeLight_1` (poleAxis scene, Y or unset) and the legacy `DomeLight`, without
  any rotation, look exactly like the LOP on CPU and XPU: the image centre (u = 0.5) faces **+Z**,
  u = 0.25 faces +X, the seam (u = 0) faces −Z (what an unrotated camera sees), the top row is +Y.
  No compensating rotation is needed.
- The dome is visible to the camera only with `karma:light:renderlightgeo = 1`.

**Proposed spec text**

- §17.8 HDRIs: "a node that creates `/world/lights/<item id>` as a `DomeLight_1` with
  `poleAxis = "scene"` and no rotation of its own (as Houdini 21's Dome Light LOP: the image centre
  faces +Z), its texture the chosen variant's file, library-relative, tagged `working_space`; a
  rotation about Y and *visible to camera* (`karma:light:renderlightgeo`) are the node's controls."

## 5. A component whose `variant` set switches payloads across versions (§17.3) — `s05`

**Found** (all as specified, CPU and XPU)

- `{id}.usd` in v002 with `variant` = { main → `../v001/payload_main.usd`, winter →
  `./payload_winter.usd` } composes opened directly and by search path from a shot.
- A selection authored on the referencing prim picks it; a nested `model` set authored inside
  the payload is visible and selectable through it.
- PointInstancer: two prototype prims referencing the same component with different selections
  render green/white/green/white. Native instancing: one prototype per distinct selection.
- The `variant` choices are visible **with the payload unloaded** (the set sits outside the
  payloads; `model`/`look` sets inside appear only once loaded).
- Houdini's Set Variant LOP lists `main`, `winter`.
- Trap for code: setting a variant on a stage opened on the library file edits that library layer
  in memory (and every later stage sees it). Tools must author selections in the referencing layer
  or the session layer.

**Proposed spec text**

- §17.3 Model: add "The `variant` set sits on the component prim outside the payloads, so its
  choices show with payloads unloaded (unlike the project's `model`/`look` sets, §9.3)."
- §17.8: "Tools author variant selections in the referencing layer, never in a library layer."

## 6. MaterialX image / triplanar nodes, normal maps under triplanar (§17.8) — `s06`

**Found**

- `ND_image_*` and `ND_triplanarprojection_*` work identically on CPU and XPU.
- MaterialX triplanar (up axis Y): X faces u = +Z, v = +Y; Y faces u = +X, v = +Z; Z faces u = +X,
  v = +Y; the negative faces are mirrored.
- Normal maps (box with UVs that disagree with the projections, map tilted towards +u / +v):

  | Method | CPU | XPU |
  | --- | --- | --- |
  | triplanar the normal map → `normalmap` (UV tangent) | mirrored on 2 of 6 checks | same |
  | SideFX `hmtlxpbrtextureset` (MtlX PBR Texture Set), Tri-Planar | mirrored (same as above: it does exactly that) | same |
  | Karma `kma_hextiled_triplanar` (normals) | off on most faces (hex tiling, own convention) | garbage |
  | per axis: image + `normalmap` with that axis' tangent/bitangent as **values** | mirrored: Karma ignores constant tangent values | same |
  | per axis, tangent/bitangent **connected** from constant nodes | **correct** | **correct** |
  | per axis, decoded by hand (T·x + B·y + N·z) | **correct** | **correct** |

**Proposed spec text**

- §17.8 `sw_texture_set`: drop *(L0)*; add "Under triplanar projection each map is projected
  along the three axes (position in metres: `position / size_m`) and blended by the normal. Normal
  maps are decoded per projection axis with that axis' tangent and bitangent and then blended:
  the obvious chain (triplanar of the normal map → normalmap) and SideFX's MtlX PBR Texture Set
  use the mesh's UV tangents and are wrong under triplanar. Karma's `normalmap` ignores tangents
  given as plain values, so they are connected from constant nodes. Only standard MaterialX nodes
  are used (no `kma_*`), so CPU and XPU render the same."

## 7. Headless model import (§17.6) — `s07`

**Found**

- Houdini 21 ships USD file-format plugins `usdFbx`, `usdGltf` (gltf, glb), `geo` (obj, bgeo) and
  `abc`. In hython `Usd.Stage.Open("x.fbx")` works headless in ~0.2 s: meshes with `st`,
  materials as `UsdPreviewSurface` + `UsdUVTexture`, bindings (glTF; a Houdini-written FBX had the
  material but no binding).
- Texture paths come as package paths (`x.fbx[direct-file.png]`, `x.gltf[file.png]`,
  `x.glb[image.png]`), readable through `Ar.GetResolver().OpenAsset` → can be copied out for the
  processor, also for textures embedded in glb/fbx.
- Units: glTF authors Y-up, 1 m. FBX authors up axis and `metersPerUnit`, but a Houdini-written FBX
  (FBX ROP, *Convert Units* off by default) says 0.01 while its values are metres: **labels can
  lie**. obj authors neither (the 0.01 USD reports is just the fallback); abc only the up axis.
- A Reference LOP on the source file + USD ROP keeps a reference to the source file: ingest must
  flatten the stage and write real layers.
- SOP side: `hou.Geometry.loadFromFile` reads fbx/obj/abc (with `shop_materialpath`, `name`, `uv`),
  not gltf; the glTF SOP and `hou.hipFile.importFBX` work. Needed only for the PolyReduce proxy.

**Proposed spec text**

- §17.6 External models: drop *(L0)*: "A hython job opens the file through Houdini's USD
  file-format plugins (fbx, gltf, glb, obj, abc; USD as is), flattens it and converts it to Y-up
  metres from its authored `upAxis`/`metersPerUnit` (missing ones count as Y-up metres). Textures,
  also embedded ones, are read through the resolver and go through the processor; each
  `UsdPreviewSurface` material becomes one MaterialX material. Unit labels are often wrong, so the
  ingest entry shows the model's size in metres and the plan has a scale override (**decision
  needed**)."

## 8. Preview scene format (§17.7) — `s08`

**Found**

- A shipped `preview_studio.usda` (1 KB of text: dome + key + rim lights, RenderSettings 512²,
  32 samples) works. Per preview a wrapper layer sublayers it, references the item
  library-relative with its variant under `/preview/item`, and gets a camera that frames the
  bounds (bounds need `pxr` → hython, 0.2 s). husk renders it with `-s /Render/settings`;
  hoiiotool applies the display view over a grey card and writes the JPEG.
- 512² on this Mac: simple model 3–4 s (CPU and XPU), shader ball with a texture set 7 s CPU,
  3–4 s XPU.
- The texture-set material can be written as MaterialX text by core (no HDA cook): a shader ball
  exported once from Houdini's *Test Geometry: Shader Ball* (318 KB USD) is referenced under
  `/preview/ball`.
- Traps: a `RenderVar` without `driver:parameters:aov:name` fails ("Unsupported AOV"), so the scene
  has no custom products and husk's `-o` is used; SOP Import ignored its prim path when exporting
  the ball (prims under `/shaderball`); texture paths in the wrapper resolve relative to the
  wrapper, so it uses library-relative paths and can live in a temp folder; the shader ball's
  UVs are 0–1, not metres, so `size_m` only means metres with the triplanar projection.

**Proposed spec text**

- §17.7: "The preview scenes ship as `src/scheinwerk/resources/library/preview_studio.usda`
  (lights and render settings, text) and `shaderball.usd`. A preview job writes a temporary
  wrapper layer outside the library that sublayers the scene and either references the model
  library-relative with the variant selected, or binds a MaterialX material (written as text, the
  same network `sw_texture_set` builds, triplanar at `size_m`) to the shader ball; a hython step
  adds a camera that frames the bounds. husk renders it (CPU), hoiiotool turns the EXR into the
  JPEG with the display view."

## Decisions (agreed 2026-11-27, all as recommended; written into spec §17)

1. **Extensions.** `.exr` for half/float outputs (colour roles, HDRIs, float data) and `.tx` for
   8/16-bit data, or `.tx` for everything (EXR inside where half/float)? Recommendation: `.exr`/`.tx`
   by container — Nuke and Blender read `.exr` directly, and the name says what's inside.
2. **Thumbnail view.** The config's default view (*Un-tone-mapped*) clips HDRIs. Use
   *ACES 1.0 - SDR Video* when the config has it, else the default view? Or a setting?
   Recommendation: the rule, no new setting.
3. **Model scale override.** A `scale` in the ingest plan, recorded in `version.json` (new JSON
   field). Recommendation: yes.
