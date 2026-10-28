"""catalog loading: base images, path tools, recipes, rices.

catalog files are the json drafts in spec/schemas/ made concrete; this module
loads a catalog directory and answers the questions the order form asks.
"""
import json
from pathlib import Path

KINDS = ("base-images", "path-tools", "recipes", "rices", "services")


class Catalog:
    def __init__(self, root):
        self.root = Path(root)
        self.base_images = {}
        self.path_tools = {}
        self.recipes = {}
        self.rices = {}
        self.services = {}
        for kind in KINDS:
            table = getattr(self, kind.replace("-", "_"))
            d = self.root / kind
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.json")):
                entry = json.loads(f.read_text())
                key = (entry.get("id") or entry.get("recipe_id")
                       or entry.get("rice_id") or entry.get("service_id") or f.stem)
                table[key] = entry

    def image(self, order):
        return self.base_images.get(order.base_image)

    def recipe(self, app_order):
        return self.recipes.get(app_order.recipe_id)

    def rice(self, order):
        if not order.rice:
            return None
        return self.rices.get(order.rice.get("rice_id"))

    def order_types_for(self, recipe, os_name):
        return recipe.get("availability", {}).get(os_name, [])

    def native_steps(self, recipe, family):
        return recipe.get("orders", {}).get("native", {}).get(family)

    def pwa(self, recipe):
        return recipe.get("orders", {}).get("pwa")

    def tool_install(self, tool_id, family):
        tool = self.path_tools.get(tool_id)
        if tool is None:
            return None
        return tool.get("installs", {}).get(family)
