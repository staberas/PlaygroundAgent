"""Unified CLI + tkinter GUI. Each ML stage uses its own Python environment."""
import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path
from pipeline import ROOT, COLUMNS, read_rows, write_rows, scan, rules, rename_jfif_to_jpg
from sorter import assign

DEFAULT_CSV = ROOT / "imgscan.csv"
STAGES = ("nudenet", "yolo", "ocr", "nsfw", "marqo", "smilingwolf")

def interpreter(stage):
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    folder = Path(config["environments"][stage]).expanduser()
    if not folder.is_absolute():
        folder = ROOT / folder
    exe = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not exe.is_file():
        raise FileNotFoundError(f"Missing {stage} environment: {exe}. Run setup_envs.py --{stage}")
    return exe

def run(stage, csv_path, force=False, callback=print):
    if not Path(csv_path).is_file():
        raise FileNotFoundError(f"Scan images first; CSV missing: {csv_path}")
    cmd = [str(interpreter(stage)), "-u", str(ROOT / "worker.py"), stage, "--csv", str(csv_path)]
    if force:
        cmd.append("--force")
    with subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace", bufsize=1) as proc:
        for line in proc.stdout:
            callback(line.rstrip())
        rc = proc.wait()
    if rc:
        raise RuntimeError(f"{stage} worker exited with status {rc}")

def gui(csv_path):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    window = tk.Tk()
    window.title("Image Library Toolkit")
    window.geometry("1190x720")
    folder = tk.StringVar()
    recursive = tk.BooleanVar(value=True)
    status = tk.StringVar(value="Ready")
    stage = tk.StringVar(value="nudenet")
    force = tk.BooleanVar()
    config_path = ROOT / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cosplay_nsfw = tk.BooleanVar(value=bool(config.get("settings", {}).get("cosplay_force_nsfw", False)))
    def save_cosplay_toggle():
        try:
            current = json.loads(config_path.read_text(encoding="utf-8"))
            current.setdefault("settings", {})["cosplay_force_nsfw"] = cosplay_nsfw.get()
            config_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            note("Cosplay NSFW override " + ("enabled" if cosplay_nsfw.get() else "disabled") + ". Click Assign folders to recompute.")
        except Exception as exc:
            messagebox.showerror("Settings error", str(exc))
    top = ttk.Frame(window, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Folder").pack(side="left")
    ttk.Entry(top, textvariable=folder, width=74).pack(side="left", padx=4)
    def browse():
        selected = filedialog.askdirectory()
        if selected:
            folder.set(selected)
    ttk.Button(top, text="Browse", command=browse).pack(side="left")
    ttk.Checkbutton(top, text="Recursive", variable=recursive).pack(side="left", padx=8)
    container = ttk.Frame(window, padding=8)
    container.pack(fill="both", expand=True)
    table = ttk.Treeview(container, columns=COLUMNS, show="headings", selectmode="browse")
    for col in COLUMNS:
        table.heading(col, text=col)
        table.column(col, width=220 if col in ("path", "destination_folder", "route_reason") else 105, stretch=False)
    yscroll = ttk.Scrollbar(container, orient="vertical", command=table.yview)
    xscroll = ttk.Scrollbar(container, orient="horizontal", command=table.xview)
    table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    table.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)
    log = tk.Text(window, height=8, wrap="word")
    log.pack(fill="x", padx=8, pady=4)
    def note(msg):
        log.insert("end", str(msg) + "\n")
        log.see("end")
    def refresh():
        for item in table.get_children():
            table.delete(item)
        rows, _ = read_rows(csv_path)
        for i, row in enumerate(rows):
            table.insert("", "end", iid=str(i), values=[row.get(col, "") for col in COLUMNS])
        status.set(f"{len(rows)} images in {csv_path}")
    def do_scan():
        try:
            count = scan(folder.get(), csv_path, recursive.get())
            refresh()
            note(f"Scanned {count} images.")
        except Exception as exc:
            messagebox.showerror("Scan failed", str(exc))
    controls = ttk.Frame(window, padding=8)
    controls.pack(fill="x")
    ttk.Button(controls, text="Scan folder", command=do_scan).pack(side="left")
    ttk.Combobox(controls, textvariable=stage, values=STAGES, state="readonly", width=15).pack(side="left", padx=6)
    ttk.Checkbutton(controls, text="Force re-run", variable=force).pack(side="left")
    def job():
        selected, rerun = stage.get(), force.get()
        status.set(f"Running {selected}...")
        def background():
            try:
                run(selected, csv_path, rerun, lambda line: window.after(0, note, line))
                window.after(0, note, f"{selected} completed.")
            except Exception as exc:
                window.after(0, note, f"ERROR: {exc}")
            finally:
                window.after(0, finished)
        def finished():
            refresh()
            run_button.configure(state="normal")
        run_button.configure(state="disabled")
        threading.Thread(target=background, daemon=True).start()
    run_button = ttk.Button(controls, text="Run stage", command=job)
    run_button.pack(side="left", padx=6)
    ttk.Button(controls, text="Refresh", command=refresh).pack(side="left")
    def do_assign():
        try:
            count = assign(csv_path, force=True)
            refresh()
            note(f"Updated {count} destination suggestions. No files moved.")
        except Exception as exc:
            messagebox.showerror("Assignment failed", str(exc))
    ttk.Button(controls, text="Assign folders", command=do_assign).pack(side="left", padx=6)
    ttk.Checkbutton(controls, text="Cosplay always NSFW", variable=cosplay_nsfw,
                    command=save_cosplay_toggle).pack(side="left", padx=6)
    def do_jfif_rename():
        rows, _ = read_rows(csv_path)
        n = sum(Path(row.get("path", "")).suffix.lower() == ".jfif" for row in rows)
        if not n:
            messagebox.showinfo("JFIF rename", "No .jfif files are listed.")
            return
        if not messagebox.askyesno("Rename JFIF to JPG",
                 f"Rename up to {n} listed .jfif files to .jpg?\nThis changes disk filenames and CSV paths; existing .jpg files are never overwritten."):
            return
        try:
            count, skipped = rename_jfif_to_jpg(csv_path)
            refresh()
            note(f"JFIF rename: {count} renamed, {len(skipped)} skipped.")
            for item in skipped:
                note("SKIPPED: " + item)
            messagebox.showinfo("JFIF rename", f"{count} renamed, {len(skipped)} skipped. Check the log for details.")
        except Exception as exc:
            refresh()
            messagebox.showerror("JFIF rename failed", str(exc))
    ttk.Button(controls, text="JFIF → JPG", command=do_jfif_rename).pack(side="left", padx=6)
    def produce_rules():
        try:
            note(f"Rules written to {rules(csv_path)}")
        except Exception as exc:
            messagebox.showerror("Rules failed", str(exc))
    ttk.Button(controls, text="Export review rules", command=produce_rules).pack(side="left", padx=6)
    def edit(event):
        item = table.identify_row(event.y)
        column = table.identify_column(event.x)
        if not item or not column:
            return
        index = int(column[1:]) - 1
        if index < 0 or index >= len(COLUMNS):
            return
        field = COLUMNS[index]
        if field not in ("ignore", "new_file_name", "destination_folder", "route_review", "other"):
            return
        rows, columns = read_rows(csv_path)
        rowidx = int(item)
        if field == "ignore":
            rows[rowidx][field] = "false" if rows[rowidx].get(field, "").lower() in ("true", "1", "yes") else "true"
            write_rows(csv_path, rows, columns)
            refresh()
            return
        import tkinter.simpledialog as simpledialog
        value = simpledialog.askstring(f"Edit {field}", field, initialvalue=rows[rowidx].get(field, ""), parent=window)
        if value is not None:
            rows[rowidx][field] = value
            write_rows(csv_path, rows, columns)
            refresh()
    table.bind("<Double-1>", edit)
    ttk.Label(window, textvariable=status, padding=5).pack(anchor="w")
    refresh()
    window.mainloop()

def main():
    ap = argparse.ArgumentParser(description="Image library scanner / pipeline")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    commands = ap.add_subparsers(dest="action")
    sc = commands.add_parser("scan")
    sc.add_argument("folder")
    sc.add_argument("--recursive", action="store_true")
    rn = commands.add_parser("run")
    rn.add_argument("stage", choices=STAGES)
    rn.add_argument("--force", action="store_true")
    commands.add_parser("status")
    commands.add_parser("rules")
    sorter = commands.add_parser("assign")
    sorter.add_argument("--force", action="store_true", help="Recompute existing suggestions")
    commands.add_parser("gui")
    args = ap.parse_args()
    csv_path = args.csv.resolve()
    if args.action == "scan":
        print(f"Scanned {scan(args.folder, csv_path, args.recursive)} images => {csv_path}")
    elif args.action == "run":
        run(args.stage, csv_path, args.force)
    elif args.action == "assign":
        print(f"Assigned {assign(csv_path, args.force)} destination suggestions (no files moved)")
    elif args.action == "rules":
        print(rules(csv_path))
    elif args.action == "status":
        rows, _ = read_rows(csv_path)
        print(f"CSV: {csv_path}; images: {len(rows)}")
        for name in STAGES:
            print(f"{name}: {sum(bool(row.get(name, '').strip()) for row in rows)}/{len(rows)}")
    else:
        gui(csv_path)

if __name__ == "__main__":
    main()
