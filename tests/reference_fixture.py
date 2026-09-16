"""Import pure reference helpers with a test registry, never reading root state."""
import re
import types

def load(path):
    text = path.read_text()
    text, count = re.subn(r"# Only load the reviewed registry reader from a root-owned directory\.\n.*?REGISTRY = _rm.read\(\)\n", "REGISTRY = {'7.2.4-arch1-2': {}, '7.2.5-1-cachyos': {}, '7.2.6-arch2-1': {}}\n", text, flags=re.S)
    if count != 1:
        raise AssertionError('Registry test fixture no longer matches reference')
    module = types.ModuleType('reference_fixture')
    module.__file__ = str(path)
    exec(compile(text, str(path), 'exec'), module.__dict__)
    return module
