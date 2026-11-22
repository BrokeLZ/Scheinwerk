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
│           ├── entity.json               # optional
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
│   └── templates/                        # optional empty workfile templates per extension
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
- No comments in filenames.
- Versions are written with 3 digits. Readers accept `v[0-9]{3,}` (ASCII digits only, v1000+ keeps working). Uppercase `V001` is not a version.
- Frames are 4-digit and start at 1001 by default.

### 5.4 Versioning

| What | Counter scope | Next version |
| --- | --- | --- |
| Workfiles | one per task, shared across all extensions/DCCs | max version of all managed files in `work/` + 1 |
| Products, USD layers | one per product / layer | max `v###` folder + 1 |
| Media | one per media name, independent of workfiles | max `v###` folder + 1 |

- "Latest" = highest version number. For USD layers, the *current* version is the one the pointer references, which can differ after "Set as latest".
- Creating a version folder uses `mkdir(exist_ok=False)`. On collision, increment and retry, so two DCCs exporting at once can't share a folder.
- An empty version folder (no files besides `version.json`) is ignored by "latest" lookups.

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

1. Find the root (§2.3). If none is found, `Context.from_path()` returns `None`.
2. Split the root-relative path into parts.
3. `assets/…`: if `parts[2]` is a department name, a reserved area (`publish`, `media`) or `entity.json`, then `parts[1]` is the asset with no category. Otherwise `parts[1]` is the category and `parts[2]` the asset.
4. `shots/<seq>/_seq/…` → entity_type `sequence`, entity = `<seq>`. `shots/<seq>/<shot>/…` → entity_type `shot`.
5. After the entity: `<dept>/<task>/work|cache/…` or `publish/[_usd/]<name>/v###/…` or `media/<name>/v###/…`.
6. Version and extension come from the filename (workfiles) or the `v###` folder (products/media).
7. Context is read from **folders**. The filename prefix is redundant and is not trusted for context. This is why product names may contain underscores.
8. Parsing works for paths that don't exist yet (needed for "next version" paths).

Round-trip requirement: `format(parse(p)) == p` for every path the core generates. This is the main test suite.

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

### 7.3 OCIO

One OCIO config for all projects, configured per machine (the `OCIO` env var in the OS or the Houdini package). Scheinwerk does not manage OCIO in v1.

---

## 8. JSON files

All JSON is UTF-8, indented with 2 spaces and written atomically (write `*.tmp` in the same folder, then `os.replace`). Every file has an integer `schema`. Unknown keys are preserved on rewrite.

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
- `usd_layer_order`: strongest first, used for the shot root layer.
- `templates`: optional overrides of §5.2/§5.3 patterns, keyed by template name. Empty = defaults.

### 8.2 `entity.json` (entity folder, optional)

```json
{ "schema": 1, "frames": [1001, 1096] }
```

Optional overrides: `fps`, `resolution`. Sequences have no `entity.json`; their range is derived from their shots.

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

All fields are optional. Readers must never require this file.

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

An extension with no entry opens with the OS default application.

---

## 9. Publishing

### 9.1 Generic product / media

1. `next_publish(entity, name)` / `next_media(entity, name)` → creates and returns `…/<name>/v###/` (§5.4).
2. The DCC (or the user via its own dialog) writes files into it.
3. Optional `finalize(version_dir, source=…, comment=…)` → writes `version.json`.

### 9.2 USD layer

1. `next_usd(entity, layer)` → `publish/_usd/<layer>/v###/`.
2. Export (Houdini USD ROP with the *Use Relative Paths* output processor).
3. `finalize(…)` → writes `version.json`, then **as the last step** atomically rewrites the pointer layer.
4. The asset entry layer (`<asset>.usd`) and the shot root layer (`<shot>.usd`) are created when the first layer is published and updated when a new layer name appears.

Pointer layer format (ASCII content in a `.usd` file, written as plain text by the core, no `pxr` needed):

```text
#usda 1.0
(
    defaultPrim = "hero"
    subLayers = [@./v003/hero_asset_v003.usd@]
)
```

`defaultPrim` is always written (= entity name). Without it, references to the pointer fail. The pointer targets the main `.usd` file in the version folder. If that is ambiguous, `finalize` takes an explicit `main_file` argument.

Shot root layer: sublayers `./<layer>/<layer>.usd` for every existing layer, ordered by `usd_layer_order`, with `defaultPrim` unset (shot layers are sublayered or opened, not referenced).

"Set as latest" on any USD version rewrites the pointer to that version. That is the only form of pinning/rollback.

### 9.3 Ingest

`ingest(files, target)` copies files into the next workfile version (renamed to the template) or into the next product/media version folder (names kept). It never moves or deletes the originals.

### 9.4 Sync safety (Synology Drive)

- Pointer layers and `version.json` are written last, atomically, so the other machine never syncs a pointer to a version that hasn't arrived yet.
- `cache/` should be excluded from sync (Synology Drive file filter). Documented, not enforced.

---

## 10. Core API (`scheinwerk.core`)

Stdlib only. Paths are `pathlib.Path` at runtime and root-relative POSIX `str` when persisted.

```python
# templates.py
validate_name(kind, name, *, seq=None) -> None   # kind: category asset sequence shot dept task product media layer
shot_sequence(shot) -> str                       # "sq010_0010" -> "sq010"
format_version(n) -> str / parse_version(text) -> int | None
format_workfile(entity, dept, task, version, ext) -> str
parse_workfile(filename, entity, dept, task) -> tuple[int, str] | None   # None = unmanaged

# project.py
find_root(path) -> Path | None
Project.find(path) -> Project | None
Project.create(folder, name, **settings) -> Project
project.config -> dict                      # parsed scheinwerk.json
project.assets() -> list[Asset]             # filesystem scan, sorted
project.sequences() -> list[Sequence]
project.shots(seq=None) -> list[Shot]
project.entity(name) -> Asset | Shot | Sequence   # resolves by unique name
project.rel(path) -> str                    # root-relative POSIX
project.abs(rel) -> Path

# context.py
Context.from_path(path) -> Context | None
context.path() -> Path                      # inverse of from_path

# entities.py  (thin, path-backed; no cached state)
Asset / Shot / Sequence:
    .name .path .category .frames
    .departments() -> list[Department]
    .create_department(name, tasks=("main",))
    .products(usd=None) -> list[Product]
    .media() -> list[Product]
Department: .tasks() .create_task(name)
Task:
    .workfiles() -> list[Workfile]          # newest first
    .unmanaged() -> list[Path]
    .latest_workfile(ext=None) -> Workfile | None
    .next_workfile(ext) -> Path
    .new_version_from(workfile) -> Path     # copy + bump
    .new_empty_workfile(ext) -> Path        # from shared/templates/ if present

# versions.py
Product: .name .usd .versions() .latest() .next_version_dir() -> Path
Version: .number .path .info -> dict | None   # version.json

# publish.py
next_publish(entity, name) -> Path
next_media(entity, name) -> Path
next_usd(entity, layer) -> Path
finalize(version_dir, *, source=None, comment="", main_file=None, dcc=None) -> None
set_current(usd_version_dir) -> None        # rewrite pointer
ingest(files, target) -> list[Path]

# env.py
env_for(context) -> dict[str, str]

# hooks.py
run_hook(name, **kwargs) -> None            # see §14

# usd_pointer.py
write_pointer(path, target_rel, default_prim) -> None
write_root_layer(path, sublayers, default_prim=None) -> None
```

Errors: core functions raise `ScheinwerkError` subclasses (`NotInProject`, `InvalidName`, `ParseError`) with messages that can be shown to the user. They never call `sys.exit` or print.

---

## 11. CLI (`sw`)

argparse, entry point `sw`. Context defaults to the current directory, like git. Every command that prints a path accepts `--relative` and `--json`.

```text
sw init [name]                              # create scheinwerk.json in cwd
sw new asset [category/]hero
sw new seq sq010
sw new shot sq010_0010 --frames 1001-1096   # creates sequence folder if needed
sw new dept <entity> <dept> [--tasks main]
sw new task <entity> <dept> <task>
sw new product <entity> <name>
sw ls [entity] [dept[/task]]
sw next <entity> <dept>/<task> --ext hip    # next workfile path
sw next-publish <entity> <name>             # creates + prints next version folder
sw next-usd <entity> <layer>
sw next-media <entity> <name>
sw latest <entity> (--product N | --media N | --work dept/task)
sw finalize <version_dir> [-m comment] [--source path] [--main file]
sw set-current <usd_version_dir>
sw ingest <files...> <entity> (<dept>/<task> | --product N | --media N)
sw context <path>                           # parse and print context
sw env <path> [--shell zsh|bash|pwsh]
sw doctor [--fix-names]                     # naming violations, conflict copies,
                                            # absolute paths in .usd/.usda/.nk, empty versions
sw gui [path]
```

Entity arguments resolve by unique name (`hero`, `sq010_0010`, `sq010`). If a name is ambiguous, use the prefixes `asset:`, `shot:` or `seq:`.

---

## 12. GUI

PySide6. The GUI holds no logic: every action is one core call. Widgets are `QWidget`s (not `QMainWindow`), so Houdini and Nuke can dock them.

### 12.1 Layout

```text
┌──────────────────────────────────────────────────────────────────────────┐
│          [Scenefiles] [Products] [Media]      [ project ▾ ] [?] [+] [Reload] │ ← top bar, fixed
├─────────────────┬──────────────┬──────────────┬───────────────────────────┤
│ [Assets][Shots] │ Column 2     │ Column 3     │ Column 4                  │
│ entity tree     │              │              │                           │
│                 ├──────────────┴──────────────┤                           │
│                 │ Detail panel                │                           │
└─────────────────┴─────────────────────────────┴───────────────────────────┘
```

- **Top bar** is identical in every view: view switch, project dropdown (recent projects), `?` (shortcuts/help), `+` (new project / add existing project), Reload.
- **Entity column** is the same in every view: Assets/Shots toggle above a tree. Assets are grouped by category if present. Shots are grouped by sequence, and each sequence's `_seq` level is its first child, labelled `<seq> (sequence)`.
- All columns have type-to-filter. Columns are separated by splitters.

| View | Column 2 | Column 3 | Column 4 | Detail panel |
| --- | --- | --- | --- | --- |
| Scenefiles | Departments | Tasks | Workfiles, newest first (+ unmanaged, dimmed) | path, latest version, frame range |
| Products | Products (`_usd` layers grouped first) | Versions | Files in version | source workfile, comment, date; current marker for USD |
| Media | Media names | Versions | Files / frame range summary | source, comment, date |

- A department with exactly one task selects it automatically.
- Selection is remembered per view while the app runs.

### 12.2 Actions — right-click only (no bottom buttons)

| Where | Menu |
| --- | --- |
| Entity column | New asset · New category · New sequence · New shot · Set frame range · Copy path · Copy relative path · Reveal |
| Departments | New department ▸ (template entries + Custom…) · Copy path · Reveal |
| Tasks | New task · Copy path · Reveal |
| Workfiles (file) | Open · Open with ▸ · New version from this · Copy path · Copy relative path · Reveal |
| Workfiles (empty space or file) | New empty workfile ▸ (ext) · **Copy next version path ▸ (ext)** · Ingest file(s)… |
| Products / Media list | New product… / New media… (name prompt) · **Copy next version folder** · Ingest file(s)… · Copy path · Reveal |
| Versions | Open folder · Finalize / Edit comment · Set as current (USD) · Copy path · Copy relative path · Reveal |

Other interactions:

- Double-click = open (workfile) or reveal (version).
- Drag files from Finder/Explorer onto a task → ingest as next workfile. Onto a product/media → ingest as next version.
- F5 = Reload, plus an automatic refresh when the window regains focus.

### 12.3 Styling

All colours, fonts and spacing live in one QSS file (`gui/theme.qss`), with a monospace UI font. The look follows the user's reference mock-up (flat panels, warm palette). No hard-coded colours in widget code.

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

1. **Package** `integrations/houdini/scheinwerk.json` → adds the repo to `PYTHONPATH` and `HOUDINI_PATH` (toolbar, otls, python3.11libs).
2. **Scene callbacks** (`hou.hipFile.addEventCallback`): on load / after save-as → set env + `$JOB`. If the frame range differs from `entity.json`, ask before applying it.
3. **Menu + shelf:** Save next version (Ctrl+Alt+S), Open Scheinwerk browser (docked Python panel), Copy context path.
4. **Expression helpers** (`import scheinwerk.dcc.houdini as sw`): `sw.cache(name)`, `sw.publish_path(product, ext)`, `sw.usd_path(layer)`, `sw.media_path(name, ext)`, `sw.shots()` (shots of the current sequence with frame ranges).
5. **HDAs (two only):**
   - `sw_publish_lop`: USD ROP with the *Use Relative Paths* output processor. Writes to `next_usd`, calls `finalize` post-render. Parms: layer name, comment, target shot (sequence context).
   - `sw_publish_sop`: file cache writing to `next_publish`, finalize post-render. Parms: product name, comment, target shot (sequence context).
6. **Render output:** Karma/husk to `media/render_<name>/v###/` with an independent counter. Source hip in `version.json`.
7. **Sequence workfiles:** a hip in `_seq/` exposes `sw.shots()` and a shot menu (context options) in Solaris. Every publish/render from it targets one specific shot and lands in **that shot's** `publish/` / `media/`.
8. **USD stack convention:** a department's hip loads the pointer layers below it in `usd_layer_order` and publishes only its own layer.

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

No integration needed: "Copy next version path" → Save As; "Copy next version folder" → export; optional Finalize in the GUI; ingest for tools that write elsewhere.

---

## 14. Hooks

- Locations: `<project>/shared/hooks/*.py` and `<user settings dir>/hooks/*.py`. Both are loaded, project first.
- A hook is a module-level function with a known name. v1 names:
  - `post_create(kind, path, context)`, where kind is one of `asset`, `shot`, `sequence`, `dept`, `task`, `product`
  - `post_save(path, context)`, called by integrations after Save next version
  - `post_publish(version_dir, context)`, called after `finalize`
- Exceptions inside hooks are caught and logged, and never block the action.
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
│   │          publish.py env.py hooks.py usd_pointer.py errors.py
│   ├── cli.py
│   ├── gui/   app.py browser.py columns.py actions.py dialogs.py theme.qss
│   └── dcc/   base.py houdini.py nuke.py blender.py
├── integrations/
│   ├── houdini/  scheinwerk.json  python3.11libs/  toolbar/  otls/
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
- GUI and DCC code are tested manually. Keep them thin enough that this is acceptable.

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
