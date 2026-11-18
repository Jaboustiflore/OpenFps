"""Interface graphique tkinter : catalogue à gauche, détail et bouton Optimiser à droite."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, catalog, hardware, scoring


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"OpenFPS {__version__} - optimiseur de FPS")
        self.geometry("900x560")
        self.minsize(760, 480)
        self.games = catalog.load_catalog()
        self.hw = None
        self.env = None
        self.current = None
        self._build()
        self._detect_async()

    # ------------------------------------------------------------------ UI
    def _build(self):
        left = ttk.Frame(self, padding=8)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Catalogue de jeux", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_list())
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=4)
        self.listbox = tk.Listbox(left, width=34, height=20, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._select())

        right = ttk.Frame(self, padding=8)
        right.pack(side="left", fill="both", expand=True)
        self.hw_label = ttk.Label(right, text="Détection de la configuration...", justify="left")
        self.hw_label.pack(anchor="w")
        self.game_label = ttk.Label(right, text="", font=("Segoe UI", 12, "bold"))
        self.game_label.pack(anchor="w", pady=(10, 0))
        self.path_label = ttk.Label(right, text="", foreground="#666")
        self.path_label.pack(anchor="w")

        cols = ("reglage", "actuel", "nouveau")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=12)
        for c, w in zip(cols, (300, 120, 120)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True, pady=8)

        self.tips = ttk.Label(right, text="", wraplength=520, justify="left")
        self.tips.pack(anchor="w")

        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(8, 0))
        self.btn_opt = ttk.Button(bar, text="Optimiser", command=self._optimize, state="disabled")
        self.btn_opt.pack(side="left")
        self.btn_res = ttk.Button(bar, text="Restaurer l'original", command=self._restore, state="disabled")
        self.btn_res.pack(side="left", padx=6)
        ttk.Button(bar, text="Choisir le fichier...", command=self._browse).pack(side="left")
        self.status = ttk.Label(right, text="")
        self.status.pack(anchor="w", pady=4)
        self._fill_list()

    def _fill_list(self):
        q = self.search.get().lower().strip()
        self.listbox.delete(0, "end")
        # jeux détectés sur le PC en premier, puis le reste du catalogue
        self.shown = sorted((g for g in self.games if q in g.name.lower()),
                            key=lambda g: (g.find_config() is None, g.name.lower()))
        for g in self.shown:
            tag = "OK" if g.find_config() else "--"
            self.listbox.insert("end", f"[{tag}] {g.name}")

    # ------------------------------------------------------------ détection
    def _detect_async(self):
        def work():
            hw = hardware.detect(screen=False)
            self.after(0, lambda: self._detected(hw))
        threading.Thread(target=work, daemon=True).start()

    def _detected(self, hw):
        # La taille d'écran se lit dans le thread principal (tkinter n'est pas thread-safe)
        hw.screen_w, hw.screen_h = hardware.detect_screen(self)
        self.hw, self.env = hw, scoring.variables(hw)
        e = self.env
        self.hw_label.config(
            text=(f"CPU : {hw.cpu_name} ({hw.cpu_threads} threads) - score {e['cpu']}/100\n"
                  f"GPU : {hw.gpu_name} - score {e['gpu']}/100\n"
                  f"RAM : {hw.ram_gb} Go   Écran : {hw.screen_w}x{hw.screen_h}")
        )
        self._select()

    # -------------------------------------------------------------- actions
    def _select(self):
        sel = self.listbox.curselection()
        if not sel or self.env is None:
            return
        self.current = self.shown[sel[0]]
        self._refresh()

    def _refresh(self):
        g = self.current
        self.tree.delete(*self.tree.get_children())
        self.game_label.config(text=g.name)
        path = g.find_config()
        self.path_label.config(text=path or "Config introuvable : lance le jeu une fois ou 'Choisir le fichier...'")
        self.btn_opt.config(state="normal" if path else "disabled")
        self.btn_res.config(state="normal" if path and catalog.os.path.exists(path + catalog.BACKUP_SUFFIX) else "disabled")
        self.tips.config(text="\n".join(catalog.render_tips(g, self.env)))
        if path:
            for c in catalog.plan(g, path, self.env):
                self.tree.insert("", "end", values=(c.label, c.old, c.new))

    def _optimize(self):
        g, path = self.current, self.current.find_config()
        try:
            changes = (catalog.apply(g, path, self.env) if g.custom_path
                       else catalog.apply_all(g, self.env))
        except OSError as exc:
            messagebox.showerror("OpenFPS", f"Écriture impossible : {exc}")
            return
        self.status.config(text=f"{len(changes)} réglage(s) appliqué(s). Sauvegarde créée.")
        self._refresh()

    def _restore(self):
        g = self.current
        if (catalog.restore(g.custom_path) if g.custom_path else catalog.restore_all(g)):
            self.status.config(text="Configuration d'origine restaurée.")
        self._refresh()

    def _browse(self):
        if not self.current:
            return
        p = filedialog.askopenfilename(title="Fichier de configuration du jeu")
        if p:
            self.current.custom_path = p
            self._refresh()


def run():
    App().mainloop()
