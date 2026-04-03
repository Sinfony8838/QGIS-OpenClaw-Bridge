# GeoAI Bridge - QGIS AI Automation Plugin

A plugin that connects AI agents with QGIS through Socket communication, enabling AI-driven GIS workflows.

GeoAI Agent Console is designed to bridge the gap between LLM intelligence and professional GIS execution. By exposing QGIS as a standardized 'Skill' for OpenClaw, it enables seamless, cross-process automation. No complex environment setup is required: users can gain full control over PyQGIS algorithms and map production through simple plugin installation and socket-based skill sets.

## Key Features

⚡ **Native OpenClaw Integration**: Pre-configured with qgis-solver skill set. OpenClaw agents gain complete geographic analysis capabilities immediately upon loading.

> **Note**: This project currently implements a limited set of QGIS tools and is continuously expanding. Contributions and feature requests are welcome!

## Project Structure

```
QGIS-GeoAI-Bridge/
├── geoai_agent_plugin/     # QGIS Plugin
│   ├── __init__.py
│   ├── geoai_bridge_plugin.py    # Plugin main entry
│   ├── geoai_dock_widget.py       # Plugin UI
│   ├── geoai_socket_server.py     # Socket server
│   └── metadata.txt               # Plugin metadata
│
└── qgis-solver/            # OpenClaw Agent Skill
    ├── SKILL.md             # Skill documentation
    ├── references/
    │   └── tools.md         # Tool reference
    └── scripts/
        └── qgis_client.py   # Python client
```

## Features

- **Socket Communication**: QGIS plugin runs as server (port 5555), AI agents connect via TCP
- **Layer Management**: Get layers, add layers, reorder layers
- **Style Configuration**: Single symbol rendering, categorized rendering, canvas background color
- **Spatial Analysis**: Execute QGIS Processing algorithms (buffer, clip, merge, etc.)
- **Map Navigation**: Zoom to layer, fly-to animations
- **Automated Cartography**: Auto-layout, export to PNG/JPG/PDF

## Quick Start

### 1. Install QGIS Plugin

1. Open QGIS → Plugins → Manage and Install Plugins
2. Select "Install from ZIP" and choose `geoai_agent_plugin.zip`
3. After installation, find **GeoAI Agent Console** in the menu bar or toolbar
4. Click to activate the plugin (Socket server will start automatically)

> **Default Port:** 5555

### 2. Configure OpenClaw (Optional)

If you use OpenClaw as your AI agent, you can use the `qgis-solver` skill directly.

## Available Commands

| Command | Description |
|---------|-------------|
| `get_layers` | Get all layer list |
| `set_style` | Set layer symbology |
| `set_background_color` | Set canvas background color |
| `run_algorithm` | Execute QGIS Processing algorithm |
| `fly_to` | Fly to specified coordinates |
| `zoom_to_layer` | Zoom to specified layer |
| `update_banner` | Show toast message |
| `auto_layout` | Create map layout |
| `export_map` | Export map to image/PDF |
| `add_layer_from_path` | Add layer from file path |

## Usage Examples

### Python Client

```python
from qgis_client import qgis_client

# Get layers
layers = qgis_client.get_layers()

# Zoom to layer
qgis_client.zoom_to_layer(layer_name="roads")

# Set style
qgis_client.set_style(
    layer_name="roads",
    style_type="single",
    color="#00FF00",
    width="0.3"
)

# Buffer analysis
qgis_client.run_algorithm(
    algorithm_id="qgis:buffer",
    params={"INPUT": "roads", "DISTANCE": 50, "OUTPUT": "memory:"}
)

# Export map
qgis_client.export_map("C:/Users/Public/output.png")
```

### Categorized Rendering

```python
qgis_client.set_style(
    layer_name="points",
    style_type="categorized",
    column="color",
    categories={
        "red": "#FF0000",
        "blue": "#0000FF",
        "green": "#00FF00"
    }
)
```

## Requirements

- QGIS 3.16+
- Python 3.7+
- OpenClaw (optional, for AI agent)

## How to Cite

This project is developed and maintained by **Chengyi Zhang (张程祎)**.

If you use this project in academic papers, research projects, or commercial products, please cite as follows:

> Zhang, C. (2026). GeoAI Agent Console: A Bridge for LLM Agents and Professional GIS. GitHub Repository: https://github.com/Sinfony8838/GeoAI-Bridge

## License

MIT License
