"""Run WynnBuilder's own JavaScript (QuickJS) to cross-check the Python port.

Used by tests/test_differential.py as a subprocess under Python 3.12, because the
quickjs package has no build for the project's Python version:

    uv run --no-project --python 3.12 --with quickjs \\
        python tests/js/wynnbuilder_harness.py <wynnbuilder_js_dir> < program.js

The program's final expression is printed (return JSON strings).
"""
import sys

import quickjs

SHIM = """
var window = this; var self = this;
var console = {log(){}, warn(){}, error(){}, info(){}};
var navigator = {userAgent: "quickjs", userAgentData: {mobile: false}};
var screen = {width: 1920, height: 1080};
var location = {hash: "", search: "", host: "127.0.0.1", protocol: "http:", pathname: "/builder/"};
window.location = location;
var document = {getElementById(){return null}, createElement(){return {classList:{add(){}}}},
                addEventListener(){}, querySelector(){return null}};
function assert(c, m) { if (!c) throw new Error(m || "assert"); }
"""
FILES = ("js/utils.js", "js/build_utils.js", "js/powders.js", "js/loader.js", "js/load_ing.js",
         "js/craft.js", "js/builder/build_encode_decode.js")
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+-"
# This QuickJS release (2021-03-27) cannot read a class's own static fields inside
# its static initializers, which browsers allow. Inline those values; the
# behaviour is unchanged.
PATCHES = {"js/utils.js": [
    ("Base64.#digitsStr.split('')", f'"{ALPHABET}".split(\'\')'),
    ("Base64.#digits.map(", f'"{ALPHABET}".split(\'\').map('),
    ("Object.fromEntries(BootstringEncoder.#base.map(",
     f'Object.fromEntries("{ALPHABET[:62]}".split(\'\').map('),
    ("static #b = BootstringEncoder.#base.length;", "static #b = 62;"),
]}


def load(ref, files=FILES):
    ctx = quickjs.Context()
    ctx.eval(SHIM)
    for f in files:
        src = open(f"{ref}/{f}").read()
        for old, new in PATCHES.get(f, []):
            assert old in src, f"harness patch no longer applies to {f}: {old}"
            src = src.replace(old, new)
        ctx.eval(src)
    return ctx


if __name__ == "__main__":
    ctx = load(sys.argv[1])
    print(ctx.eval(sys.stdin.read()))
