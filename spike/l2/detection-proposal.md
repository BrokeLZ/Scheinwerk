# L2 detection and ingest plan: proposal for review

CLAUDE.md asks for the test cases of new parsing rules before they are implemented. These are
the cases for `sw lib detect` (spec §17.5 *Detection*), written against real download names,
plus the places where §17.5 is silent or would get real downloads wrong (marked **Q1–Q5**).
Nothing here is implemented yet.

## 1. Splitting a file name into tokens

Names are split on `_`, `-`, `.`, spaces and lower→Upper case changes; matching ignores case.

| File name | Tokens |
| --- | --- |
| `Metal032_4K-JPG_NormalGL.jpg` | `metal032` `4k` `jpg` `normal` `gl` |
| `rusty_metal_02_nor_gl_4k.exr` | `rusty` `metal` `02` `nor` `gl` `4k` |
| `Aset_rock_rough_M_rgeoU_4K_AmbientOcclusion.jpg` | … `ambient` `occlusion` (read as one role) |
| `oak_Var3_LOD0_Albedo.png` | `oak` `var3` `lod0` `albedo` |

Ignored tokens (not part of the base name): resolutions `1k`…`16k`, `512`…`16384`; format words
`jpg` `jpeg` `png` `exr` `tif` `tiff` `hdr`; `lod<n>`.

## 2. Role per file

Exact token matches (not prefixes, so `Metal032` is not `metal` and `collection` is not `col`):

| Role | Tokens |
| --- | --- |
| `basecolor` | `basecolor`, `base`+`color`, `albedo`, `col`, `color`, `colour` |
| `diffuse` | `diffuse`, `diff` |
| `normal` | `normal`, `nrm`, `nor`, `norm` |
| `roughness` | `rough`, `roughness` |
| `glossiness` | `gloss`, `glossiness` |
| `metalness` | `metal`, `metallic`, `metalness` |
| `specular` | `spec`, `specular` |
| `height` | `disp`, `displacement`, `height` |
| `ao` | `ao`, `occlusion`, `ambient`+`occlusion` |
| `opacity` | `opacity`, `alpha`, `mask` |
| `emission` | `emissive`, `emission` |

**Q1 — several role tokens in one name.** `rusty_metal_02_diff_4k.jpg` has `metal` *and*
`diff`. Proposal: the **last** role token wins (download sites put the role after the name), so
this is `diffuse`, and the base name is everything before it: `rusty_metal_02`.

| File | Role | Base name | Normal convention |
| --- | --- | --- | --- |
| `Metal032_4K-JPG_Color.jpg` | basecolor | `metal032` | |
| `Metal032_4K-JPG_NormalGL.jpg` | normal | `metal032` | GL |
| `Metal032_4K-JPG_NormalDX.jpg` | normal | `metal032` | DX |
| `Metal032_4K-JPG_Displacement.jpg` | height | `metal032` | |
| `rusty_metal_02_diff_4k.jpg` | diffuse | `rusty_metal_02` | |
| `rusty_metal_02_metal_4k.exr` | metalness | `rusty_metal_02` | |
| `rusty_metal_02_nor_dx_4k.exr` | normal | `rusty_metal_02` | DX |
| `Aset_rock_4K_Albedo.jpg` | basecolor | `aset_rock` | |
| `Aset_rock_4K_Normal.jpg` | normal | `aset_rock` | (none: GUI asks, CLI assumes GL and warns) |
| `Aset_rock_4K_Cavity.jpg` | unknown (listed, can be assigned or skipped) | `aset_rock` | |
| `Metal032.png`, `preview.jpg` | unknown | | |

**Q2 — packed maps.** Poly Haven ships `rusty_metal_02_arm_4k.jpg` (AO in R, roughness in G,
metal in B); Unreal-style sets have `ORM`. §17.5 has no packed roles. Options:
(a) `arm`/`orm` tokens unpack into `ao`/`roughness`/`metalness` by channel, used only for the
roles the set doesn't have as separate files: a new recipe field `channel` in `version.json`
`files`; (b) not supported in v1: listed as unknown. Recommendation: (a), Poly Haven often has
no separate metal map.

## 3. Files → entries

1. Every folder is grouped on its own (subfolders recursively). Zips are extracted to a temporary
   folder first and grouped like a folder.
2. Within a folder, images are grouped by base name (after dropping role, resolution, format,
   variant and LOD tokens). UDIM tiles `name.1001.ext` belong to one map.
3. A group with at least two known roles → one `texture_set` entry.
4. A single float image with a 2:1 aspect → `hdri`. Any other single image → `texture` (one
   channel: data, else colour).
5. Model files → one `model` entry each (L4; until then listed as *needs L4*).
6. Variant tokens `var<n>`/`variation<n>`, in the file name or as a folder name (`Var1/`), merge
   groups that are the same otherwise into one entry with variants `var01`, `var02`, …

| Dropped | Entries |
| --- | --- |
| ambientCG `Metal032_4K-JPG/` (Color, NormalGL, NormalDX, Roughness, Metalness, Displacement, `Metal032.png`, `.usdc`, `.mtlx`) | 1 texture_set `Metal032`. NormalGL used, NormalDX skipped (Q3). Preview, `.usdc`, `.mtlx` listed as not used. |
| a folder with 20 such folders | 20 entries |
| Poly Haven `rusty_metal_02_{diff,rough,metal,nor_gl,disp,arm}_4k.*` | 1 texture_set `Rusty Metal 02` |
| `kloppenheim_06_4k.exr` + `kloppenheim_06_puresky_4k.exr` (both 8192×4096 float) | 2 hdri entries (`puresky` is not a variant token; merging into one item is chosen in the entry: *target: existing item, as variant*) |
| `sky_8k.jpg` 8192×4096 uint8 | 1 texture (not float, so not an HDRI) |
| Megascans plant: `Var1/…_Albedo.png`, `Var1/…_Normal.png`, `Var2/…` | 1 texture_set (or model later) with variants `var01`, `var02` |
| `oak_Var1_Albedo.png`, `oak_Var2_Albedo.png` (no other roles) | 1 texture with variants `var01`, `var02` |
| `brick.png` (one channel) | 1 texture, data |
| `photo.webp` | listed as unsupported |

**Q3 — a set with both NormalGL and NormalDX.** Proposal: use GL, skip DX (listed as skipped).

## 4. Workflow

**Q4 — `diffuse` in metal/rough sets.** Poly Haven names its basecolor `diff` and usually has
no metal map. §17.5 as written would call `brick_wall_{diff,rough,nor_gl}` a **spec/gloss** set
(diffuse, no metalness). Proposal: a set is `spec_gloss` only when it has `specular` or
`glossiness` and neither `metalness` nor `roughness`; otherwise it is `metal_rough` and a
`diffuse` file is its `basecolor`, and `spec` is `specular_level`.

| Roles found | Workflow | Notes |
| --- | --- | --- |
| basecolor, normal, roughness, metalness | metal_rough | |
| diffuse, normal, roughness | metal_rough | diffuse → basecolor |
| diffuse, specular, glossiness, normal | spec_gloss | asked to confirm; threshold 0.2 |
| diffuse, specular, roughness | metal_rough | specular → specular_level |
| albedo, gloss, normal | spec_gloss | gloss alone (no specular): metalness 0 everywhere |

## 5. Colour spaces and defaults

| Map | `from_space` |
| --- | --- |
| integer colour (basecolor, diffuse, specular, emission, colour texture) | the config's sRGB texture space |
| float colour (EXR basecolor, HDRI) | linear Rec.709 |
| data roles | raw |

## 6. Display names

| From | Suggested name |
| --- | --- |
| `Rusty_Metal_02_4K` | `Rusty Metal 02` |
| `rusty_metal_02` | `Rusty Metal 02` |
| `Metal032_4K-JPG` | `Metal032` |
| `kloppenheim_06_puresky_4k` | `Kloppenheim 06 Puresky` |
| `oak_Var3` | `Oak` |

## 7. The ingest plan (JSON)

**Q5 — the plan format.** §17.10 says a plan is "the JSON form of one ingest entry" but defines
no fields. Proposal (absolute source paths are fine: a plan is runtime data, never stored in the
library):

```json
{
  "schema": 1,
  "type": "texture_set",
  "name": "Rusty Metal 02",
  "target": { "item": null, "variant": null },
  "variants": {
    "main": [
      { "path": "/Users/me/Downloads/rusty_metal_02_diff_4k.jpg", "role": "basecolor",
        "color_space": "sRGB - Texture", "flip_green": false, "invert": false, "channel": null },
      { "path": "/Users/me/Downloads/rusty_metal_02_nor_dx_4k.exr", "role": "normal",
        "color_space": "raw", "flip_green": true, "invert": false, "channel": null }
    ]
  },
  "skipped": ["/Users/me/Downloads/rusty_metal_02.blend"],
  "workflow": "metal_rough",
  "metal_threshold": null,
  "size_m": null,
  "displacement": null,
  "scale": null,
  "categories": [], "tags": [], "credits": "", "license": "", "source_url": "",
  "status": "ready",
  "messages": []
}
```

- `target.item` null = a new item; an item id = a new version of it. `target.variant`: the
  variant name when adding/changing one variant of an existing item (the item's other variants
  are kept from its latest version).
- UDIM maps: `path` is the pattern `…/name.<UDIM>.png`.
- `status`: `ready`, `needs_input` (with `messages` saying what), `warning` (e.g. the same files
  were ingested before, by `sha256`). `sw lib ingest --plan` refuses `needs_input`.
- `size_m` is read from ambientCG/Poly Haven metadata files only if one is next to the maps
  (L2 reads none; it stays empty unless given with `--size`).
