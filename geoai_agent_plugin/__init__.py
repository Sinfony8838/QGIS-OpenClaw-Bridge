def classFactory(iface):
    from .geoai_bridge_plugin import GeoaiBridgePlugin
    return GeoaiBridgePlugin(iface)