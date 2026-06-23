#!/usr/bin/env python3
"""Row-based config editor for PipeWire VAC.

Two cable sections plus app routing. **Cables** are output cables (Name, Channels, Target).
**Microphones** are the same cable, plus a Source (a hardware mic wired in) — apps capture the
cable's monitor as a virtual mic; its Target can still send the audio to any output (or none).
Device dropdowns show friendly labels but store the stable node name. Save regenerates
config.toml (comments dropped); the daemon applies the new structure on its next poll. The editor
never touches the live graph — it only edits config. Volume/mute/default are the user's.

Run:  python src/configui.py [--config PATH]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import config
import pwgraph
import apps
from routing import LAYOUTS

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception:                  # importable without Tk so the pure helpers stay testable
    tk = None

CHANNEL_CHOICES = list(LAYOUTS)    # mono, stereo, 2.1, 5.1, 7.1

# Picker sentinels. Comboboxes show friendly labels; config stores the stable node name (or "auto"
# / "" for none). MIC_MULTI marks a TOML-set list of 2+ sources — shown read-only, kept verbatim.
TARGET_NONE = "(no output)"
MIC_AUTO = "auto (first physical)"
MIC_MULTI = "(multiple — edit in TOML)"


def _s(v):
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


def dump_config(cfg):
    """Serialize the v2 config (cables + features) back to TOML. Comments are dropped."""
    out = ["# PipeWire VAC config — written by the settings UI.\n", "config_version = 2\n"]
    for c in cfg["cable"]:
        out.append("\n[[cable]]\n")
        out.append("name = %s\n" % _s(c["name"]))
        out.append("channels = %s\n" % _s(c["channels"]))
        out.append("target = %s\n" % _s(c["target"]))   # "" = virtual mic with no output
        if c.get("sources"):
            out.append("sources = [%s]\n" % ", ".join(_s(s) for s in c["sources"]))
    for r in cfg.get("app") or []:
        out.append("\n[[app]]\n")
        out.append("match = %s\n" % _s(r["match"]))
        out.append("target = %s\n" % _s(r["target"]))
    feats = cfg.get("features") or {}
    if feats:
        out.append("\n[features]\n")
        for k, v in feats.items():
            out.append("%s = %s\n" % (k, "true" if v is True else "false" if v is False else _s(v)))
    return "".join(out)


def _label_map(pairs):
    """[(name, desc)] -> {f'{desc} (physical)': name}, disambiguating duplicate descriptions with
    the node name. Used for both the output sinks and the capture sources."""
    out = {}
    for name, desc in pairs:
        base = f"{desc} (physical)"
        out[base if base not in out else f"{base} [{name}]"] = name
    return out


# --- pure label<->stored-value mappings (Tk-free, unit-tested) ---

def target_display(target, name_to_label):
    """A stored target -> the label shown in a Target combobox."""
    if target == "":
        return TARGET_NONE
    return name_to_label.get(target, target)        # physical -> label; cable/'auto' pass through


def target_store(label, label_to_name):
    """A picked Target label -> the stored value."""
    if label in ("", TARGET_NONE):
        return ""
    return label_to_name.get(label, label)


def mic_display(sources, name_to_label):
    """A cable's `sources` list -> the label shown in its Source combobox."""
    if not sources:        return MIC_AUTO          # a mic row always has a source; default auto
    if len(sources) > 1:   return MIC_MULTI
    s = sources[0]
    if s == "auto":        return MIC_AUTO
    return name_to_label.get(s, s)                  # raw name if the device is unplugged/unknown


def mic_to_sources(label, original, label_to_name):
    """A picked Source label -> the cable's `sources` list. MULTI (unchanged) is preserved
    verbatim; a known label maps to its node name; anything else is treated as a raw name."""
    if label == MIC_AUTO:    return ["auto"]
    if label == MIC_MULTI:   return list(original)
    if not label:            return []
    return [label_to_name.get(label, label)]


class App:
    def __init__(self, root, cfgpath):
        self.root = root
        self.cfgpath = cfgpath
        self.cfg = config.load(cfgpath)
        self._build_device_maps()
        self.rows = []           # output cables
        self.mic_rows = []       # virtual mics (cables with a source)
        self.app_rows = []
        root.title("PipeWire VAC — settings")
        self._build()

    def _build_device_maps(self):
        """Friendly label <-> node name for outputs (Target) and capture devices (Source)."""
        names = {c["name"] for c in self.cfg["cable"]}
        try:    sinks = pwgraph.sink_labels(names)       # [(name, desc)] physical outputs
        except Exception: sinks = []
        try:    srcs = pwgraph.source_labels()           # [(name, desc)] capture devices
        except Exception: srcs = []
        self.target_label_to_name = _label_map(sinks)
        self.target_name_to_label = {n: l for l, n in self.target_label_to_name.items()}
        self.mic_label_to_name = _label_map(srcs)
        self.mic_name_to_label = {n: l for l, n in self.mic_label_to_name.items()}

        cable_names = [c["name"] for c in self.cfg["cable"]]
        phys = list(self.target_label_to_name)
        # cable & mic target: (no output) for a record/stream bus, auto, an output, or another cable
        self.targets = [TARGET_NONE, "auto"] + phys + cable_names
        self.app_targets = phys + cable_names                        # app: real outputs + cables only
        self.mic_choices = [MIC_AUTO] + list(self.mic_label_to_name)

    def _build(self):
        pad = {"padx": 10, "pady": 8}

        frame = ttk.LabelFrame(self.root, text="Cables")
        frame.pack(fill="both", expand=True, **pad)
        hdr = ttk.Frame(frame); hdr.pack(fill="x")
        for txt, w in (("Name", 16), ("Channels", 10), ("Target", 34), ("", 4)):
            ttk.Label(hdr, text=txt, width=w).pack(side="left", padx=2)
        self.container = ttk.Frame(frame); self.container.pack(fill="x")
        for c in self.cfg["cable"]:
            if not c.get("sources"):
                self._add_row(c["name"], c["channels"], c["target"])
        ttk.Button(frame, text="+ Add cable",
                   command=lambda: self._add_row("", "stereo", "auto")).pack(anchor="w", pady=6)

        mf = ttk.LabelFrame(self.root, text="Microphones (virtual mics)")
        mf.pack(fill="both", expand=True, **pad)
        ttk.Label(mf, wraplength=560, foreground="#666",
                  text="Apps select the Name as their input. Source is the hardware mic wired in "
                       "(mono mics fan out to stereo). Target optionally also sends it to an "
                       "output — leave it '(no output)' for a capture-only mic.").pack(anchor="w")
        mhdr = ttk.Frame(mf); mhdr.pack(fill="x")
        for txt, w in (("Name", 16), ("Channels", 10), ("Source", 34), ("Target", 26), ("", 4)):
            ttk.Label(mhdr, text=txt, width=w).pack(side="left", padx=2)
        self.mic_container = ttk.Frame(mf); self.mic_container.pack(fill="x")
        for c in self.cfg["cable"]:
            if c.get("sources"):
                self._add_mic_row(c["name"], c["channels"], c["target"], c["sources"])
        ttk.Button(mf, text="+ Add microphone",
                   command=lambda: self._add_mic_row("", "stereo", "", ["auto"])).pack(anchor="w", pady=6)

        af = ttk.LabelFrame(self.root, text="App routing")
        af.pack(fill="both", expand=True, **pad)
        ttk.Label(af, wraplength=560, foreground="#666",
                  text="Match an alias (browser/game/media/voice), part of an app's name "
                       "(combine with |), or 'default' to catch everything unmatched. "
                       "First matching row wins.").pack(anchor="w")
        ahdr = ttk.Frame(af); ahdr.pack(fill="x")
        for txt, w in (("Match", 30), ("Target", 30), ("", 4)):
            ttk.Label(ahdr, text=txt, width=w).pack(side="left", padx=2)
        self.app_container = ttk.Frame(af); self.app_container.pack(fill="x")
        for r in self.cfg.get("app") or []:
            self._add_app_row(r["match"], r["target"])
        ttk.Button(af, text="+ Add app rule",
                   command=lambda: self._add_app_row("", "")).pack(anchor="w", pady=6)

        bot = ttk.Frame(self.root); bot.pack(fill="x", **pad)
        ttk.Button(bot, text="Save", command=self.save).pack(side="right", padx=4)
        ttk.Button(bot, text="Close", command=self.root.destroy).pack(side="right")

    def _add_row(self, name, channels, target):
        fr = ttk.Frame(self.container); fr.pack(fill="x", pady=2)
        nv = tk.StringVar(value=name)
        cv = tk.StringVar(value=channels if channels in CHANNEL_CHOICES else "stereo")
        tv = tk.StringVar(value=target_display(target, self.target_name_to_label))
        ttk.Entry(fr, textvariable=nv, width=16).pack(side="left", padx=2)
        ttk.Combobox(fr, textvariable=cv, values=CHANNEL_CHOICES, width=8,
                     state="readonly").pack(side="left", padx=2)
        ttk.Combobox(fr, textvariable=tv, values=self.targets, width=34).pack(side="left", padx=2)
        row = {"name": nv, "channels": cv, "target": tv, "frame": fr}
        ttk.Button(fr, text="✕", width=3, command=lambda: self._remove(self.rows, row)).pack(side="left", padx=2)
        self.rows.append(row)

    def _add_mic_row(self, name, channels, target, sources):
        fr = ttk.Frame(self.mic_container); fr.pack(fill="x", pady=2)
        nv = tk.StringVar(value=name)
        cv = tk.StringVar(value=channels if channels in CHANNEL_CHOICES else "stereo")
        tv = tk.StringVar(value=target_display(target, self.target_name_to_label))
        sv = tk.StringVar(value=mic_display(list(sources), self.mic_name_to_label))
        ttk.Entry(fr, textvariable=nv, width=16).pack(side="left", padx=2)
        ttk.Combobox(fr, textvariable=cv, values=CHANNEL_CHOICES, width=8,
                     state="readonly").pack(side="left", padx=2)
        ttk.Combobox(fr, textvariable=sv, values=self.mic_choices, width=34).pack(side="left", padx=2)
        ttk.Combobox(fr, textvariable=tv, values=self.targets, width=26).pack(side="left", padx=2)
        # `sources` (raw list) kept so a TOML-set multi-mic survives a save the picker can't express
        row = {"name": nv, "channels": cv, "target": tv, "mic": sv, "sources": list(sources), "frame": fr}
        ttk.Button(fr, text="✕", width=3, command=lambda: self._remove(self.mic_rows, row)).pack(side="left", padx=2)
        self.mic_rows.append(row)

    def _add_app_row(self, match, target):
        fr = ttk.Frame(self.app_container); fr.pack(fill="x", pady=2)
        mv = tk.StringVar(value=match)
        tv = tk.StringVar(value=target_display(target, self.target_name_to_label))
        ttk.Combobox(fr, textvariable=mv, values=list(apps.ALIASES) + ["default"], width=28).pack(side="left", padx=2)
        ttk.Combobox(fr, textvariable=tv, values=self.app_targets, width=28).pack(side="left", padx=2)
        row = {"match": mv, "target": tv, "frame": fr}
        ttk.Button(fr, text="✕", width=3, command=lambda: self._remove(self.app_rows, row)).pack(side="left", padx=2)
        self.app_rows.append(row)

    def _remove(self, rows, row):
        row["frame"].destroy()
        rows.remove(row)

    def save(self):
        cables = []
        for r in self.rows:
            name = r["name"].get().strip()
            if not name:
                continue
            cables.append({"name": name, "channels": r["channels"].get(),
                           "target": target_store(r["target"].get().strip(), self.target_label_to_name)})
        for r in self.mic_rows:
            name = r["name"].get().strip()
            if not name:
                continue
            cable = {"name": name, "channels": r["channels"].get(),
                     "target": target_store(r["target"].get().strip(), self.target_label_to_name)}
            sources = mic_to_sources(r["mic"].get().strip(), r["sources"], self.mic_label_to_name)
            if sources:
                cable["sources"] = sources
            cables.append(cable)
        self.cfg["cable"] = cables
        app_rules = []
        for r in self.app_rows:
            match = r["match"].get().strip()
            if not match:
                continue
            app_rules.append({"match": match,
                              "target": target_store(r["target"].get().strip(), self.target_label_to_name)})
        self.cfg["app"] = app_rules
        try:
            config._validate(self.cfg)
        except config.ConfigError as e:
            messagebox.showerror("Invalid config", str(e)); return
        try:
            with open(self.cfgpath, "w") as f:
                f.write(dump_config(self.cfg))
        except OSError as e:
            messagebox.showerror("Save failed", str(e)); return
        messagebox.showinfo("Saved", "Saved to %s\nThe daemon applies the new structure shortly."
                            % self.cfgpath)


def main():
    if tk is None:
        sys.exit("tkinter not available — install python3-tk / python-tk")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    root = tk.Tk()
    App(root, args.config or paths.config_path())
    root.mainloop()


if __name__ == "__main__":
    main()
