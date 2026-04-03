# GeoBot

GeoBot is a product wrapper for QGIS-assisted geography teaching. It keeps QGIS as the visible professional execution window, adds a local product runtime for project and job management, and hides the underlying orchestration engine behind a private adapter boundary.

## Architecture

The repository now contains three product-facing layers:

- `geoai_agent_plugin/`
  - QGIS plugin that exposes stable mapping and analysis tools over a local socket bridge, including terrain profile and simplified terrain-model outputs for DEM or contour data.
- `geobot_runtime/`
  - Local product runtime that manages projects, jobs, artifacts, outputs, QGIS connectivity, and template execution.
- `geobot_desktop/`
  - Electron desktop shell that talks only to `geobot_runtime` and does not expose orchestration-engine concepts in the UI.

The runtime-facing flow is:

```text
GeoBot Desktop
  -> GeoBot Runtime (HTTP)
  -> Hidden OpenClaw bridge (current transition engine)
  -> qgis-solver / QGIS bridge protocol
  -> QGIS plugin socket
  -> Exported maps and teaching artifacts
```

## Product Goals

- Hide `OpenClaw / agent / skill / session / subagent` terminology from teachers.
- Keep QGIS available as the professional demonstration window.
- Provide a stable product API around projects, jobs, templates, outputs, and health checks.
- Let the desktop shell evolve independently from the hidden orchestration engine.

## Runtime API

`geobot_runtime` exposes a local HTTP API on `127.0.0.1:18999` by default.

- `GET /health`
  - Runtime, QGIS bridge, assistant-engine, and output-path status.
- `GET /templates`
  - Template definitions used by the desktop shell.
- `POST /projects`
  - Create a project context.
- `GET /projects/{project_id}`
  - Read project metadata and linked jobs.
- `POST /chat`
  - Submit a natural-language request. In this build, chat first tries the hidden OpenClaw bridge and falls back to local teaching templates when possible.
- `POST /templates/{template_id}`
  - Execute a standard teaching template directly through QGIS.
- `GET /jobs/{job_id}`
  - Read job status, steps, and result.
- `GET /jobs/{job_id}/stream`
  - Server-sent events stream for job updates.
- `GET /artifacts/{artifact_id}`
  - Read exported artifact metadata.
- `GET /outputs?project_id=...`
  - List exported outputs for a project.
- `POST /qgis/focus`
  - Bring the QGIS window to the foreground.

## Included Teaching Templates

- `population_distribution`
  - Population choropleth map.
- `population_density`
  - Population heatmap or density map.
- `population_migration`
  - Population migration or flow map.
- `hu_line_comparison`
  - Classic Hu Huanyong line versus a line fitted from current data.

## Quick Start

### 1. Install or update the QGIS plugin

Run:

```powershell
.\scripts\install_geobot_plugin.ps1 -Force
```

This copies `geoai_agent_plugin` into the QGIS profile plugin directory.

### 2. Start the runtime

Run:

```powershell
.\scripts\run_geobot_runtime.ps1
```

If you need to override the bind address, use `-RuntimeHost` instead of `-Host` because PowerShell reserves `$Host`.

The runtime will try to detect your existing local OpenClaw installation from `C:\Users\<you>\.openclaw\openclaw.json`.

### 3. Start the desktop shell

Run:

```powershell
cd .\geobot_desktop
npm install
cd ..
.\scripts\run_geobot_desktop.ps1
```

If Python is not on your `PATH`, set `GEOBOT_PYTHON`. If QGIS is installed in a non-standard location, set `GEOBOT_QGIS_EXE`.

For chat-driven execution in this transition build, you also need:

- an existing local OpenClaw installation
- a working `.openclaw\workspace\skills\qgis-solver`
- `npm install` completed inside `geobot_desktop/` so the hidden Electron bridge is available

## Product Runtime Directories

GeoBot uses private runtime directories under `%AppData%\GeoBot\`:

- `runtime/`
- `workspace/`
- `outputs/`
- `logs/`

These directories are separate from `.openclaw` and are intended to be the only product-visible runtime paths.

## Current Scope

Implemented in this repository:

- Product runtime package and local HTTP API
- QGIS bridge client and template executor
- Desktop shell scaffold
- Terrain profile and simplified terrain-model tools in the QGIS plugin
- Project, job, and artifact store
- Hidden OpenClaw bridge with runtime-managed health checks and chat fallback
- Installer and launch scripts

Not finished in this build:

- Replacing OpenClaw with GISclaw as the long-term engine
- Windows installer packaging
- Automatic QGIS plugin update checks
- Complete desktop workflow forms for every template parameter

## Tests

Run:

```powershell
python -m unittest `
  tests.unit.test_service_utils `
  tests.unit.test_session_utils `
  tests.unit.test_geobot_runtime_config `
  tests.unit.test_geobot_runtime_store `
  tests.unit.test_geobot_templates `
  tests.unit.test_openclaw_engine
```

## Requirements

- Windows
- QGIS 3.16+
- Python 3.7+
- Node.js for the Electron shell

## License

MIT License
