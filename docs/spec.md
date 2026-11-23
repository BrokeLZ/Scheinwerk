# Scheinwerk — Specification

Status: v1 spec · Last updated: 2026-11-22
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

No database or server. No multi-user handling, locking or permissions. No task status, assignments or scheduling. No review/annotation tool or built-in media player. No custom USD asset resolver. No symlinks. No per-file metadata for workfiles. No template-editor UI. No file watchers. No ORM layer over the folders.

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
│           │   │   ├── <asset>.usd       # asset entry layer (pointer)
│           │   │   └── <layer>/
│           │   │       ├── <layer>.usd   # pointer layer
│           │   │       └── v###/         # version folders
│           │   └── <product>/v###/       # any non-USD product, free name
│           └── media/<name>/v###/
├── shots/
│   └── <seq>/
│       ├── _seq/                         # optional sequence-level entity
│       │   ├── <dept>/<task>/work|cache/
│       │   ├── publish/                  # only for genuinely sequence-wide products
│       │   └── media/
│       └── <shot>/                       # <seq>_<nnnn>, unique project-wide
│           ├── entity.json               # frame range
│           ├── <dept>/<task>/work|cache/
│           ├── publish/
│           │   ├── _usd/
│           │   │   ├── <shot>.usd        # shot root layer
│           │   │   └── <layer>/          # layout, anim, fx, lgt: pointer + v###/
│           │   └── <product>/v###/
│           └── media/<name>/v###/
├── shared/                               # project-wide: HDAs, templates, hooks, LUTs
│   ├── hooks/
│   └── templates/                        # optional empty workfile templates: empty.<ext>
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
| USD version folder | `publish/_usd/{layer}/v{version:03d}/` | `publish/_usd/asset/v003/` |
| USD pointer | `publish/_usd/{layer}/{layer}.usd` | `publish/_usd/asset/asset.usd` |
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
| File-relative | USD asset paths, Blender `//` | `./v003/hero_asset_v003.usd`, `../../../../assets/char/hero/publish/_usd/hero.usd` |
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
- `usd_layer_order`: strongest first, used for the asset entry layer and the shot/sequence root layer (§9.2).
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
  "comment": ""
}
```

All fields are optional. Readers must never require this file; a missing or broken file reads as no info.

- `source` is root-relative; a source outside the project is refused. `dept` and `task` come from the source path.
- Re-finalizing (e.g. "Edit comment") always sets `comment`, sets `source`/`dept`/`task`/`dcc` only when given, and keeps `user`, `created` and unknown keys.

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
4. The entry/root layer `publish/_usd/<entity>.usd` (asset entry layer, shot or sequence root layer) sublayers `./<layer>/<layer>.usd` for every layer that has a pointer. It is rewritten on every finalize/set-current, so it exists from the first publish and picks up new layer names. Identical content is not rewritten (§8).

Pointer layer format (ASCII content in a `.usd` file, written as plain text by the core, no `pxr` needed):

```text
#usda 1.0
(
    defaultPrim = "hero"
    subLayers = [@./v003/hero_asset_v003.usd@]
)
```

`defaultPrim` is always written (= entity name). Without it, references to the pointer fail. Layer paths must be file-relative (`./` or `../`); anything else is refused.

The pointer targets the main USD file (`.usd`, `.usda`, `.usdc`) at the top of the version folder: the only one if there is one, else the one with the recommended name `{entity}_{layer}_v###`, else `main_file` must be given (`finalize` and `set_current` both take it).

Entry/root layer format. Layers are ordered strongest first: names in `usd_layer_order` in that order, then all others A–Z. The asset entry layer has `defaultPrim` = asset name (it is referenced); shot and sequence root layers have none (they are sublayered or opened, not referenced). With no layers: `subLayers = []`.

```text
#usda 1.0
(
    defaultPrim = "hero"
    subLayers = [
        @./fx/fx.usd@,
        @./geo/geo.usd@
    ]
)
```

"Set as latest" on any USD version rewrites the pointer to that version. That is the only form of pinning/rollback.

### 9.3 Ingest

`ingest(files, target)` copies files into the next workfile version (renamed to the template) or into the next product/media version folder (names kept). It never moves or deletes the originals.

- Target a task: each file becomes its own next version, in the order given (`a.hip`, `b.hip` → v004, v005). The extension is lowercased (`scene.HIP` → `….hip`). A file without an extension is refused.
- Target a product or media name: all files go into one new version folder. Two files with the same name are refused.
- Only files, no folders. Everything is checked before the first copy.

### 9.4 Sync safety (Synology Drive)

- Pointer layers and `version.json` are written last, atomically, so the other machine never syncs a pointer to a version that hasn't arrived yet.
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
Project.create(folder, name, **settings) -> Project   # writes scheinwerk.json + assets/ shots/ shared/{hooks,templates}/ io/{in,out}/;
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
    .project .type .name .category .sequence .path .valid .frames
    .set_frames(start, end)                 # assets and shots; sequences derive theirs
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
finalize(version_dir, *, source=None, comment="", main_file=None, dcc=None) -> None
set_current(usd_version_dir, *, main_file=None) -> None   # rewrite pointer
ingest(files, target) -> list[Path]

# env.py
env_for(context) -> dict[str, str]
ENV_VARS / cleared_env() -> dict[str, str]   # every SW_* variable set to ""

# install.py  (machine-local Houdini preferences, §13.2.1)
houdini_pref_dirs() -> list[Path] / package_data(repo) -> dict
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
write_pointer(path, target_rel, default_prim) -> None
write_root_layer(path, sublayers, default_prim=None) -> None
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
  - `empty version`: version folders with no files besides `version.json`.

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
| Workfiles (empty space or file) | New empty workfile ▸ (ext) · **Copy next version path** · Ingest file(s)… |
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
- "Open" uses the application configured for the extension in the user settings (§8.4, `dcc`), else the OS default. "Open with ▸" lists every configured application plus the system default.
- Extension list for New empty workfile: `hip`, `nk`, `blend`, the `dcc` extensions from the user settings, the `shared/templates/empty.<ext>` templates and the extensions already in the task. New empty workfile is enabled only where a template exists.
- "Copy next version path" copies a path without extension (§5.3). In Files it creates nothing. In Versions it creates the next `v###` folder (reserving the number), copies `…/v###/{entity}_{name}_v###` and selects the new, still empty version.
- "Finalize / Edit comment" asks for the comment (pre-filled) and, for a USD version with several `.usd` files, which one is the main file.
- After creating something the browser selects it. Errors from core appear in a message box.
- Open and reveal go through one helper per OS (`core/system.py`): macOS `open` / `open -a <app>` / `open -R`, Windows `os.startfile` / the app's exe / `explorer /select,`, Linux `xdg-open`.

### 12.3 Styling

All colours, fonts and spacing live in one QSS file (`gui/theme.qss`), with a monospace UI font (Menlo, Consolas, DejaVu Sans Mono, …). The look follows the user's reference mock-up (flat panels, warm palette: orange background, peach panels, dark rust for the active state). No hard-coded colours in widget code; the one colour widgets need, for dimmed rows, comes from the theme as `Column { qproperty-dimColor: … }`.

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

Integrations are installed persistently (no launcher needed). On every file open and save-as, they derive the context from the file path and set the §7.2 env vars.

### 13.2 Houdini 21 (key integration)

Target Houdini 21 (Python 3.11, PySide6 6.5); everything is also checked in Houdini 22 (Python 3.13, PySide6 6.8). Code: `scheinwerk/dcc/houdini.py`; startup files: `integrations/houdini/`.

1. **Package** `integrations/houdini/scheinwerk.json` sets `SCHEINWERK` (the checkout), prepends `$SCHEINWERK/src` to `PYTHONPATH` and adds `$SCHEINWERK/integrations/houdini` to `HOUDINI_PATH` (`python3.11libs/` and `python3.13libs/` with the same `pythonrc.py`, `MainMenuCommon.xml`, `toolbar/`, `python_panels/`, `otls/`). `sw install houdini` (`core/install.py`) writes it, with the checkout's absolute path, into `packages/` of every Houdini preferences folder that exists (macOS `~/Library/Preferences/houdini/<X.Y>/`, Windows `~/Documents/houdini<X.Y>/`, Linux `~/houdini<X.Y>/`). It is machine-local, so the absolute path is allowed (§2.4). A `scheinwerk.json` that doesn't set `SCHEINWERK` was not written by Scheinwerk: install refuses (writing nothing) and uninstall skips it.
2. **Scene callbacks** (`hou.hipFile.addEventCallback`, registered by `pythonrc.py`): after load and after every save → set the §7.2 variables and `$JOB` (= `SW_ROOT`) with `hou.putenv` **and** `os.environ` (so Python code and child processes such as husk see them too); after *File → New* → clear them. On load, and on a save that moves the scene to another entity, if the entity's frame range differs from the scene's, ask before applying it (only with a UI; headless sessions never change it). Callback errors are logged, never raised.
3. **Menu + shelf + panel:** a *Scheinwerk* main menu and shelf with *Save Next Version*, *Open Scheinwerk Browser* (the §12 browser as a Python panel `scheinwerk`, dockable from the pane-tab menu), *Copy Context Path* (the scene's root-relative path). *Save Next Version* needs a scene saved in a task's `work/`, keeps the extension (`.hip`, `.hipnc`, `.hiplc`) and runs the `post_save` hook. The spec's Ctrl+Alt+S is assigned by the user in the Hotkey Manager (Houdini's hotkey API is not available to verify headless).
4. **Expression helpers** (`import scheinwerk.dcc.houdini as sw`, Python parameter expressions; they return absolute runtime paths, never stored):
   - `sw.cache(name)` → `<task>/cache/<name>` (free-form).
   - `sw.publish_path(product, ext, version=None, frames=False, shot=None)`, `sw.usd_path(layer, version=None, shot=None)`, `sw.media_path(name, ext, version=None, frames=True, shot=None)` → the recommended file (§5.3) in `version`, default the **highest existing** version (v001 if none). `frames` adds the evaluated frame (`.1001`).
   - `sw.shots()` → `[(shot, frames), …]` of the scene's sequence; `sw.shot_menu()` for menu parms; `sw.set_shot(name)`; `sw.layers_below(layer, shot=None)` (item 8).
5. **Versioning on nodes:** a node writes into a fixed version until the user clicks *New version*, which reserves the next `v###` (`next_version_dir`) and sets the node's `version` parm. `version` 0 means the highest existing version. Exporting again overwrites that version's files and finalizes it again.
6. **HDAs (three, built by hand in Houdini; see the usage guide):**
   - `sw_publish_sop`: SOP, wraps a ROP Geometry Output → `publish/<product>/v###/`. Parms: `product`, `ext` (bgeo.sc, vdb, abc, obj), `frames` (one file per frame).
   - `sw_publish_lop`: LOP, wraps a USD ROP with the *Use Relative Paths* output processor (on by default) → `publish/_usd/<layer>/v###/{entity}_{layer}_v###.usd`. Parm: `layer`.
   - `sw_render`: LOP, wraps a USD Render ROP (Karma) → `media/render_<name>/v###/` with its own counter, one `.exr` per frame. Parm: `render_name`.
   - Common parms: `version`, `new_version` (button), `shot` (sequence scenes), `comment`, `output` (the path, Python expression `hda_output`), `execute` (button). The inner ROP's path is `chs("../output")` and its post-render script calls `hda_post_render`, which finalizes the version with `source` = the scene (`version.json`; for USD also the pointer and root layer). The code tells the kinds apart by the `product` / `layer` / `render_name` parm.
7. **Sequence scenes:** in a scene under `_seq/`, publishes and renders target one shot: the node's `shot` parm, else the context option `SW_SHOT` (`sw.set_shot`, or *Edit → Context Options*). Without a shot they raise an error. Output lands in **that shot's** `publish/` / `media/`.
8. **USD stack convention:** a department's scene loads the pointer layers below its own in `usd_layer_order` and publishes only its own layer. `sw.layers_below(layer)` returns the existing ones, strongest first, as `$JOB/…` paths for a Sublayer LOP (stored env-relative, §7.1).
9. **Tests:** `tests/houdini/` runs the integration inside every installed hython (`uv run pytest -m houdini`), loading the package from a temporary `HOUDINI_PACKAGE_DIR`. UI-only parts (menu, shelf, panel, dialogs, clipboard) are checked by hand.

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
│   ├── gui/   app.py browser.py columns.py actions.py dialogs.py theme.qss __main__.py
│   └── dcc/   base.py houdini.py nuke.py blender.py
├── integrations/
│   ├── houdini/  scheinwerk.json  python3.11libs/  python3.13libs/  MainMenuCommon.xml
│   │             toolbar/  python_panels/  otls/
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
| 4 — Houdini | §13.2 | Asset → lookdev → shot → lighting → render loop with no hand-typed paths, including a `_seq` multi-shot hip. |
| 5 — Nuke | §13.3 | A Phase-4 render is comped without typing a path. |
| 6 — Blender | §13.4 | Blender workfiles are versioned and opened like the rest. |
| 7 — Later | launcher (per-project OCIO), deep `doctor`, thumbnails, asset library, rename tool | When actually missed. |
