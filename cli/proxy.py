import sys
import os as _real_os
import subprocess as _real_subprocess
import socket as _real_socket
import getpass as _real_getpass
import hashlib as _real_hashlib
import json as _real_json
import pathlib as _real_pathlib

class ModuleProxy:
    def __init__(self, name, real_mod):
        self._name = name
        self._real_mod = real_mod

    def __getattr__(self, attr):
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, self._name):
                patched_mod = getattr(ff_cli, self._name)
                return getattr(patched_mod, attr)
        return getattr(self._real_mod, attr)

os = ModuleProxy("os", _real_os)

class SysProxy:
    def __getattr__(self, attr):
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "sys"):
                return getattr(ff_cli.sys, attr)
        return getattr(sys, attr)

sys_proxy = SysProxy()
subprocess = ModuleProxy("subprocess", _real_subprocess)
socket = ModuleProxy("socket", _real_socket)
getpass = ModuleProxy("getpass", _real_getpass)
hashlib = ModuleProxy("hashlib", _real_hashlib)
json = ModuleProxy("json", _real_json)

class PathProxy:
    def __call__(self, *args, **kwargs):
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "Path"):
                return getattr(ff_cli, "Path")(*args, **kwargs)
        return _real_pathlib.Path(*args, **kwargs)

    def __getattr__(self, attr):
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "Path"):
                return getattr(getattr(ff_cli, "Path"), attr)
        return getattr(_real_pathlib.Path, attr)

Path = PathProxy()
