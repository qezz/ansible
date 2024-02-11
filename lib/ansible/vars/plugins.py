# Copyright (c) 2018 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import os

from functools import lru_cache

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.inventory.group import InventoryObjectType
from ansible.plugins.loader import vars_loader
from ansible.utils.display import Display
from ansible.utils.vars import combine_vars

display = Display()


def _prime_vars_loader():
    # find 3rd party legacy vars plugins once, and look them up by name subsequently
    list(vars_loader.all(class_only=True))
    for plugin_name in C.VARIABLE_PLUGINS_ENABLED:
        if not plugin_name:
            continue
        vars_loader.get(plugin_name)


def get_plugin_vars(loader, plugin, path, entities):
    import json
    import sys
    print(f"plugins::get_plugin_vars", file=sys.stderr)
    print(f"plugins::get_plugin_vars: path: {path}", file=sys.stderr)
    print(f"plugins::get_plugin_vars: plugin: {plugin.ansible_name}", file=sys.stderr)

    data = {}
    try:
        print(f"plugins::get_plugin_vars::try: get_vars: path: {path}", file=sys.stderr)
        data = plugin.get_vars(loader, path, entities)
        _keys = list(data.keys())
        print(f"plugins::get_plugin_vars::try: get_vars: keys: {_keys}", file=sys.stderr)
    except AttributeError:
        if hasattr(plugin, 'get_host_vars') or hasattr(plugin, 'get_group_vars'):
            display.deprecated(
                f"The vars plugin {plugin.ansible_name} from {plugin._original_path} is relying "
                "on the deprecated entrypoints 'get_host_vars' and 'get_group_vars'. "
                "This plugin should be updated to inherit from BaseVarsPlugin and define "
                "a 'get_vars' method as the main entrypoint instead.",
                version="2.20",
            )
        try:
            for entity in entities:
                if entity.base_type is InventoryObjectType.HOST:
                    data |= plugin.get_host_vars(entity.name)
                else:
                    data |= plugin.get_group_vars(entity.name)
        except AttributeError:
            if hasattr(plugin, 'run'):
                raise AnsibleError("Cannot use v1 type vars plugin %s from %s" % (plugin._load_name, plugin._original_path))
            else:
                raise AnsibleError("Invalid vars plugin %s from %s" % (plugin._load_name, plugin._original_path))
    return data


# optimized for stateless plugins; non-stateless plugin instances will fall out quickly
@lru_cache(maxsize=10)
def _plugin_should_run(plugin, stage):
    # if a plugin-specific setting has not been provided, use the global setting
    # older/non shipped plugins that don't support the plugin-specific setting should also use the global setting
    allowed_stages = None

    try:
        allowed_stages = plugin.get_option('stage')
    except (AttributeError, KeyError):
        pass

    if allowed_stages:
        return allowed_stages in ('all', stage)

    # plugin didn't declare a preference; consult global config
    config_stage_override = C.RUN_VARS_PLUGINS
    if config_stage_override == 'demand' and stage == 'inventory':
        return False
    elif config_stage_override == 'start' and stage == 'task':
        return False
    return True


def get_vars_from_path(loader, path, entities, stage):
    import json
    import sys
    data = {}
    if vars_loader._paths is None:
        # cache has been reset, reload all()
        _prime_vars_loader()

    for plugin_name in vars_loader._plugin_instance_cache:
        if (plugin := vars_loader.get(plugin_name)) is None:
            continue

        collection = '.' in plugin.ansible_name and not plugin.ansible_name.startswith('ansible.builtin.')
        # Warn if a collection plugin has REQUIRES_ENABLED because it has no effect.
        if collection and (hasattr(plugin, 'REQUIRES_ENABLED') or hasattr(plugin, 'REQUIRES_WHITELIST')):
            display.warning(
                "Vars plugins in collections must be enabled to be loaded, REQUIRES_ENABLED is not supported. "
                "This should be removed from the plugin %s." % plugin.ansible_name
            )

        if not _plugin_should_run(plugin, stage):
            continue

        if (new_vars := get_plugin_vars(loader, plugin, path, entities)) != {}:
            print(f"plugins::get_vars_from_path::if", file=sys.stderr)
            print(f"plugins::get_vars_from_path: path: {path}", file=sys.stderr)
            print(f"plugins::get_vars_from_path: plugin: {plugin.ansible_name}", file=sys.stderr)
            # print(f"base:\n{json.dumps([data.keys()], indent=2)}\n\n", file=sys.stderr)
            # print(f"new_vars:\n{json.dumps([new_vars.keys()], indent=2)}", file=sys.stderr)
            print(f"\n", file=sys.stderr)

            data = combine_vars(data, new_vars)

    return data


def get_vars_from_inventory_sources(loader, sources, entities, stage):
    import json
    import sys
    _sources = json.dumps(sources, indent=2)
    # _entities = json.dumps(entities, indent=2)
    print(f"plugins::get_vars_from_inventory_sources", file=sys.stderr)
    print(f"stage: {stage}", file=sys.stderr)
    print(f"sources:\n{_sources}", file=sys.stderr)
    print(f"entities:", file=sys.stderr) # \n{_entities}", file=sys.stderr)
    for entity in entities:
        print(f"  {entity}", file=sys.stderr)

    data = {}
    for path in sources:
        # print(f"  path: {path}", file=sys.stderr)

        if path is None:
            continue
        if ',' in path and not os.path.exists(path):  # skip host lists
            continue
        elif not os.path.isdir(path):
            # always pass the directory of the inventory source file
            path = os.path.dirname(path)

        if (new_vars := get_vars_from_path(loader, path, entities, stage)) != {}:
            # print(f"base:\n{json.dumps(data, indent=2)}\n\n", file=sys.stderr)
            # print(f"new_vars:\n{json.dumps(new_vars, indent=2)}", file=sys.stderr)
            # print(f"\n", file=sys.stderr)
            data = combine_vars(data, new_vars)
            _vars = json.dumps(data, indent=2)
            # print(f"if: data:\n{_vars}", file=sys.stderr)
            print("loaded: keys: ", list(data.keys()), file=sys.stderr)
            raise Exception("stop")

    print(f"return:  data:\n{json.dumps(data, indent=2)}", file=sys.stderr)
    return data
