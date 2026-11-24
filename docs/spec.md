# Scheinwerk — Specification

Status: v1 spec · Last updated: 2026-11-24
This file is the single source of truth for Scheinwerk. Code serves the spec. If a decision changes, change this file in the same commit.

---

## 1. Purpose and scope

Scheinwerk is a lightweight, file-based VFX pipeline for one artist working on personal projects on macOS and Windows.

It is:

- a set of **on-disk conventions** (folder layout, naming, versioning),
- a **stdlib-only Python core** that knows those conventions,
- a **CLI** (`sw`) and a **PySide6 GUI** built on the core,
- thin, optional **DCC integrations** (Houdini first, then Nuke, then Blender).

Any DCC can take part with no plugin at all: the GUI/CLI hands out the next path, and you save or export through the DCC's own dialog.

### Non-goals (v1)

No database or server. No multi-user handling, locking or permissions. No task status, assignments or scheduling. No review/annotation tool or built-in media player. No custom USD asset resolver, value clips, asset assemblies or per-shot asset pinning (shots always use an asset's current versions; renders record what they used, §8.3). No symlinks. No per-file metadata for workfiles. No template-editor UI. No file watchers. No ORM layer over the folders.

---

## 2. Non-negotiable principles

1. **A path is the context.** Every path inside a project can be parsed into project / entity / department / task / product / version. No tool needs stored state to know where it is.
2. **The folder tree is the truth.** JSON holds only what a path cannot express. Delete a folder and its data goes with it. Never cache tree state in JSON.
3. **The project root is found, never stored.** Walk up from any path until a folder contains `scheinwerk.json`.
4. **Nothing persisted inside a project contains an absolute path.** Persisted paths are root-relative POSIX strings (`/` separators). The only exception is machine-local user settings (§8.4).
5. **The core uses the Python standard library only.** No third-party imports, no Qt, no DCC modules. It must import inside hython, Nuke, Blender and plain Python 3.11.
6. **Plugins are conveniences, never requirements.** Every plugin action must also be possible through the GUI or CLI.
7. **Convention over configuration.** One opinionated default layout, overridable per project through `scheinwerk.json`. No UI for editing templates.
8. **Minimal over clever.** Before adding a dependency, a JSON field or a new concept, ask whether a naming convention or a CLI command would do.

---

## 3. Glossary

| Term | Meaning |
| --- | --- |
| Project | A folder containing `scheinwerk.json`. |
| Entity | Something work is done for: an **asset**, a **shot**, or a **sequence** (via `_seq`). |
| Category | Optional single grouping level for assets (`char`, `prop`, `env`). Not an entity. |
| Department | A discipline folder under an entity (`mdl`, `lgt`, …). |
| Task | A folder under a department. Every department has a default task `main`. |
| Workfile | A versioned DCC scene file inside `<task>/work/`. |
| Product | A named, versioned export at entity level: `publish/<product>/v###/`. |
| USD layer | A versioned USD product under `publish/_usd/<layer>/v###/`, with a pointer layer. |
| Pointer layer | A tiny unversioned `.usd` file that sublayers one specific version. |
| Media | Named, versioned images/movies for viewing: `media/<name>/v###/`. |
| Version | A `v###` folder (products/media) or the `v###` in a workfile name. |
| Finalize | Writing `version.json` (and, for USD, updating the pointer) after an export. Optional. |
| Ingest | Copying an external file into the pipeline as the next version. |

---

## 4. On-disk layout

```text
<project>/
├── scheinwerk.json                       # marker + project config (only required file)
├── assets/
│   └── [<category>/]                     # optional, one level max
│       └── <asset>/
│           ├── entity.json               # written on create; marks an asset (§6.3)
│           ├── <dept>/
│           │   └── <task>/
│           │       ├── work/             # workfiles, all DCCs, flat
│           │       └── cache/            # WIP caches, free-form, never referenced downstream
│           ├── publish/
│           │   ├── _usd/
│           │   │   ├── <asset>.usd       # asset entry layer: the component (§9.2)
│           │   │   ├── payload.usd       # its payload: the asset's layers, mtl over geo
│           │   │   └── <layer>/          # geo, mtl (§9.3)
│           │   │       ├── <layer>.usd   # pointer layer
│           │   │       └── v###/         # version folders
│           │   └── <product>/v###/       # any non-USD product, free name
│           └── media/<name>/v###/
├── shots/
│   └── <seq>/
│       ├── _seq/                         # optional sequence-level entity
│       │   ├── <dept>/<task>/work|cache/
│       │   ├── publish/                  # only for genuinely sequence-wide products
│       │   │   └── _usd/
│       │   │       └── <seq>.usd         # sequence root layer: its layers, then structure
│       │   └── media/
│       └── <shot>/                       # <seq>_<nnnn>, unique project-wide
│           ├── entity.json               # frame range
│           ├── <dept>/<task>/work|cache/
│           ├── publish/
│           │   ├── _usd/
│           │   │   ├── <shot>.usd        # shot root layer: its layers, then the sequence's (or structure)
│           │   │   └── <layer>/          # layout, anim, fx, lgt: pointer + v###/
│           │   └── <product>/v###/
│           └── media/<name>/v###/
├── shared/                               # project-wide: HDAs, templates, hooks, LUTs
│   ├── hooks/
│   ├── templates/                        # optional empty workfile templates: empty.<ext>
│   └── usd/
│       └── structure.usd                 # the shot hierarchy (§9.2), written by core
└── io/                                   # in/ and out/: plates, references, deliveries
```

### 4.1 Reserved names

- Any folder name starting with `_` is pipeline-reserved. Defined: `_usd`, `_seq`.
- Reserved words (cannot be used as entity, category, department, task, product or media names): `publish`, `media`, `work`, `cache`, `assets`, `shots`, `shared`, `io`, `entity`.
- Asset and category names must not equal any department name in the project template. This keeps parsing of the optional category unambiguous (§6.2).

### 4.2 Ignored files

Scans skip entries that match `scheinwerk.json → ignore`. Defaults: `backup`, `*.blend1`, `*.autosave`, `.DS_Store`, `._*`, `Thumbs.db`, `@eaDir`, `*~`. Synology conflict copies (names containing `_Conflict` / `Conflict`) are not ignored. `sw doctor` reports them.

---

## 5. Naming rules

### 5.1 Characters

- Names use lowercase `a-z`, digits and `_`. Regex for a name: `^[a-z0-9][a-z0-9_]*$`.
- No spaces, umlauts, `-` or uppercase. No leading `_` (reserved).
- Asset names are unique project-wide (across categories). Sequence names are unique. Shot names are unique project-wide.

### 5.2 Entity name patterns (defaults, overridable)

| Entity | Default regex | Example |
| --- | --- | --- |
| Category | name regex | `char` |
| Asset | name regex | `hero` |
| Sequence | `^[a-z]+[0-9]+$` | `sq010` |
| Shot | `^{seq}_[0-9]{4}$` (must start with its sequence) | `sq010_0010` |

When the sequence isn't known yet (`sw new shot sq010_0010` creates it), a shot name must match `<sequence regex>_[0-9]{4}` and the sequence is the part before the last `_`.

Name suggestions (the GUI's `-`/`+` buttons) count in steps of 10. Each click moves the number at the end of the field to the next or previous multiple of 10, keeping prefix and digit count and never going below 10 (`sq010` → `sq020` → `sq030`; `0040` → `0030`); stepping doesn't skip names that already exist. On an empty field (or one without a number) either button fills in the next free name: the next sequence is `sq` + the next multiple of 10 above the highest existing `sq###` (`sq010`, `sq020`, …; other sequence names are ignored); the next shot is the next multiple of 10 above the highest `<seq>_####` in that sequence (`sq010_0010`, `sq010_0020`, …). When creating an asset, the categories `char`, `prop` and `env` are always offered, followed by any other existing categories.

### 5.3 File and folder templates

| Thing | Template | Example |
| --- | --- | --- |
| Workfile | `{entity}_{dept}_{task}_v{version:03d}.{ext}` | `sq010_0010_lgt_main_v012.hip` |
| Sequence workfile | same; `entity` = sequence name | `sq010_lgt_main_v007.hip` |
| Product version folder | `publish/{product}/v{version:03d}/` | `publish/pants_drape_base/v001/` |
| USD version folder | `publish/_usd/{layer}/v{version:03d}/` | `publish/_usd/geo/v003/` |
| USD pointer | `publish/_usd/{layer}/{layer}.usd` | `publish/_usd/geo/geo.usd` |
| Product file (recommended) | `{entity}_{product}_v{version:03d}[.{frame:04d}].{ext}` | `hero_pants_drape_base_v001.abc` |
| Media version folder | `media/{media}/v{version:03d}/` | `media/render_beauty/v004/` |
| Media file (recommended) | `{entity}_{media}_v{version:03d}.{frame:04d}.{ext}` | `sq010_0010_render_beauty_v004.1001.exr` |

- Workfile names are **enforced** for files Scheinwerk creates. A file in `work/` is *managed* only if its whole name matches the template filled in from its **folders** (entity, dept, task), with a lowercase `[a-z0-9]+` extension. Anything else is *unmanaged*: a different prefix, a suffix like `_final`, an uppercase `.HIP`, a nested subfolder. Unmanaged files are shown, never hidden or touched.
- Names of files **inside** a version folder are recommended, not enforced. Everything in a version folder belongs to that version.
- Copied next-version paths carry no extension: the DCC adds it (and any frame number) when saving or exporting. Workfiles: `…/work/hero_mdl_main_v004` (`Task.next_workfile()`, `sw next` without `--ext`). Products, USD layers and media: the reserved version folder plus the recommended name without frame and extension, `…/base_model/v002/hero_base_model_v002` (`Product.next_version_path()`, `sw next-publish --file`).
- No comments in filenames.
- Versions are written with 3 digits. Readers accept `v[0-9]{3,}` (ASCII digits only, v1000+ keeps working). Uppercase `V001` is not a version.
- Frames are 4-digit and start at 1001 by default.

### 5.4 Versioning

| What | Counter scope | Next version |
| --- | --- | --- |
| Workfiles | one per task, shared across all extensions/DCCs | max version of all managed files in `work/` + 1 |
| Products, USD layers | one per product / layer | max `v###` folder (empty ones included) + 1 |
| Media | one per media name, independent of workfiles | max `v###` folder (empty ones included) + 1 |

- "Latest" = highest version number. For USD layers, the *current* version is the one the pointer references, which can differ after "Set as latest".
- Creating a version folder uses `mkdir(exist_ok=False)`. On collision, increment and retry, so two DCCs exporting at once can't share a folder.
- An empty version folder (no files besides `version.json` and ignored files) is ignored by "latest" lookups, but its number stays taken.

---

## 6. Parsing (path → context)

### 6.1 Context object

```python
@dataclass(frozen=True)
class Context:
    root: Path                    # absolute, runtime only
    entity_type: str              # "asset" | "shot" | "sequence"
    entity: str                   # "hero" | "sq010_0010" | "sq010"
    category: str | None          # assets only
    sequence: str | None          # shots and sequences
    dept: str | None
    task: str | None
    area: str | None              # "work" | "cache" | "publish" | "media"
    product: str | None           # product, USD layer or media name
    usd: bool                     # True if under publish/_usd/
    version: int | None
    ext: str | None
```

### 6.2 Rules

1. Find the root (§2.3). If none is found, `Context.from_path()` returns `None`. Relative paths are taken from the current directory; symlinks are not resolved.
2. Split the root-relative path into parts. A path inside the project but not inside an entity (the root, `scheinwerk.json`, `assets/`, `shots/`, `shared/…`, `io/…`) raises `ParseError`.
3. `assets/…` (optional category). Checked in this order:
   1. Area keyword position (deep paths). If `parts[2]` is `publish`, `media` or `entity.json`, or `parts[4]` is `work` or `cache`, there is no category. If `parts[3]` is one of the first three, or `parts[5]` is `work` or `cache`, then `parts[1]` is the category. These words are reserved, so this works for custom departments too.
   2. Otherwise (short paths): if there is no `parts[2]`, or it is a department name from the project template (any entity type), there is no category. Otherwise `parts[1]` is the category and `parts[2]` the asset.

   Known limit: a short path under an asset with no category whose third part is a *custom* department (`assets/hero/groom`) reads as category `hero`, asset `groom`. Deep paths into that department parse correctly.
4. `shots/<seq>/_seq/…` → entity_type `sequence`, entity = `<seq>`. The sequence folder `shots/<seq>` itself is the same sequence, so its `path()` is `shots/<seq>/_seq`. `shots/<seq>/<shot>/…` → entity_type `shot`. Shot names are not validated while parsing (`sw doctor` reports them).
5. After the entity: `<dept>/<task>/work|cache/…` or `publish/[_usd/]<name>/v###/…` or `media/<name>/v###/…`. Folders that are none of these are kept as far as they are recognisable (an unknown folder in a task gives area `None`, a non-`v###` folder in a product gives version `None`).
6. Version and extension:
   - Workfiles: from a managed filename (§5.3). An unmanaged file in `work/` has version `None` and its own extension, so "unmanaged" is the same as `version is None`.
   - Products/media: version from the `v###` folder, extension from the last suffix of a file inside it (`x.1001.bgeo.sc` → `sc`).
   - USD: the pointer `_usd/<layer>/<layer>.usd` and the entry/root layer `_usd/<entity>.usd` have version `None` and ext `usd`.
   - Nothing below `cache/` is parsed.
7. Context is read from **folders**. The filename prefix is redundant and is not trusted for context. This is why product names may contain underscores.
8. Parsing works for paths that don't exist yet (needed for "next version" paths).

Round-trip requirement: `Context.from_path(p).path() == p` for every path the core generates. This is the main test suite. A file inside a version folder can't round-trip (the context doesn't hold its name): its `path()` is the version folder. `v0001` parses as 1 and comes back as `v001`.

### 6.3 Scanning (listing what exists)

Listings come from scanning folders every time. Ignored entries (§4.2) are skipped everywhere; everything else is shown.

- **Assets and categories.** A folder directly under `assets/` is an asset if it contains `entity.json`, `publish/`, `media/` or a department from the template. Otherwise it is a category (an empty folder too, e.g. a fresh "New category"), and every folder inside it is an asset. Creating an asset always writes `entity.json`, so assets made by Scheinwerk are never mistaken for categories.
- **Sequences** are the folders under `shots/`; **shots** are the folders under a sequence except `_seq`.
- **Departments** of an entity: its folders except `publish/` and `media/`. **Tasks**: the folders in a department.
- **Order.** Assets by (category, name) with uncategorised ones first; sequences and shots by name; departments and tasks in template order, then the custom ones A–Z.
- **Flags.** Entities, departments and tasks carry `valid` (name passes §5) and departments/tasks `custom` (not in the template). Invalid names are listed, never hidden.
- **Workfiles.** Managed files in `work/`, newest first (same version: by extension). Everything else in `work/`, folders included, is listed as unmanaged.
- **Versions.** `v###` folders, newest first. Other folders in a product are not versions.

---

## 7. Paths in files and the environment

### 7.1 Three kinds of relative path

| Kind | Used in | Form |
| --- | --- | --- |
| Root-relative | all JSON, CLI `--relative`, GUI "copy relative path" | `shots/sq010/sq010_0010/publish/fx_pyro/v002` |
| File-relative | USD asset paths, Blender `//` | `./v003/hero_geo_v003.usd`, `../../../../assets/char/hero/publish/_usd/hero.usd` |
| Env-relative | Houdini parms, Nuke Read/Write | `$SW_ROOT/shots/...` (Houdini also: `$JOB`) |

Plugins write file-relative paths where the format supports it (USD, Blender) and env-relative paths otherwise. Nothing persisted ever contains a drive letter, `/Volumes/…`, `/Users/…` or a UNC path.

### 7.2 Environment variables

Set by integrations from the **currently opened file's path**, never from stored state. They are runtime values, so they may be absolute.

| Variable | Value |
| --- | --- |
| `SW_ROOT` | project root |
| `JOB` | project root (Houdini only) |
| `SW_ENTITY_TYPE` | `asset` / `shot` / `sequence` |
| `SW_ENTITY` | entity name |
| `SW_SEQ` | sequence name (shots, sequences) |
| `SW_DEPT`, `SW_TASK` | department, task |
| `SW_TASK_DIR` | absolute task folder |
| `SW_CACHE` | `<task>/cache` |
| `SW_ENTITY_DIR` | absolute entity folder |

`env_for` always returns every variable except `JOB` (the Houdini adapter adds that one). A variable that doesn't apply is `""`, so an integration overwrites values left over from the previous file. Paths use `/` on every OS: Houdini, Nuke and Blender accept them, and they need no escaping in expressions.

### 7.3 OCIO

One OCIO config for all projects, configured per machine (the `OCIO` env var in the OS or the Houdini package). Scheinwerk does not manage OCIO in v1.

---

## 8. JSON files

All JSON is UTF-8 with LF line endings, indented with 2 spaces and written atomically (write `<name>.tmp` in the same folder, then `os.replace`). A write whose content is identical to the file on disk is skipped, so nothing re-syncs needlessly. The same applies to pointer and root layers. Every file has an integer `schema`. Unknown keys are preserved on rewrite.

### 8.1 `scheinwerk.json` (project root, required)

```json
{
  "schema": 1,
  "name": "myproject",
  "fps": 24,
  "resolution": [1920, 1080],
  "frame_start": 1001,
  "departments": {
    "asset":    { "mdl": ["main"], "tex": ["main"], "lookdev": ["main"], "rig": ["main"], "fx": ["main"] },
    "sequence": { "layout": ["main"], "lgt": ["main"] },
    "shot":     { "layout": ["main"], "anim": ["main"], "fx": ["main"], "lgt": ["main"], "comp": ["main"] }
  },
  "usd_layer_order": ["lgt", "fx", "anim", "layout"],
  "ignore": ["backup", "*.blend1", "*.autosave", ".DS_Store", "._*", "Thumbs.db", "@eaDir", "*~"],
  "templates": {}
}
```

- `departments` lists what the GUI and CLI offer when creating. Departments/tasks that exist on disk but not in the template are still shown, marked as *custom*.
- `usd_layer_order`: strongest first, used for the shot and sequence root layers (§9.2). Asset layers have a fixed order instead (§9.3).
- `templates`: optional overrides of §5.2/§5.3 patterns, keyed by template name. Empty = defaults.

### 8.2 `entity.json` (entity folder, optional)

```json
{ "schema": 1, "frames": [1001, 1096] }
```

Optional overrides: `fps`, `resolution`. Sequences have no `entity.json`; their range is derived from their shots (lowest start to highest end; shots without a range are skipped).

Creating an asset writes `{ "schema": 1 }`; creating a shot writes the same plus `frames` when a range is given. For assets the file mainly marks the folder as an asset (§6.3). Hand-made entity folders without it still work.

### 8.3 `version.json` (inside a version folder, optional, written on finalize)

```json
{
  "schema": 1,
  "source": "shots/sq010/_seq/lgt/main/work/sq010_lgt_main_v007.hip",
  "dept": "lgt",
  "task": "main",
  "dcc": "houdini",
  "user": "lorenz",
  "created": "2026-11-22T11:40:00+01:00",
  "comment": "",
  "usd_files": ["assets/char/hero/publish/_usd/geo/v003/hero_geo_v003.usd"]
}
```

All fields are optional. Readers must never require this file; a missing or broken file reads as no info.

- `source` is root-relative; a source outside the project is refused. `dept` and `task` come from the source path.
- `usd_files` (renders only): the published USD files the render's composed stage used, root-relative and sorted: every layer in a `v###` folder under `publish/` (pointer, entry and root layers are left out, they float). The integration collects them (§13.2). Shots follow the current versions of everything, so this is the record of what a render was made from; to reproduce it, set those versions as current.
- Re-finalizing (e.g. "Edit comment") always sets `comment`, sets `source`/`dept`/`task`/`dcc`/`usd_files` only when given, and keeps `user`, `created` and unknown keys.

### 8.4 User settings (machine-local, never in a project)

Location: `~/Library/Application Support/Scheinwerk/settings.json` (macOS), `%APPDATA%\Scheinwerk\settings.json` (Windows). Absolute paths are allowed here because the file never leaves the machine.

```json
{
  "schema": 1,
  "recent_projects": ["/Users/lorenz/SynologyDrive/projects/myproject"],
  "dcc": {
    "hip":   { "name": "Houdini", "exe": "/Applications/Houdini/Houdini21.0.xxx/Houdini FX 21.0.xxx.app" },
    "nk":    { "name": "Nuke",    "exe": "..." },
    "blend": { "name": "Blender", "exe": "..." }
  },
  "gui": { "last_view": "scenefiles", "geometry": null }
}
```

An extension with no entry opens with the OS default application. `exe` is an `.app` bundle on macOS and an executable on Windows.

Missing keys are filled from these defaults when reading; a missing or broken file reads as the defaults. `recent_projects` holds at most 10 entries, newest first. The GUI writes `last_view` and `geometry` (`[x, y, w, h]`) when its window closes. The folder also holds user hooks (§14).

---

## 9. Publishing

### 9.1 Generic product / media

1. `next_publish(entity, name)` / `next_media(entity, name)` → creates and returns `…/<name>/v###/` (§5.4).
2. The DCC (or the user via its own dialog) writes files into it.
3. Optional `finalize(version_dir, source=…, comment=…)` → writes `version.json`.

### 9.2 USD layer

1. `next_usd(entity, layer)` → `publish/_usd/<layer>/v###/`.
2. Export (Houdini USD ROP with the *Use Relative Paths* output processor).
3. `finalize(…)` → writes `version.json`, then atomically rewrites the pointer layer, then the entry/root layer. Nothing is written if the main file can't be determined.
4. The entry/root layers are rewritten on every finalize/set-current, so they exist from the first publish and pick up new layer names. Identical content is not rewritten (§8). Each lists the entity's layers that have a pointer (`./<layer>/<layer>.usd`):
   - **Asset**: two files. `payload.usd` sublayers the asset's layers in the asset order (§9.3). `<asset>.usd` is the *component*: one prim `/<asset>` with `kind = "component"`, `assetInfo` (name) and a payload to `./payload.usd`, and `defaultPrim` = the asset. Referencing an asset therefore loads nothing heavy until its payload is loaded.
   - **Shot**: `<shot>.usd` sublayers the shot's layers (`usd_layer_order`, then A–Z), then as the weakest the sequence root layer `../../../_seq/publish/_usd/<seq>.usd` when it exists, else the structure layer. The sequence root layer ends with the structure layer, so a shot's stack holds it exactly once. No `defaultPrim`.
   - **Sequence**: `_seq/publish/_usd/<seq>.usd` sublayers the sequence's own layers like a shot, then the structure layer. When it is created, the root layers of all the sequence's shots are rewritten so they include it.
   - **Structure** (`shared/usd/structure.usd`, one per project): the shot hierarchy, so no department layer has to define it and publishes can come from any file in any order. Core writes it when the project is created, and in older projects whenever a root layer is written or *Shot Start* (§13.2) loads it and the file is missing. It is never overwritten and not versioned. A project may change it, but the HDA defaults (§13.2) assume this convention. Everything spatial lives under one transformable root, `/world`, so a transform on it moves geometry, cameras and lights together; render settings are not spatial and stay outside. All of them are Xforms. Groups that hold assets or fx have kind `group`, so an asset below them stays a model; cameras and lights hold no models and have no kind. Not Scopes: Houdini's Camera and Light LOPs create a missing parent as an Xform, and that layer's type would win over the structure layer's, so the prim's type would depend on which layers are loaded. Xforms also let a department transform all cameras or lights at once:

     | Prim | Type, kind | Filled by |
     | --- | --- | --- |
     | `/world` | Xform, `group` | |
     | `/world/chars` | Xform, `group` | layout: assets of category `char` |
     | `/world/props` | Xform, `group` | layout: assets of category `prop`, any other category and assets without one |
     | `/world/env` | Xform, `group` | layout: assets of category `env`, set dressing |
     | `/world/fx` | Xform, `group` | fx |
     | `/world/cameras` | Xform | layout, anim |
     | `/world/lights` | Xform | lighting |
     | `/Render` | Scope | lighting: render settings and products (Karma's default location) |
5. **Time metadata.** Published layers carry the fps of the scene that wrote them (Houdini's USD ROP always writes it), and the integration keeps the scene at the entity's fps (§13.2 item 2). Every pointer, entry, payload and root layer core writes carries `framesPerSecond` and `timeCodesPerSecond` = the entity's fps (its `entity.json` override, else the project's; written like the JSON value: `24`, `23.976`). USD rescales a sublayer, reference or payload whose `timeCodesPerSecond` differs from the layer that includes it, and a layer without one counts as 24, so without this a 25 fps publish would be retimed (keys at 1001 land at 961). Shot root layers also carry `startTimeCode`/`endTimeCode` = the shot's frames (when set), so usdview and husk open on the right range; sequence root layers carry no range (it is derived from the shots and would go stale). `set_frames` rewrites the shot's root layer if it exists. A changed fps reaches a layer the next time core rewrites it (publish, set-current, `set_frames`). The structure layer has no time metadata: it holds no time samples.
6. **References stay in `publish/`.** Everything a published layer points at (sublayers, references, payloads, textures, volumes, caches) lives under a `publish/` folder: in the layer's own version folder, in a version of a product or another layer, or another entity's entry/root layer or pointer. Never under `work/` or `cache/`: those change, and `cache/` is not synced (§9.5), so the published layer would change or break on the other machine. Heavy per-frame data that belongs to one layer (e.g. the VDBs of an fx layer) goes into that layer's version folder next to the main file (`{entity}_{layer}_v###.####.vdb`); data several layers or entities use goes into a product (`publish/<product>/v###/`). `sw doctor` reports violations (§11).
7. **Known limit:** published layers reach other entities by file-relative paths, so moving an asset to another category, or renaming an entity, after it is referenced breaks those paths (a rename tool may come later, §16).

Pointer layer format (ASCII content in a `.usd` file, written as plain text by the core, no `pxr` needed):

```text
#usda 1.0
(
    defaultPrim = "hero"
    framesPerSecond = 24
    timeCodesPerSecond = 24
    subLayers = [@./v003/hero_geo_v003.usd@]
)
```

Asset pointers have `defaultPrim` = the asset name: without it, references to the pointer fail. Shot and sequence pointers have none (they are sublayered, and the entity is not a prim). Layer paths must be file-relative (`./` or `../`); anything else is refused.

The pointer targets the main USD file (`.usd`, `.usda`, `.usdc`) at the top of the version folder: the only one if there is one, else the one with the recommended name `{entity}_{layer}_v###`, else `main_file` must be given (`finalize` and `set_current` both take it).

Entry/root layer formats (strongest first; with no layers: `subLayers = []`). Asset entry layer `hero.usd` and its payload `payload.usd`:

```text
#usda 1.0
(
    defaultPrim = "hero"
    framesPerSecond = 24
    timeCodesPerSecond = 24
)

def Xform "hero" (
    kind = "component"
    assetInfo = {string name = "hero"}
    payload = @./payload.usd@</hero>
)
{
}
```

```text
#usda 1.0
(
    framesPerSecond = 24
    timeCodesPerSecond = 24
    subLayers = [
        @./mtl/mtl.usd@,
        @./geo/geo.usd@
    ]
)
```

Shot root layer `sq010_0010.usd` (sequence and shot layers are sublayered, not referenced: they share the shot's namespace). Without a sequence root layer, its last entry is the structure layer `@../../../../../shared/usd/structure.usd@`:

```text
#usda 1.0
(
    framesPerSecond = 24
    timeCodesPerSecond = 24
    startTimeCode = 1001
    endTimeCode = 1096
    subLayers = [
        @./lgt/lgt.usd@,
        @./layout/layout.usd@,
        @../../../_seq/publish/_usd/sq010.usd@
    ]
)
```

Sequence root layer `sq010.usd`:

```text
#usda 1.0
(
    framesPerSecond = 24
    timeCodesPerSecond = 24
    subLayers = [
        @./lgt/lgt.usd@,
        @../../../../../shared/usd/structure.usd@
    ]
)
```

Structure layer `shared/usd/structure.usd`:

```text
#usda 1.0

def Xform "world" (
    kind = "group"
)
{
    def Xform "chars" (
        kind = "group"
    )
    {
    }

    def Xform "props" (
        kind = "group"
    )
    {
    }

    def Xform "env" (
        kind = "group"
    )
    {
    }

    def Xform "fx" (
        kind = "group"
    )
    {
    }

    def Xform "cameras"
    {
    }

    def Xform "lights"
    {
    }
}

def Scope "Render"
{
}
```

`payload.usd` parses like the entry layer (§6.2: `usd`, no product, ext `usd`) and is not round-trippable; it is always written by path. The structure layer is outside any entity (§6.2 rule 2).

"Set as latest" on any USD version rewrites the pointer to that version. That is the only form of pinning/rollback.

### 9.3 Asset layers (roles, hierarchy, variants)

An asset is built from two layers, published and versioned separately:

| Layer | Department | Holds | Prims | Variant set (convention) |
| --- | --- | --- | --- | --- |
| `geo` | modelling (also rigs, grooms) | geometry, render and proxy | `/<asset>/geo/render`, `/<asset>/geo/proxy` (with purposes) | `model` |
| `mtl` | lookdev | materials and bindings | `/<asset>/mtl/…`, bindings as overs on `/<asset>/geo/…` | `look` |

- **Order** in `payload.usd`: `mtl`, then `geo`, then any other asset layer A–Z. Other names are allowed but get no conventions.
- **Hierarchy:** everything an asset layer authors lives under `/<asset>`. Variant sets sit on `/<asset>`. The component prim's `kind` and `payload` come only from the entry layer. The skeleton (`/<asset>/geo/render`, `/<asset>/geo/proxy`, `/<asset>/mtl`) is built by *Asset Start* (§13.2) at the top of the scene and is therefore published in `geo`, the first layer; `mtl` adds to it.
- **Bindings** go on `/<asset>/geo/render` (or a group above the meshes), not on single meshes, where the materials allow it: bindings are inherited, so model variants that rename or add meshes keep their materials.
- **Textures** are a product of the asset (conventionally `textures`: `publish/textures/v###/`, written via *Copy next version path* or ingested), and the `mtl` layer references them there (§9.2 item 6), never in `tex/<task>/work/`.
- **One scene, several layers:** an asset is usually built in one scene: geometry, then *Publish USD* `geo`, then materials, then *Publish USD* `mtl`. Each publish node ends with a Layer Break (§13.2), so the `mtl` layer holds only what was added after the `geo` publish.
- **Variants** are authored by the user in the layer before publishing (in Houdini e.g. with *Add Variant* LOPs); Scheinwerk never writes them. Convention: one variant set per layer, named `model` (`geo`) or `look` (`mtl`), on `/<asset>`. Other names work too; nothing checks them. Variant names and the default selection are up to the user.
- **Variants live inside the payload.** A stage that hasn't loaded an asset's payload doesn't show its variant sets (variant menus are empty); a selection authored on the referencing prim still applies once the payload loads. Houdini loads payloads by default.
- **Prim types:** `/<asset>` is an Xform, the only transformable prim of the skeleton; `geo`, `render`, `proxy` and `mtl` are Scopes (they carry purpose, and transforms pass through them).
- **No nesting:** an asset never contains other assets (no nested components, no assemblies). An environment built from props is set-dressed in a shot's `layout` layer under `/world/env`, or for a whole sequence in the `_seq` `layout` layer.
- Shots reference `<asset>.usd` (the component) and choose variants with the stage's own variant selection.

### 9.4 Ingest

`ingest(files, target)` copies files into the next workfile version (renamed to the template) or into the next product/media version folder (names kept). It never moves or deletes the originals.

- Target a task: each file becomes its own next version, in the order given (`a.hip`, `b.hip` → v004, v005). The extension is lowercased (`scene.HIP` → `….hip`). A file without an extension is refused.
- Target a product or media name: all files go into one new version folder. Two files with the same name are refused.
- Only files, no folders. Everything is checked before the first copy.

### 9.5 Sync safety (Synology Drive)

- Pointer layers and `version.json` are written last, atomically, so on the machine that publishes a pointer never names an incomplete version.
- Sync doesn't keep that order: Synology Drive may upload a small pointer before a large version file, so the other machine can briefly see a pointer to a file that hasn't arrived. Let sync finish before opening the work on the other machine. Scheinwerk does not try to guard against this.
- `cache/` should be excluded from sync (Synology Drive file filter). Documented, not enforced.

---

## 10. Core API (`scheinwerk.core`)

Stdlib only. Paths are `pathlib.Path` at runtime and root-relative POSIX `str` when persisted.

```python
# templates.py
validate_name(kind, name, *, seq=None) -> None   # kind: project category asset sequence shot dept task product media layer
validate_extension(ext) -> None                  # "hip": lowercase [a-z0-9]+, no dot
parse_frames(text) -> tuple[int, int]            # "1001-1096"
parse_fps(text) -> int | float                   # "24" -> 24, "23.976"
parse_resolution(text) -> tuple[int, int]        # "1920x1080"
step_name(text, delta, step=10) -> str | None   # "sq020", +1 -> "sq030"; None without a number
shot_sequence(shot) -> str                       # "sq010_0010" -> "sq010"
format_version(n) -> str / parse_version(text) -> int | None
format_workfile(entity, dept, task, version, ext=None) -> str   # no ext: hero_mdl_main_v003
parse_workfile(filename, entity, dept, task) -> tuple[int, str] | None   # None = unmanaged
format_product_stem(entity, product, version) -> str     # hero_base_model_v002
format_product_file(entity, product, version, ext, frame=None) -> str   # hero_pants_v002.1001.bgeo.sc

# fileio.py
write_text(path, text) / write_json(path, data)  # atomic, LF, skips identical content
read_json(path) -> dict | None              # None if missing or invalid
copy_new(src, dest)                         # never overwrites (AlreadyExists)

# project.py
find_root(path) -> Path | None
read_config(root) -> dict
Project.find(path) -> Project | None
Project.create(folder, name, **settings) -> Project   # writes scheinwerk.json + assets/ shots/ shared/{hooks,templates}/ shared/usd/structure.usd io/{in,out}/;
                                                      # refuses an existing or nested project and unknown settings
project.root -> Path
project.config -> dict                      # parsed scheinwerk.json
project.setting(key)                        # config value or default
project.department_template(entity_type) -> dict[str, list[str]]
project.ignored(name) -> bool
project.scan(folder, dirs_only=True) -> list[Path]   # sorted, ignored entries skipped
project.assets() -> list[Entity]            # filesystem scan, sorted (§6.3)
project.categories() -> list[str]
project.sequences() -> list[Entity]
project.shots(seq=None) -> list[Entity]
project.entity(name) -> Entity              # resolves by unique name, prefixes asset: shot: seq:
project.create_category(name) -> Path
project.category_choices() -> list[str]    # char, prop, env, then other existing ones
project.next_sequence_name() -> str         # sq030
project.next_shot_name(seq) -> str          # sq010_0040
project.create_asset(name, category=None) -> Entity  # names unique project-wide, case-insensitive
project.create_sequence(name) -> Entity
project.create_shot(name, frames=None) -> Entity     # creates the sequence if needed
project.entity_at(context) -> Entity        # the entity a context belongs to
project.rel(path) -> str                    # root-relative POSIX
project.abs(rel) -> Path

# context.py
Context.from_path(path) -> Context | None
context.path() -> Path                      # inverse of from_path

# entities.py  (thin, path-backed; no cached state)
Entity  # Asset, Shot and Sequence are one class told apart by .type ("asset" | "shot" | "sequence")
    .project .type .name .category .sequence .path .valid .frames .fps   # fps: entity.json override, else the project's
    .set_frames(start, end)                 # assets and shots; sequences derive theirs; rewrites a shot's root layer if it exists
    .departments() -> list[Department]
    .department(name) -> Department
    .create_department(name, tasks=("main",)) -> Department   # each task gets work/ and cache/
    .products(usd=None) -> list[Product]    # USD layers first
    .media() -> list[Product]
    .create_product(name) -> Product
    .create_media(name) -> Product
Department: .entity .name .path .custom .valid .tasks() .task(name) .create_task(name)   # dept folder must exist
Task:
    .entity .name .path .work_dir .cache_dir .custom .valid
    .workfiles() -> list[Workfile]          # newest first
    .unmanaged() -> list[Path]
    .latest_workfile(ext=None) -> Workfile | None
    .next_workfile(ext=None) -> Path      # without ext: no extension
    .new_version_from(workfile) -> Path     # copy + bump
    .new_empty_workfile(ext) -> Path        # copy of shared/templates/empty.<ext>, NotFound if missing
Workfile: .path .version .ext

# versions.py
Product(project, path): .name .usd .is_media .kind .valid .pointer .versions() .latest() .current() .next_version_dir() -> Path
    .next_version_path() -> Path   # creates the next v### folder, returns …/v002/hero_base_model_v002
    .highest() -> int | None       # highest v###, empty ones included
    .file_path(version, ext, frame=None) -> Path   # …/v002/hero_pants_v002[.1001].ext
Version(project, path): .number .path .info -> dict | None .files() .empty
file_sequences(paths) -> list[FileGroup]    # FileGroup: .label ("name.####.exr") .paths .frames .count .missing

# publish.py
next_publish(entity, name) -> Path
next_media(entity, name) -> Path
next_usd(entity, layer) -> Path
finalize(version_dir, *, source=None, comment="", main_file=None, dcc=None, usd_files=None) -> None   # usd_files: renders (§8.3)
set_current(usd_version_dir, *, main_file=None) -> None   # rewrite pointer
ingest(files, target) -> list[Path]

# env.py
env_for(context) -> dict[str, str]
ENV_VARS / cleared_env() -> dict[str, str]   # every SW_* variable set to ""

# install.py  (machine-local Houdini preferences, §13.2.1)
houdini_pref_dirs() -> list[Path] / package_data(repo) -> dict
documents_dir() -> Path                     # Windows Documents folder, also when moved
install_houdini(repo) -> list[Path] / uninstall_houdini() -> list[Path]

# hooks.py
run_hook(name, **kwargs) -> None            # see §14

# settings.py  (machine-local, §8.4)
user_dir() -> Path / settings_path() -> Path
load_settings() -> dict / save_settings(data)
add_recent_project(root) / app_for(settings, ext) -> str | None

# system.py  (one helper per OS)
open_path(path, app=None) / reveal(path)
open_command(path, app=None) / reveal_command(path)   # the commands, for tests

# doctor.py
check(project) -> list[Issue]               # Issue(kind, path, detail); report only (§11)

# usd_pointer.py
# every writer except write_structure adds framesPerSecond/timeCodesPerSecond = fps (§9.2 item 5)
write_pointer(path, target_rel, *, fps, default_prim=None) -> None   # default_prim: asset pointers only
write_root_layer(path, sublayers, *, fps, frames=None) -> None       # shot/sequence root, payload.usd; frames: shots
write_component(path, asset, *, fps) -> None                         # <asset>.usd, payload ./payload.usd
write_structure(path) -> None                                        # shared/usd/structure.usd, only when missing
write_entity_layers(entity) -> None                                  # an entity's entry/root layers from its pointers (§9.2 item 4)
asset_prim_path(asset) -> str                                       # /world/chars/hero: where a shot references an asset (§9.2)
layers_below(entity, layer) -> list[Path]                           # published layers a version of `layer` sits on, strongest first (§13.2)
read_pointer(path) -> str | None
```

Errors: core functions raise `ScheinwerkError` subclasses (`NotInProject`, `InvalidName`, `ParseError`, `NotFound`, `AlreadyExists`) with messages that can be shown to the user. They never call `sys.exit` or print.

---

## 11. CLI (`sw`)

argparse, entry point `sw`. The project is found from the current directory, like git; path arguments are relative to it. Every command that prints a path accepts `--relative` (root-relative POSIX) and `--json`; `ls`, `frames`, `context`, `env` and `doctor` also print JSON with `--json`.

```text
sw init [name]                              # make cwd a project; name defaults to the folder name
sw new asset [category/]hero
sw new category char                        # empty category
sw new seq sq010
sw new shot sq010_0010 [--frames 1001-1096] # creates the sequence folder if needed
sw new dept <entity> <dept> [--tasks a b]   # default tasks: the template's, else main
sw new task <entity> <dept> <task>
sw new product <entity> <name>
sw ls [entity] [dept[/task]]
sw next <entity> <dept>[/<task>] [--ext hip]  # next workfile path (no extension unless --ext), creates nothing
sw next-publish <entity> <name> [--file]     # creates + prints next version folder,
sw next-usd <entity> <layer> [--file]        # or with --file the file path in it, no extension
sw next-media <entity> <name> [--file]
sw latest <entity> (--product N | --usd L | --media N | --work dept[/task])
sw frames <entity> [START-END]              # show or set; sequences show their shots' range
sw finalize <version_dir> [-m comment] [--source path] [--main file]
sw set-current <usd_version_dir> [--main file]
sw ingest <files...> <entity> (<dept>[/<task>] | --product N | --media N)
sw context [path]                           # parse and print context (default: cwd)
sw env [path] [--shell zsh|bash|pwsh]
sw doctor                                   # report only, see below
sw install houdini                          # write the Houdini package file (§13.2.1)
sw uninstall houdini                        # remove what `sw install` wrote
sw gui [path]                               # Phase 3
```

- Entity arguments resolve by unique name (`hero`, `sq010_0010`, `sq010`). If a name is ambiguous, use the prefixes `asset:`, `shot:` or `seq:`.
- `<dept>` alone stands for its task when the department has exactly one task (as in the GUI, §12.1).
- Output goes to stdout; errors go to stderr as `sw: error: <message>`. Exit codes: 0 success, 1 a Scheinwerk error (or `doctor` found issues, or `latest` found nothing), 2 wrong usage.
- Absolute paths are printed in the OS's own form; `--relative` and JSON keys are as described per command in the usage guide.
- `sw ls` without arguments lists assets (uncategorised first, then `category/asset`, then empty categories) and shots grouped by sequence with frame ranges. With an entity: departments and tasks, products (`[usd]`, latest and current version) and media. With `dept`: its tasks. With `dept/task`: workfiles newest first, then unmanaged entries. Flags show as `[custom]` and `[invalid name]`.
- `sw env --shell zsh|bash` prints `export KEY='value'`, `--shell pwsh` prints `$env:KEY = 'value'`, otherwise `KEY=value`. Use it as `eval "$(sw env --shell zsh)"`.
- `sw doctor` only reports, never changes anything (`--fix-names` may come later with the rename tool, §16). It lists, ordered by kind then path:
  - `invalid name`: categories, entities, departments, tasks, products, USD layers and media whose names break §5;
  - `conflict copy`: any file or folder whose name contains `Conflict` (Synology);
  - `absolute path`: the first drive letter, `/Users/`, `/Volumes/` or UNC path in each `.usd`, `.usda` and `.nk` file (`cache/` is skipped);
  - `empty version`: version folders with no files besides `version.json`;
  - `unpublished reference`: the first path through a `work/` or `cache/` folder in each `.usd` and `.usda` file under `publish/` (a published layer may only reference published files, §9.2 item 6). `work` and `cache` are reserved names, so such a path segment always means a task folder.

---

## 12. GUI

PySide6. The GUI holds no logic: every action is one core call. Widgets are `QWidget`s (not `QMainWindow`), so Houdini and Nuke can dock them. The browser (`gui/browser.py: Browser`) applies `theme.qss` to itself, never to the `QApplication`, so it can't restyle a host DCC. `gui/app.py` is only a window around it for standalone use. Start it with `sw gui [path]` (runs `python -m scheinwerk.gui` as its own process, so the CLI never imports GUI code) or `scheinwerk-gui [path]`.

### 12.1 Layout

```text
┌──────────────────────────────────────────────────────────────────────────┐
│          [Scenefiles] [Products] [Media]            [ project ▾ ] [Reload] │ ← top bar, fixed
├─────────────────┬──────────────┬──────────────┬───────────────────────────┤
│ [Assets][Shots] │ Column 2     │ Column 3     │ Column 4                  │
│ entity tree     │              │              │                           │
│                 ├──────────────┴──────────────┤                           │
│                 │ Detail panel                │                           │
└─────────────────┴─────────────────────────────┴───────────────────────────┘
```

- **Top bar** is identical in every view: view switch, project dropdown, Reload. The dropdown lists the recent projects that still exist, then *Open existing project…* (pick any folder inside a project) and *New project…*. Choosing an action and cancelling leaves the open project selected.
- **New project…** asks for *Location* (a folder, with *Browse…*; pre-filled with the folder holding the open project), *Name*, *Frame rate* and *Resolution* (dropdowns of common values that can be typed into, parsed by `parse_fps` / `parse_resolution`), and *Start frame*; defaults come from §8.1. The project folder is `<location>/<name>`, shown in the dialog before it is created. Departments, USD layer order and ignore patterns are edited in `scheinwerk.json`.
- **Entity column** is the same in every view: Assets/Shots toggle above a tree. Assets are grouped by category if present. Shots are grouped by sequence, and each sequence's `_seq` level is its first child, labelled `<seq> (sequence)`.
- All columns have type-to-filter: typing in a focused column shows a filter field under it, Backspace edits it, Esc clears and hides it. Columns are separated by splitters, the detail panel sits under columns 2–3 and column 4 runs full height (as in the mock-up).
- Asset tree: uncategorised assets first, then one group per category (empty categories too).
- Dimmed (italic, `dimColor` from the theme): unmanaged files, empty versions, invalid names. Custom departments/tasks show `(custom)`.
- On start: the project and entity/department/task of `path` if given, else the most recent project that still exists, else an empty browser that says to use `+`.

| View | Column 2 | Column 3 | Column 4 | Detail panel |
| --- | --- | --- | --- | --- |
| Scenefiles | Departments | Tasks | Workfiles, newest first (+ unmanaged, dimmed) | path, latest version, frame range |
| Products | Products (USD layers under a "USD layers" header, then a "Products" header) | Versions, newest first, `(current)` on the USD pointer's version | Files in version, numbered files as one `name.####.ext  first-last (count)` line | path, source workfile, comment, date, user, dcc; current yes/no for USD; file count |
| Media | Media names | Versions | Files / frame range summary (as Products) | same as Products |

- A column is never left without a selection when it has rows: it selects the remembered row if it is there, else the first one (the entity tree: the first asset or shot, skipping category and sequence header rows; Products: skipping the USD layers/Products headers). So selecting an entity selects its first department, first task and newest workfile. Deselecting (Ctrl-click, clicking empty space) puts the selection back.
- Selection is remembered per view while the app runs.

### 12.2 Actions — right-click only (no bottom buttons)

| Where | Menu |
| --- | --- |
| Entity column | New asset · New category · New sequence · New shot · Set frame range · Copy path · Copy relative path · Reveal |
| Departments | New department… (dialog: the template departments not created yet, or a typed name; *Create task "main"*, on by default) · Copy path · Reveal |
| Tasks | New task · Copy path · Reveal |
| Workfiles (file) | Open · Open with ▸ · New version from this · Copy path · Copy relative path · Reveal |
| Workfiles (empty space or file) | Save scene as `<next workfile>` (inside a DCC only) · New empty workfile ▸ (ext) · **Copy next version path** · Ingest file(s)… |
| Products / Media list | New product… / New media… (name prompt) · Ingest file(s)… · Copy path · Reveal |
| Versions (empty space or version) | **Copy next version path** |
| Versions (version) | Open folder · Finalize / Edit comment · Set as current (USD) · Copy path · Copy relative path · Reveal |

Other interactions:

- Double-click = open (workfile, unmanaged file, file in a version) or reveal (version).
- Drag files from Finder/Explorer onto a task, or into the Files column of the selected task → ingest as next workfiles. Onto a product/media name, or into its Versions/Files columns → ingest as its next version.
- F5 = Reload, plus an automatic refresh when the window regains focus (at most every 2 s).
- The entity menu offers asset/category entries in Assets mode and sequence/shot entries in Shots mode.
  - "New asset": a *Category* dropdown you can also type into (`category_choices()`, pre-set to the selected category, empty = no category) and a *Name* field.
  - "New sequence": a *Name* field with `-`/`+` buttons (§5.2: step by 10; on an empty field, `next_sequence_name()`).
  - "New shot": a *Sequence* dropdown of existing sequences with `-`/`+`, a *Shot* field for the 4-digit number with `-`/`+` (on an empty field, the next free number in the chosen sequence), and optional *Frames*. The shot name is `<sequence>_<shot>`.
  - Presets come from the right-clicked item, which right-clicking also selects: a sequence folder, its `(sequence)` entry or any of its shots preset the *Sequence*; a category or an asset in it presets the *Category*.
- "Open" uses the application configured for the extension in the user settings (§8.4, `dcc`), else the OS default. "Open with ▸" lists every configured application plus the system default. Inside a DCC (the browser panel in Houdini), "Open" and double-click load that DCC's own scene files into the running session through its adapter (`open`, §13.1), never a second instance; other files open as above, and "Open with ▸" still launches the chosen application.
- "Save scene as `<next workfile>`" (only in a DCC's browser panel) saves the open scene through the adapter (`save_as`, §13.1) as the selected task's next workfile, named in the entry, e.g. *Save scene as hero_mdl_main_v003.hip*. It keeps the scene's extension; an untitled scene, or one with another extension, gets the DCC's first extension (`hip`). Like *Save Next Version* (§13.2.3) it runs the `post_save` hook, but into the selected task, so it can also save an untitled scene or move a scene into another task.
- Extension list for New empty workfile: `hip`, `nk`, `blend`, the `dcc` extensions from the user settings, the `shared/templates/empty.<ext>` templates and the extensions already in the task. New empty workfile is enabled only where a template exists.
- "Copy next version path" copies a path without extension (§5.3). In Files it creates nothing. In Versions it creates the next `v###` folder (reserving the number), copies `…/v###/{entity}_{name}_v###` and selects the new, still empty version.
- "Finalize / Edit comment" asks for the comment (pre-filled) and, for a USD version with several `.usd` files, which one is the main file.
- Column widths are proportions (entities 18 %, departments + tasks 30 %, files 52 %), so a narrow panel (docked in a DCC) shrinks every column alike. The splitters can still be dragged.
- After creating something the browser selects it. Errors from core appear in a message box.
- Open and reveal go through one helper per OS (`core/system.py`): macOS `open` / `open -a <app>` / `open -R`, Windows `os.startfile` / the app's exe / `explorer /select,`, Linux `xdg-open`.

### 12.3 Styling

All colours, fonts and spacing live in one QSS file (`gui/theme.qss`), with a monospace UI font (Menlo, Consolas, DejaVu Sans Mono, …). The look follows the user's reference mock-up (flat panels, warm palette: orange background, peach panels, dark rust for the active state). No hard-coded colours in widget code; the one colour widgets need, for dimmed rows, comes from the theme as `Column { qproperty-dimColor: … }`. Tree rows and the branch area get opaque colours in every state (normal, hover, selected): a host application (Houdini) styles item views application-wide, and its Qt style paints rows itself wherever the theme leaves them transparent. A GUI test renders the tree under such a style.

---

## 13. DCC integrations

### 13.1 Adapter interface (`scheinwerk.dcc.base`)

```python
class DCCAdapter(Protocol):
    name: str
    extensions: tuple[str, ...]
    def current_file(self) -> Path | None: ...
    def open(self, path: Path) -> None: ...
    def save_as(self, path: Path) -> None: ...
    def main_window(self) -> "QWidget | None": ...
```

Integrations are installed persistently (no launcher needed). On every file open and save-as, they derive the context from the file path and set the §7.2 env vars. `save_as` runs the `post_save` hook after saving; `open` and `save_as` raise `ScheinwerkError` when the DCC can't load or save.

### 13.2 Houdini 21 (key integration)

Target Houdini 21 (Python 3.11, PySide6 6.5); everything is also checked in Houdini 22 (Python 3.13, PySide6 6.8). Code: `scheinwerk/dcc/houdini.py`; startup files: `integrations/houdini/`.

1. **Package** `integrations/houdini/scheinwerk.json` sets `SCHEINWERK` (the checkout), prepends `$SCHEINWERK/src` to `PYTHONPATH` and adds `$SCHEINWERK/integrations/houdini` to `HOUDINI_PATH` (`python3.11libs/` and `python3.13libs/` with the same `pythonrc.py`, `MainMenuCommon.xml`, `toolbar/`, `python_panels/`, `otls/`, `scripts/`). `sw install houdini` (`core/install.py`) writes it, with the checkout's absolute path, into `packages/` of every Houdini preferences folder that exists (macOS `~/Library/Preferences/houdini/<X.Y>/`, Windows `houdini<X.Y>/` in the user's Documents folder, read from the registry because it can be moved (e.g. to `D:\you\Dokumente`; fallback `~/Documents`), Linux `~/houdini<X.Y>/`). It is machine-local, so the absolute path is allowed (§2.4). A `scheinwerk.json` that doesn't set `SCHEINWERK` was not written by Scheinwerk: install refuses (writing nothing) and uninstall skips it.
2. **Scene callbacks** (`hou.hipFile.addEventCallback`, registered by `pythonrc.py`): after load and after every save → set the §7.2 variables and `$JOB` (= `SW_ROOT`) with `hou.putenv` **and** `os.environ` (so Python code and child processes such as husk see them too); after *File → New* → clear them. On load, and on a save that moves the scene to another entity, if the entity's frame range or fps differs from the scene's, ask once before applying them (only with a UI; headless sessions never change them). Applying the fps keeps keys and the frame range on their frames. The fps matters for USD: the USD ROP always writes the scene's fps into a layer (a Configure Layer can't change it), so a scene at the wrong fps would publish retimed layers (§9.2 item 5). Callback errors are logged, never raised.
3. **Menu + shelf + panel:** a *Scheinwerk* main menu and shelf with *Save Next Version*, *Open Scheinwerk Browser* (the §12 browser as a Python panel `scheinwerk`, dockable from the pane-tab menu), *Copy Context Path* (the scene's root-relative path), *Publish All USD*. *Save Next Version* needs a scene saved in a task's `work/`, keeps the extension (`.hip`, `.hipnc`, `.hiplc`) and runs the `post_save` hook. The spec's Ctrl+Alt+S is assigned by the user in the Hotkey Manager (Houdini's hotkey API is not available to verify headless). *Publish All USD* exports every `sw_publish_lop` in the scene whose target is *Publish* and that isn't bypassed, upstream first (in a LOP chain a node is exported before the nodes below it), so a scene that publishes several layers can't leave one stale. A node whose version already exists first gets a new version (as *New version*), so nothing published is overwritten. With a UI it first asks, listing the nodes and their versions. It stops at the first error.
4. **Expression helpers** (`import scheinwerk.dcc.houdini as sw`, Python parameter expressions; they return absolute runtime paths, never stored):
   - `sw.cache(name)` → `<task>/cache/<name>` (free-form).
   - `sw.publish_path(product, ext, version=None, frames=False, shot=None)`, `sw.usd_path(layer, version=None, shot=None)`, `sw.media_path(name, ext, version=None, frames=True, shot=None)` → the recommended file (§5.3) in `version`, default the **highest existing** version (v001 if none). `frames` adds the evaluated frame (`.1001`).
   - `sw.shots()` → `[(shot, frames), …]` of the scene's sequence; `sw.shot_menu()` for menu parms; `sw.set_shot(name)`.
5. **Versioning on nodes:** a node writes into a fixed version until the user clicks *New version*, which sets the node's `version` parm to the highest existing `v###` + 1 (1 when there is none yet). It creates nothing: *Export*/*Render* creates the version folder right before the ROP runs, so an unused number leaves no empty folder. Unlike `next_version_dir` this doesn't reserve the number, so two nodes can pick the same one; the Info box shows when a version already exists. `version` starts at 1 and can't go below; choosing a name sets it to that name's highest version (1 for a new one). Exporting again overwrites that version's files and finalizes it again. Without a valid name nothing is written or finalized: every HDA function refuses it, and the buttons are disabled while the name is empty. Errors from the buttons appear as a message box.
6. **HDAs (seven, in `integrations/houdini/otls/` as `.hdalc` (Houdini Indie), built by `build_hdas.py`), in the TAB menu under *Scheinwerk*. Writing:**
   - `sw_publish_sop`: SOP, wraps a ROP Geometry Output → `publish/<product>/v###/` (or the task cache, below). Name parm `product`; also `ext` (bgeo.sc, vdb, abc, obj). One file per frame for the two ranges, one file without frame number for *Current Frame*. Default range: *Shot Range*.
   - `sw_publish_lop`: LOP, wraps a USD ROP with the *Use Relative Paths* output processor (on by default) → `publish/_usd/<layer>/v###/{entity}_{layer}_v###.usd` (or the task cache, below). Name parm `layer`. Always one main file; a range writes time samples. Default range: *Current Frame*. Publishing refuses a scene whose fps differs from the target entity's, and the Info box warns about it (item 2).
   - **Layer Break After** (`layer_break`, toggle on `sw_publish_lop`, default on): the HDA's output passes the stage on through a Layer Break, so publishes further down the same chain write only what was added after this one (one scene can publish `geo` then `mtl`, or `layout`, `anim`, then `lgt`).
   - **Asset layers on `sw_publish_lop`** (§9.3): with the layer `geo` or `mtl` in an asset scene, the Info box warns about prims outside `/<asset>`. The HDA publishes the stage as it comes in; variants are authored by the user upstream (e.g. Houdini's *Add Variant* LOP), never by the HDA.
   - **Starting a scene** (LOP HDAs, no input, built by `build_hdas.py`):
     - `sw_asset_start`: the asset skeleton for the scene's asset: the Xform `/<asset>` and the Scopes `/<asset>/geo`, its `render` and `proxy` (purposes render and proxy) and `/<asset>/mtl` (§9.3). Only in asset scenes. It authors prims, which end up in the first publish (`geo`).
     - `sw_shot_start`: loads, as sublayers behind a Layer Break (so none of it is published again), the project's structure layer (through the sequence root layer when `sequence` is ticked and that exists, else directly, as in the shot root layer, §9.2), and the published layers ticked in `load` (a multi-select menu of the target's `usd_layer_order` layers plus `sequence`; default `sequence`): tick the layers published from *other* scenes, e.g. `fx` in the main scene, `layout` and `anim` in an fx scene. Has `shot` like the publish HDAs: in a sequence scene it loads that shot's layers, or with `_seq` the sequence's. Also `reload` and an Info box listing the loaded layers. It builds no prims and sets no time: frame range and fps come from the scene (item 2).
     - In the working scene, loaded layers sit below everything authored in the chain (unlike the published root layer's order), so a live preview can differ from the published shot where two departments change the same prim (e.g. fx hiding an animated prop). Final renders therefore use `sw_render`'s *Published shot* source.
   - `sw_render` (**work in progress**: works for simple renders): LOP, wraps a USD Render ROP (Karma, one husk run per frame) → `media/render_<name>/v###/` with its own counter, always one `.exr` per frame. Name parm `render_name` (without `render_`). Default range: *Shot Range*. `source`: *Live stage* (default: the node's input, for iterating) or *Published shot*: renders the target's root layer (`<shot>.usd`, or `<seq>.usd` for `_seq`) with husk, so what is rendered is exactly what is published. The input is ignored then: a Sublayer LOP of the root layer feeds the ROP, so husk renders exactly the published composition, with the render settings at `/Render/rendersettings` (authored by lighting; sublayering drops the lighting layer's own default). On finalize both record `usd_files` (§8.3): the layers of the rendered stage (`GetUsedLayers()`, payloads loaded) that lie in a `publish/` version folder.
   - Common parms: the name parm (a text field whose menu lists the existing names, `hda_name_menu`; on `sw_publish_lop` it starts with the entity's standard layers in working order, labelled *(new)* until published: `geo`, `mtl` for an asset, `usd_layer_order` weakest first for a shot or sequence; changing it calls `hda_name_changed`), `range` (*Current Frame*; *Shot Range*: the target entity's frames, else the scene's range; *Custom Range*: `frame_range`, default `$FSTART`/`$FEND`; read by the inner ROP through `hda_range`), `version`, `new_version` (button), `shot` (sequence scenes), `comment`, `output` (the path, Python expression `hda_output`), `execute` (button) and `info`: a read-only multi-line field (Python expression `hda_info`) with the version count, the latest version (files, frame range, date, user, comment, source scene), for USD the pointer's current version, and whether the node's version is new or will be overwritten; *Export* re-evaluates it afterwards. The inner ROP's path is `chs("../output")` and its post-render script calls `hda_post_render`, which finalizes the version with `source` = the scene (`version.json`; for USD also the pointer and root layer). The code tells the kinds apart by the `product` / `layer` / `render_name` parm.
   - **Write To and Load from Disk** (`sw_publish_sop`, `sw_publish_lop`): `target` = *Publish* (default, as above) or *Task cache*: the same name, versioning and output, but into the scene's task cache, `<task>/cache/<name>/v###/<entity>_<name>_v###[.####].<ext>`, with nothing finalized (no `version.json`, no pointer or root layer: caches stay free-form, §4); `shot` and `comment` are hidden then, and in a sequence scene it is the `_seq` task's cache. Both also have `choose` (*Choose…*, disabled for the task cache): the picker below in publish mode, for an existing product/layer of an entity the scene publishes to (its own asset or shot; in a sequence scene one of the sequence's shots, which also sets `shot`). It sets the name and switches to its highest version; typing a name works as before. The name menu lists the caches of the task instead of the products. `load` (*Load from Disk*) outputs the written version instead of the input, behind a Switch: a File SOP reading `chs("../output")` (SOP); on `sw_publish_lop` a Sublayer LOP that loads the written file on the published layers below it (`layers_below`, §10: for an asset's `mtl` the `geo` and the other weaker layers, for a shot layer the weaker layers and the sequence root or structure layer; the same stack as the root layer, up to this layer). A layer published after a Layer Break holds only overs for what it doesn't define, so loading it alone would lose the prims below it. Nothing upstream cooks; the layers below are their current published versions, so unpublished upstream edits don't show.
   - **Importing** (both have `choose` (*Choose…*: the picker below), `entity` (empty = the scene's own entity, else an asset, shot or `seq:<name>`; a plain text field), `reload`, `path` (Python expression), `info`):
     - `sw_import_sop`: SOP, no input. `product` (menu of the entity's products), `version` (`latest` = the newest version with files, or a `v###`), `file` (one of the version's files/sequences, default the first; sequences follow the current frame). A File SOP reads `chs("../path")`, so `.bgeo.sc`, `.vdb`, `.obj` and `.abc` (packed) load.
     - `sw_import_lop`: LOP, optional input. `layer` (empty = the entity's entry/root layer `<entity>.usd`, or a layer), `version` (`current` = the layer's pointer, or a `v###` = that version's main file), `mode` (*Auto*: reference an asset, sublayer a shot or sequence; *Reference*; *Sublayer*), `primpath` (reference destination, default `/<entity>` in an asset scene; in a shot or sequence scene an asset's group in the structure layer, e.g. `/world/chars/hero` (`asset_prim_path`, §9.2)). A Sublayer and a Reference LOP behind a Switch.
   - **Picker** (`gui/pick.py`, called by `import_choose` and, in publish mode with the allowed entities, `publish_choose`; publish mode hides the checkboxes, chooses no version, refuses other entities, and accepts an entity without choosing a product: then only `shot` is set and the typed name stays, e.g. for a shot that has no products yet). It lists only the matching kind: products for the SOP HDAs, USD layers for the LOP HDAs: the §12 browser as a dialog over Houdini, in its Products view (no view switch or project menu), opened on the node's current entity, product/layer and pinned version. Select an entity and a product (or USD layer), then OK or double-click the product, a version or a file. *Always load the latest version* (USD: *Use the layer's current version*), on unless the node pins a version, writes `latest`/`current`; unticked, the selected version is pinned. For USD, *All layers of the entity* (on when the node's layer is empty) chooses the entry layer. A product of the wrong kind is refused. The entity is written as `""` when it is the scene's own, so a copied scene keeps importing its own entity.
   - All seven are built by `integrations/houdini/build_hdas.py` (hython), from ordinary nodes, so they can be edited by hand; rebuilding replaces such edits.
7. **Sequence scenes:** in a scene under `_seq/`, publishes and renders target one shot: the node's `shot` parm, else the context option `SW_SHOT` (`sw.set_shot`, or *Edit → Context Options*). Without a shot they raise an error. Output lands in **that shot's** `publish/` / `media/`. The `shot` menu (and `SW_SHOT`) also offers `_seq` = *(the sequence itself)*: the output then lands in the sequence's own `publish/` / `media/`, for genuinely sequence-wide products such as a lighting rig, which every shot root layer of the sequence picks up as its weakest layer (§9.2).
8. **USD stack convention:** a department's scene loads the layers published from other scenes with `sw_shot_start` (`load`) and publishes only its own layers. Assets come in through `sw_import_lop` as references to their component (`<asset>.usd`). Everything a published layer references must already be published (§9.2 item 6): cache heavy data with `sw_publish_sop` in *Publish* mode, not into the task cache, before it goes into a USD layer.
9. **New Camera and Light LOPs** start under `/world` (§9.2): `scripts/OnCreated.py`, Houdini's event script for every new node, changes a LOP's `primpath` from Houdini's default `/cameras/$OS` or `/lights/$OS` to `/world/cameras/$OS` or `/world/lights/$OS`. Only those exact defaults change, so a path the user set (also on a copied node) stays. Like any global `OnCreated.py` it is the only one Houdini runs: another package's comes later on `HOUDINI_PATH` and is ignored.
10. **Tests:** `tests/houdini/` runs the integration inside every installed hython (`uv run pytest -m houdini`), loading the package from a temporary `HOUDINI_PACKAGE_DIR`, and uses each of the seven HDAs (Karma render included). UI-only parts (menu, shelf, panel, dialogs, clipboard) are checked by hand.

### 13.3 Nuke (current)

- `init.py`/`menu.py` via `NUKE_PATH`.
- On script load: env vars, frame range + fps from `entity.json`.
- Menu: Save next version, Open browser (docked panel).
- "Load latest render": Read node at the newest `media/render_*` version, path written as `[getenv SW_ROOT]/…`.
- "Update selected Reads to latest".
- Write preset → next `media/comp/v###/`.

### 13.4 Blender (current)

- A Blender extension, no Qt.
- N-panel: shows the context, Save next version, Open Scheinwerk browser (launches `sw gui <blend path>` as a separate process).
- `load_post` handler sets env vars and the frame range.
- Uses Blender's own `//` relative paths ("Make Paths Relative" on save).
- USD/Alembic export helpers only once Blender is actually part of the USD chain.

### 13.5 Any other DCC

No integration needed: "Copy next version path" in Files → Save As; "Copy next version path" in Versions → export (add the extension and frame number the DCC needs); optional Finalize in the GUI; ingest for tools that write elsewhere.

---

## 14. Hooks

- Locations: `<project>/shared/hooks/*.py` and `<user settings dir>/hooks/*.py`. Both are loaded, project first.
- A hook is a module-level function with a known name. v1 names:
  - `post_create(kind, path, context)`, where kind is one of `asset`, `shot`, `sequence`, `dept`, `task`, `product`, `media`
  - `post_save(path, context)`, called by integrations after Save next version
  - `post_publish(version_dir, context)`, called after `finalize`
- The project comes from the `context` argument. Files whose name starts with `_` are skipped. Hook files are loaded fresh on every call, in filename order.
- Exceptions inside hooks (including syntax errors) are caught and logged (logger `scheinwerk.hooks`), and never block the action.
- No registry, no event bus, no priorities.

---

## 15. Repository, tooling, testing

```text
scheinwerk/
├── pyproject.toml          # uv; extras: [gui] = PySide6; scripts: sw, scheinwerk-gui
├── CLAUDE.md
├── docs/spec.md            # this file
├── src/scheinwerk/
│   ├── core/  templates.py project.py context.py entities.py versions.py
│   │          publish.py env.py hooks.py usd_pointer.py fileio.py doctor.py
│   │          settings.py system.py install.py errors.py
│   ├── cli.py
│   ├── gui/   app.py browser.py columns.py actions.py dialogs.py pick.py theme.qss __main__.py
│   └── dcc/   base.py houdini.py nuke.py blender.py
├── integrations/
│   ├── houdini/  scheinwerk.json  build_hdas.py  python3.11libs/  python3.13libs/  MainMenuCommon.xml
│   │             toolbar/  python_panels/  otls/  scripts/
│   ├── nuke/     init.py menu.py
│   └── blender/  scheinwerk_ext/
└── tests/
```

- Python **3.11**. Use no syntax newer than 3.11.
- `ruff` for lint/format. `pytest` for tests.
- `core/` has an import test: importing it must not pull in any non-stdlib module.
- Tests build real throwaway projects in `tmp_path`. The filesystem is never mocked.
- Required suites: template format ⇄ parse round-trips; optional category parsing; `_seq` parsing; version counting (shared across extensions, gaps, v1000+, empty folders); atomic writes; pointer/root layer text; unmanaged files; ignore patterns.
- CI: GitHub Actions matrix `macos-latest` + `windows-latest`, Python 3.11.
- GUI and DCC code are tested manually. Keep them thin enough that this is acceptable. `tests/gui` has offscreen smoke tests (columns fill, menus, a few actions); they are skipped when PySide6 isn't installed, as in CI.

---

## 16. Roadmap

| Phase | Scope | Done when |
| --- | --- | --- |
| 0 — Spec | This file + `CLAUDE.md` | Every path can be derived from this spec. |
| 1 — Core | §6, §8, §9, §10 + tests | Round-trip and versioning tests pass on Mac + Windows CI. |
| 2 — CLI | §11 | A test project can be set up and used through `sw` alone. |
| 3 — GUI | §12 | Finder/Explorer is no longer needed to find or create files. |
| 4 — Houdini | §13.2, and the USD asset and shot structure of §9.2–§9.3 | Starting from *Asset Start* / *Shot Start*: asset (geo and mtl layers with variants, one scene) → shot (layout, anim, lighting in one scene, fx in another) → a final render of the published shot, in a 25 fps project, with no hand-typed paths, including a `_seq` multi-shot hip that publishes to the sequence itself. |
| 5 — Nuke | §13.3 | A Phase-4 render is comped without typing a path. |
| 6 — Blender | §13.4 | Blender workfiles are versioned and opened like the rest. |
| 7 — Later | launcher (per-project OCIO), deep `doctor`, thumbnails, asset library, rename tool | When actually missed. |
