from core.kernel.plugin_sdk import XiaoYiPluginAPI


def activate(api: XiaoYiPluginAPI) -> None:
    api.log_access("activate", {})
    api.emit_event("plugin.activated", {"plugin_id": api.plugin_id})