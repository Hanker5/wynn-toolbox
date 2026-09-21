"""Progress display for long searches."""
import sys


class ProgressBar:
    """Callable for `solve_gear(progress=...)`.

    In a terminal it redraws one line in place. Elsewhere (logs, AI agents running
    commands) it prints a line at each 10% step so output stays short.
    """

    def __init__(self, label="searching", stream=sys.stderr, width=30):
        self.label, self.stream, self.width = label, stream, width
        self.tty = stream.isatty()
        self.last_decile = -1

    def __call__(self, p):
        pct = p["fraction"] * 100
        best = "—" if p["best"] is None else f"{p['best']:g}"
        m, s = divmod(int(p["elapsed"]), 60)
        info = f"{pct:5.1f}%  {p['nodes']:,} checked  best {best}  {m}:{s:02d}"
        if self.tty:
            fill = int(self.width * p["fraction"])
            self.stream.write(f"\r{self.label} [{'#' * fill}{'.' * (self.width - fill)}] {info}")
            if p["fraction"] >= 1:
                self.stream.write("\n")
        elif int(pct // 10) > self.last_decile:
            self.last_decile = int(pct // 10)
            self.stream.write(f"{self.label}: {info}\n")
        self.stream.flush()
