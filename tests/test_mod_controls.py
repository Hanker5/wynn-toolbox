"""The chest-export mod's click rule (Controls.java), compiled and run against real exports.

Regression: the rule once compared tooltip lines as the game sends them, but Wynncraft
puts an invisible mouse glyph before "Click to go", so no arrow was recognised; the walker
took page 1 for the last page and the app dropped every Account page after it. A Python
copy of the rule had passed (the app's clean() strips that glyph). These tests run the
mod's own Java instead. Skipped without a JDK.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from wynntools.gameimport import clean

ROOT = Path(__file__).parent.parent
CONTROLS = ROOT / "wynn-chest-export" / "src" / "client" / "java" / "com" / "hankryhays" / "wynngptchestexport" / "Controls.java"
EXPORTS = Path(__file__).parent / "fixtures" / "exports"
SEP = "\u001e"

HARNESS = """
import com.hankryhays.wynngptchestexport.Controls;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

public class Harness {
    public static void main(String[] args) throws Exception {
        String text = Files.readString(Path.of(args[0]), StandardCharsets.UTF_8);
        StringBuilder out = new StringBuilder();
        for (String record : text.split("\\u001e\\n", -1)) {
            if (record.isEmpty()) continue;
            List<String> lines = new ArrayList<>(List.of(record.split("\\n", -1)));
            String name = lines.remove(0);
            out.append(Controls.arrow(name, lines, ">")).append('\\t')
               .append(Controls.arrow(name, lines, "<")).append('\\t')
               .append(Controls.isSwitch(name, lines)).append('\\t')
               .append(Controls.unreadableArrow(name, lines)).append('\\t')
               .append(Controls.clean(name)).append('\\n');
        }
        Files.writeString(Path.of(args[1]), out.toString(), StandardCharsets.UTF_8);
    }
}
"""


@pytest.fixture(scope="module")
def controls(tmp_path_factory):
    javac = shutil.which("javac")
    if javac is None:
        pytest.skip("no JDK (javac) to compile the mod's Controls.java")
    java = str(Path(javac).with_name("java"))
    out = tmp_path_factory.mktemp("controls")
    (out / "Harness.java").write_text(HARNESS, encoding="utf-8")
    subprocess.run([javac, "-encoding", "UTF-8", "-d", str(out), str(CONTROLS), str(out / "Harness.java")],
                   check=True, capture_output=True)

    def run(slots):
        """[(name, lore)] -> [{"next", "previous", "switch", "unreadable", "clean"}] from the Java."""
        src, dst = out / "in.txt", out / "out.txt"
        src.write_text("".join("\n".join([name, *lore]) + f"{SEP}\n" for name, lore in slots), encoding="utf-8")
        subprocess.run([java, "-cp", str(out), "Harness", str(src), str(dst)], check=True, capture_output=True)
        rows = []
        for line in dst.read_text(encoding="utf-8").splitlines():
            nxt, prev, switch, unreadable, name = line.split("\t")
            rows.append({"next": None if nxt == "null" else int(nxt), "previous": None if prev == "null" else int(prev),
                         "switch": switch == "true", "unreadable": unreadable == "true", "clean": name})
        return rows
    return run


def slots(export):
    storage = json.loads((EXPORTS / export).read_text(encoding="utf-8"))["storage"]
    return {s["slot"]: (s["name"], s.get("lore") or []) for s in storage}


def test_real_arrows_and_the_switch_are_recognised(controls):
    p7, last, p1 = slots("account-p7.json"), slots("account-p14-last.json"), slots("account-p1.json")
    back, ahead, buy, prev13, switch, dump, first_next = controls(
        [p7[51], p7[52], last[52], last[51], p1[47], p1[46], p1[52]])
    assert back["previous"] == 6 and ahead["next"] == 8 and first_next["next"] == 2
    assert buy["next"] is None and not buy["unreadable"]         # the offer to buy page 15: never clicked
    assert prev13["previous"] == 13
    assert switch["switch"] and not dump["switch"] and dump["next"] is None and dump["previous"] is None


def test_an_arrow_it_cannot_read_is_not_taken_for_the_last_page(controls):
    odd, = controls([("§f§lPage 9§a >§2>§a>§2>§a>", ["", "Something new"])])
    assert odd["next"] is None and odd["unreadable"]


def test_the_mod_cleans_text_as_the_app_does(controls):
    lines = []
    for f in EXPORTS.glob("*.json"):
        for s in json.loads(f.read_text(encoding="utf-8"))["storage"]:
            lines += [s["name"], *(s.get("lore") or [])]
    lines = [x for x in dict.fromkeys(lines) if x and "\n" not in x]
    got = controls([(x, []) for x in lines])
    assert [r["clean"] for r in got] == [clean(x) for x in lines]
