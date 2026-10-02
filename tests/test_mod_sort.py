"""The chest-export mod's sorting (SortSteps.java), compiled and run against plans the app
makes, on a simulated chest whose clicks behave like the game's: each click trades the slot
and the cursor. Checks that the Java carries out every plan to the end, and that it stops,
with nothing left on the cursor, as soon as the chest isn't what the plan expects.
Skipped without a JDK."""
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from wynntools import storagesort as ss
from wynntools.inventory import Inventory

ROOT = Path(__file__).parent.parent
SRC = ROOT / "wynn-chest-export" / "src" / "client" / "java" / "com" / "hankryhays" / "wynngptchestexport"

HARNESS = r"""
import com.hankryhays.wynngptchestexport.SortSteps;
import com.hankryhays.wynngptchestexport.SortSteps.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import com.hankryhays.wynngptchestexport.SortSteps.Stack;

public class SortHarness {
    static Map<Integer, Map<Integer, Stack>> chest = new TreeMap<>();
    static Map<Integer, Stack> inv = new TreeMap<>();
    static Stack cursor;
    static int page, pages;

    static Stack stack(String sig, String count) {
        return sig.equals("-") ? null : new Stack(sig, Integer.parseInt(count), sig);
    }

    public static void main(String[] args) throws Exception {
        List<Step> steps = new ArrayList<>();
        Map<Integer, String[]> disturb = new HashMap<>();
        int reserve = -1;
        for (String line : Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8)) {
            String[] f = line.split("\t");
            switch (f[0]) {
                case "SIG" -> { System.out.println(SortSteps.sig(f[1], f[2], List.of(Arrays.copyOfRange(f, 3, f.length)))); return; }
                case "START" -> { page = Integer.parseInt(f[1]); pages = Integer.parseInt(f[2]); reserve = Integer.parseInt(f[3]); }
                case "CHEST" -> chest.computeIfAbsent(Integer.parseInt(f[1]), k -> new TreeMap<>()).put(Integer.parseInt(f[2]), stack(f[3], f[4]));
                case "INV" -> inv.put(Integer.parseInt(f[1]), stack(f[2], f[3]));
                case "PAGE" -> steps.add(new Page(Integer.parseInt(f[1]), new HashMap<>()));
                case "EXPECT" -> ((Page) steps.get(steps.size() - 1)).expect().put(Integer.parseInt(f[1]), stack(f[2], f[3]));
                case "CLICK" -> steps.add(new Click(f[1].equals("chest"), Integer.parseInt(f[2]), stack(f[3], f[4]), stack(f[5], f[6])));
                case "DISTURB" -> disturb.put(Integer.parseInt(f[1]), f);
                default -> throw new IllegalArgumentException(line);
            }
        }
        SortSteps sort = new SortSteps(steps);
        View view = new View() {
            public Integer page() { return page; }
            public Stack chest(int slot) { return chest.getOrDefault(page, Map.of()).get(slot); }
            public Stack inventory(int slot) { return inv.get(slot); }
            public Stack cursor() { return cursor; }
        };
        StringBuilder out = new StringBuilder();
        int waits = 0, clicks = 0, turns = 0;
        while (true) {
            String[] d = disturb.remove(sort.done());
            if (d != null) {            // the player (or the game) takes an item away mid-sort
                chest.getOrDefault(Integer.parseInt(d[2]), new TreeMap<>()).remove(Integer.parseInt(d[3]));
            }
            Action a = sort.next(view);
            if (a instanceof Wait w) {
                if (++waits > 3) { out.append("STOP\tstuck: ").append(sort.problem(view)).append('\n'); break; }
                continue;
            }
            waits = 0;
            if (a instanceof Done) { out.append("DONE\n"); break; }
            if (a instanceof Stop s) { out.append("STOP\t").append(s.why()).append('\n'); break; }
            if (a instanceof TurnPage t) {
                page += t.next() ? 1 : -1;
                turns++;
                if (page < 1 || page > pages) throw new IllegalStateException("turned past the chest");
                continue;
            }
            clicks++;
            if (a instanceof ClickChest c) click(chest.computeIfAbsent(page, k -> new TreeMap<>()), c.slot());
            else click(inv, ((ClickInventory) a).slot());
        }
        Action r;
        int rescues = 0;
        while ((r = SortSteps.rescue(view, reserve)) != null && rescues++ < 3) {
            if (r instanceof ClickChest c) click(chest.computeIfAbsent(page, k -> new TreeMap<>()), c.slot());
            else click(inv, ((ClickInventory) r).slot());
        }
        out.append("CLICKS\t").append(clicks).append('\t').append(turns).append('\n');
        chest.forEach((p, slots) -> slots.forEach((s, st) -> out.append("CHEST\t").append(p).append('\t').append(s)
            .append('\t').append(st.sig()).append('\t').append(st.count()).append('\n')));
        inv.forEach((s, st) -> { if (st != null) out.append("INV\t").append(s).append('\t').append(st.sig()).append('\t').append(st.count()).append('\n'); });
        out.append("CURSOR\t").append(cursor == null ? "-" : cursor.sig()).append('\n');
        Files.writeString(Path.of(args[1]), out.toString(), StandardCharsets.UTF_8);
    }

    static void click(Map<Integer, Stack> box, int slot) {
        Stack here = box.get(slot);
        if (here != null && cursor != null && here.sig().equals(cursor.sig())) throw new IllegalStateException("merged");
        if (cursor == null) box.remove(slot); else box.put(slot, cursor);
        cursor = here;
    }
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    javac = shutil.which("javac")
    if javac is None:
        pytest.skip("no JDK (javac) to compile the mod's SortSteps.java")
    java = str(Path(javac).with_name("java"))
    out = tmp_path_factory.mktemp("sort")
    (out / "SortHarness.java").write_text(HARNESS, encoding="utf-8")
    subprocess.run([javac, "-encoding", "UTF-8", "-d", str(out), str(SRC / "SortSteps.java"), str(SRC / "Controls.java"),
                    str(out / "SortHarness.java")], check=True, capture_output=True)

    def run(lines):
        src, dst = out / "in.txt", out / "out.txt"
        dst.unlink(missing_ok=True)
        src.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        done = subprocess.run([java, "-cp", str(out), "SortHarness", str(src), str(dst)],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return dst.read_text(encoding="utf-8").splitlines() if dst.exists() else done.stdout.splitlines()
    return run


def _stack(v):
    return ["-", "0"] if v is None else [v[0], str(v[1])]


def _lines(pl, pages, start, n_pages, disturb=()):
    lines = [f"START\t{start}\t{n_pages}\t{pl['reserve']}"]
    for p, slots in pages.items():
        lines += [f"CHEST\t{p}\t{s}\t{v[0]}\t{v[1]}" for s, v in slots.items()]
    for step in pl["steps"]:
        if step["op"] == "page":
            lines.append(f"PAGE\t{step['page']}")
            lines += [f"EXPECT\t{e[0]}\t{e[1]}\t{e[2]}" for e in step["expect"]]
        else:
            lines.append("\t".join(["CLICK", step["area"], str(step["slot"]), *_stack(step["slot_has"]),
                                    *_stack(step["cursor_has"])]))
    lines += ["\t".join(["DISTURB", *map(str, d)]) for d in disturb]
    return lines


def _result(out):
    chest, inv, status, cursor = {}, {}, None, None
    for line in out:
        f = line.split("\t")
        if f[0] in ("DONE", "STOP"):
            status = f
        elif f[0] == "CHEST":
            chest.setdefault(int(f[1]), {})[int(f[2])] = (f[3], int(f[4]))
        elif f[0] == "INV":
            inv[int(f[1])] = (f[2], int(f[3]))
        elif f[0] == "CURSOR":
            cursor = None if f[1] == "-" else f[1]
    return status, chest, inv, cursor


def _random_inv(rng):
    names = ["Copper Ingot", "Nii Rune", "Snake Symbol", "Wyvern Reins", "Galleon", "Spring", "Thunder Powder II"]
    pages = rng.randint(1, 5)
    out = {}
    for p in range(1, pages + 1):
        slots = []
        for s in range(45):
            if rng.random() < 0.5:
                name = rng.choice(names)
                kind = "item" if name in ("Galleon", "Spring") else "other"
                sig = f"{name[:4]}{rng.randrange(3)}" if kind == "other" else f"{name[:4]}-{p}-{s}"
                slots.append({"slot": s, "name": name, "kind": kind, "sig": sig.replace(" ", "_"),
                              "count": rng.randint(1, 2) if kind == "other" else 1})
        out[str(p)] = {"updated": "", "slots": slots}
    return Inventory(places={"account": {"pages": out}, "inventory:c1": {"pages": {"1": {"slots": []}}}},
                     characters={"c1": {"seen": "x"}}), pages


@pytest.mark.parametrize("seed", range(12))
def test_the_mod_carries_out_the_apps_plans(gd, harness, seed):
    rng = random.Random(seed)
    inv, n_pages = _random_inv(rng)
    start = n_pages
    pl = ss.plan(gd, inv, "account", start_page=start, buffer=sorted(rng.sample(range(13, 36), rng.randint(2, 12))))
    pages = {p: {s: (e["sig"], e.get("count", 1)) for s, e in slots.items()}
             for p, slots in ss.chest_pages(inv, "account").items()}
    status, chest, carried, cursor = _result(harness(_lines(pl, pages, start, n_pages)))
    assert status == ["DONE"] and carried == {} and cursor is None
    py_end, _ = ss.simulate({p: {s: list(v) for s, v in slots.items()} for p, slots in pages.items()}, {},
                            pl["steps"], next((s["page"] for s in pl["steps"] if s["op"] == "page"), start))
    assert {p: slots for p, slots in chest.items() if slots} == \
        {p: {s: tuple(v[:2]) for s, v in slots.items()} for p, slots in py_end.items() if slots}


def test_it_stops_safely_when_the_chest_changes_mid_sort(gd, harness):
    rng = random.Random(7)
    inv, n_pages = _random_inv(rng)
    while n_pages < 3:
        inv, n_pages = _random_inv(rng)
    pl = ss.plan(gd, inv, "account", start_page=n_pages, buffer=list(range(20, 36)))
    pages = {p: {s: (e["sig"], e.get("count", 1)) for s, e in slots.items()}
             for p, slots in ss.chest_pages(inv, "account").items()}
    # take away an item the plan will reach later, while the sort runs
    k, victim = next((k, s) for k, s in enumerate(pl["steps"])
                     if k > len(pl["steps"]) // 3 and s["op"] == "click" and s["area"] == "chest" and s["slot_has"])
    page = next(s["page"] for s in reversed(pl["steps"][:k]) if s["op"] == "page")
    status, chest, carried, cursor = _result(harness(_lines(pl, pages, n_pages, n_pages,
                                                            disturb=[(k - 1, page, victim["slot"])])))
    assert status[0] == "STOP" and "holds nothing" in status[1]
    assert cursor is None                                      # whatever it held was put down
    before = sorted(v for slots in pages.values() for v in slots.values())
    after = sorted([v for slots in chest.values() for v in slots.values()] + list(carried.values()))
    assert len(after) == len(before) - 1                       # only the item taken away is missing


def test_a_plan_that_clicks_a_control_slot_is_refused(harness):
    out = harness(["START\t1\t1\t35", "CHEST\t1\t46\tquick\t1", "PAGE\t1", "EXPECT\t46\tquick\t1",
                   "CLICK\tchest\t46\tquick\t1\t-\t0"])
    status, chest, _, cursor = _result(out)
    assert status[0] == "STOP" and "must not" in status[1] and chest[1][46] == ("quick", 1)


def test_stack_ids_tell_tooltips_apart(harness):
    a = harness(["SIG\tminecraft:potion\tGalleon\tWalk Speed+18%"])[0]
    b = harness(["SIG\tminecraft:potion\tGalleon\tWalk Speed+19%"])[0]
    c = harness(["SIG\tminecraft:potion\tGalleon\tWalk Speed+18%"])[0]
    assert a == c and a != b and len(a) == 12
