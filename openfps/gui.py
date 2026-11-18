"""Interface graphique : catalogue de jeux en cartes (grille de jaquettes) + fiche du jeu."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, catalog, covers, hardware, scoring

try:  # optionnel : permet d'afficher les jaquettes JPG de Steam
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover
    Image = ImageTk = None

BG, PANEL, FG, MUTED, ACCENT = "#141414", "#1f1f1f", "#f2f2f2", "#9a9a9a", "#ff5a1f"
CARD_W, CARD_H, PAD = 150, 225, 14


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"OpenFPS {__version__}")
        self.geometry("1000x680")
        self.minsize(640, 480)
        self.configure(bg=BG)
        self.games = catalog.load_catalog()
        self.hw = None
        self.env = None
        self._images = {}  # (id, w, h) -> PhotoImage (garde une référence)
        self._cols = 0
        self._after = None
        self._style()
        self._build()
        self._detect_async()

    # ------------------------------------------------------------------ style
    def _style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=24, borderwidth=0)
        st.configure("Treeview.Heading", background="#2b2b2b", foreground=FG, borderwidth=0)
        st.map("Treeview", background=[("selected", "#333333")])
        st.configure("Accent.TButton", background=ACCENT, foreground="white", padding=8,
                     borderwidth=0, font=("Segoe UI", 10, "bold"))
        st.map("Accent.TButton", background=[("active", "#ff7a45"), ("disabled", "#555555")])
        st.configure("Plain.TButton", background="#333333", foreground=FG, padding=8, borderwidth=0)
        st.map("Plain.TButton", background=[("active", "#444444")])

    # --------------------------------------------------------------------- UI
    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=PAD, pady=(PAD, 4))
        tk.Label(top, text="OpenFPS", bg=BG, fg=ACCENT, font=("Segoe UI", 22, "bold")).pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._render())
        e = tk.Entry(top, textvariable=self.search, bg=PANEL, fg=FG, insertbackground=FG,
                     relief="flat", font=("Segoe UI", 11), width=26)
        e.pack(side="right", ipady=5)
        tk.Label(top, text="Rechercher", bg=BG, fg=MUTED).pack(side="right", padx=8)

        self.hw_label = tk.Label(self, text="Détection de ta configuration...", bg=BG, fg=MUTED,
                                 anchor="w", justify="left", font=("Segoe UI", 9))
        self.hw_label.pack(fill="x", padx=PAD)

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_resize)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self._render()

    def _on_wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _on_resize(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        cols = max(1, (e.width - PAD) // (CARD_W + PAD))
        if cols != self._cols:
            self._cols = cols
            if self._after:
                self.after_cancel(self._after)
            self._after = self.after(120, self._render)

    # --------------------------------------------------------------- catalogue
    def _render(self):
        for w in self.inner.winfo_children():
            w.destroy()
        q = self.search.get().lower().strip()
        shown = [g for g in self.games if q in g.name.lower()]
        installed = [g for g in shown if g.find_config()]
        others = [g for g in shown if g not in installed]
        self._section("Détectés sur ton PC", installed,
                      "Aucun jeu du catalogue détecté pour l'instant.")
        self._section("Catalogue", others, "")

    def _section(self, title, games, empty_text):
        tk.Label(self.inner, text=title, bg=BG, fg=FG, font=("Segoe UI", 14, "bold"),
                 anchor="w").pack(fill="x", padx=PAD, pady=(10, 6))
        if not games:
            if empty_text:
                tk.Label(self.inner, text=empty_text, bg=BG, fg=MUTED, anchor="w").pack(
                    fill="x", padx=PAD)
            return
        grid = tk.Frame(self.inner, bg=BG)
        grid.pack(fill="x", padx=PAD // 2)
        cols = max(1, self._cols or 5)
        for i, g in enumerate(games):
            card = self._poster(grid, g, CARD_W, CARD_H, installed=bool(g.find_config()),
                                clickable=True)
            card.grid(row=i // cols, column=i % cols, padx=PAD // 2, pady=PAD // 2)

    # --------------------------------------------------------------- jaquettes
    def _cover_image(self, g, w, h):
        key = (g.id, w, h)
        if key in self._images:
            return self._images[key]
        img = None
        path = covers.find_cover(g)
        try:
            if path and Image is not None:
                im = Image.open(path).convert("RGB").resize((w, h), Image.LANCZOS)
                img = ImageTk.PhotoImage(im)
            elif path and path.lower().endswith(".png"):
                full = tk.PhotoImage(file=path)
                if full.width() >= w and full.height() >= h:
                    img = full.subsample(max(1, full.width() // w), max(1, full.height() // h))
        except Exception:
            img = None
        self._images[key] = img
        return img

    def _poster(self, parent, g, w, h, installed, clickable):
        c = tk.Canvas(parent, width=w, height=h, bg=BG, highlightthickness=2,
                      highlightbackground=BG, bd=0, cursor="hand2" if clickable else "")
        img = self._cover_image(g, w, h)
        if img is not None:
            c.create_image(0, 0, image=img, anchor="nw")
        else:  # jaquette générée : dégradé + nom du jeu
            top, bottom = covers.tile_colors(g.id)
            t, b = int(top[1:], 16), int(bottom[1:], 16)
            steps = 30
            for i in range(steps):
                f = i / (steps - 1)
                col = "#%02x%02x%02x" % tuple(
                    int(((t >> s) & 255) * (1 - f) + ((b >> s) & 255) * f) for s in (16, 8, 0))
                c.create_rectangle(0, i * h / steps, w, (i + 1) * h / steps + 1, fill=col, width=0)
            name = g.name.split(" (")[0]
            c.create_text(w / 2, h / 2, text=name, fill="white", width=w - 22,
                          justify="center", font=("Segoe UI", max(10, w // 12), "bold"))
        c.create_rectangle(0, h - 26, w, h, fill="#000000", stipple="gray50", width=0)
        c.create_text(8, h - 13, anchor="w", font=("Segoe UI", 9, "bold"),
                      fill="#5ee38b" if installed else MUTED,
                      text="● Détecté" if installed else "Non trouvé")
        if clickable:
            c.bind("<Enter>", lambda _e: c.configure(highlightbackground=ACCENT))
            c.bind("<Leave>", lambda _e: c.configure(highlightbackground=BG))
            c.bind("<Button-1>", lambda _e, game=g: self._open_detail(game))
        return c

    # ------------------------------------------------------------- détection PC
    def _detect_async(self):
        def work():
            hw = hardware.detect(screen=False)
            self.after(0, lambda: self._detected(hw))
        threading.Thread(target=work, daemon=True).start()

    def _detected(self, hw):
        hw.screen_w, hw.screen_h = hardware.detect_screen(self)
        self.hw, self.env = hw, scoring.variables(hw)
        e = self.env
        self.hw_label.config(text=(
            f"GPU {hw.gpu_name} (score {e['gpu']}/100)   |   CPU {hw.cpu_threads} threads "
            f"(score {e['cpu']}/100)   |   RAM {hw.ram_gb} Go   |   Écran {hw.screen_w}x{hw.screen_h}"))

    # -------------------------------------------------------------------- fiche
    def _open_detail(self, g):
        win = tk.Toplevel(self)
        win.title(g.name)
        win.configure(bg=BG)
        win.geometry("820x520")
        win.transient(self)

        left = tk.Frame(win, bg=BG)
        left.pack(side="left", padx=PAD, pady=PAD, anchor="n")
        poster_holder = tk.Frame(left, bg=BG)
        poster_holder.pack()
        right = tk.Frame(win, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, PAD), pady=PAD)

        title = tk.Label(right, text=g.name, bg=BG, fg=FG, font=("Segoe UI", 18, "bold"),
                         anchor="w", wraplength=500, justify="left")
        title.pack(fill="x")
        path_lbl = tk.Label(right, text="", bg=BG, fg=MUTED, anchor="w", wraplength=500,
                            justify="left", font=("Segoe UI", 9))
        path_lbl.pack(fill="x", pady=(2, 8))

        cols = ("Réglage", "Actuel", "Nouveau")
        tree = ttk.Treeview(right, columns=cols, show="headings", height=9)
        for col, wd in zip(cols, (270, 100, 100)):
            tree.heading(col, text=col)
            tree.column(col, width=wd)
        tree.pack(fill="both", expand=True)

        tips = tk.Label(right, text="", bg=BG, fg=MUTED, anchor="w", wraplength=500,
                        justify="left", font=("Segoe UI", 9))
        tips.pack(fill="x", pady=6)
        status = tk.Label(right, text="", bg=BG, fg="#5ee38b", anchor="w")
        status.pack(fill="x")

        bar = tk.Frame(right, bg=BG)
        bar.pack(fill="x", pady=(4, 0))
        btn_opt = ttk.Button(bar, text="Optimiser", style="Accent.TButton")
        btn_res = ttk.Button(bar, text="Restaurer l'original", style="Plain.TButton")
        btn_browse = ttk.Button(bar, text="Choisir le fichier...", style="Plain.TButton")
        btn_opt.pack(side="left")
        btn_res.pack(side="left", padx=6)
        btn_browse.pack(side="left")

        def refresh():
            for w in poster_holder.winfo_children():
                w.destroy()
            self._poster(poster_holder, g, 180, 270, bool(g.find_config()),
                         clickable=False).pack()
            tree.delete(*tree.get_children())
            path = g.find_config()
            path_lbl.config(text=path or "Fichier de config introuvable : lance le jeu une "
                                         "fois, ou utilise « Choisir le fichier... ».")
            ready = bool(path) and self.env is not None
            btn_opt.state(["!disabled"] if ready else ["disabled"])
            has_backup = bool(path) and os.path.exists(path + catalog.BACKUP_SUFFIX)
            btn_res.state(["!disabled"] if has_backup else ["disabled"])
            if self.env is None:
                tips.config(text="Détection de ta configuration en cours...")
                win.after(800, refresh)
                return
            tips.config(text="\n".join(catalog.render_tips(g, self.env)))
            if path:
                try:
                    for ch in catalog.plan(g, path, self.env):
                        tree.insert("", "end", values=(ch.label, ch.old, ch.new))
                except OSError as exc:
                    status.config(text=f"Lecture impossible : {exc}", fg="#ff6b6b")
            if path and not tree.get_children():
                status.config(text="Déjà optimisé pour ta configuration.", fg="#5ee38b")

        def optimize():
            try:
                changes = (catalog.apply(g, g.custom_path, self.env) if g.custom_path
                           else catalog.apply_all(g, self.env))
            except OSError as exc:
                messagebox.showerror("OpenFPS", f"Écriture impossible : {exc}", parent=win)
                return
            refresh()
            status.config(text=f"{len(changes)} réglage(s) appliqué(s). Sauvegarde créée.",
                          fg="#5ee38b")

        def restore():
            ok = (catalog.restore(g.custom_path) if g.custom_path else catalog.restore_all(g))
            refresh()
            status.config(text="Configuration d'origine restaurée." if ok else
                          "Aucune sauvegarde trouvée.", fg="#5ee38b" if ok else "#ff6b6b")

        def browse():
            p = filedialog.askopenfilename(parent=win, title="Fichier de configuration du jeu")
            if p:
                g.custom_path = p
                refresh()

        btn_opt.configure(command=optimize)
        btn_res.configure(command=restore)
        btn_browse.configure(command=browse)
        refresh()


def run():
    App().mainloop()
