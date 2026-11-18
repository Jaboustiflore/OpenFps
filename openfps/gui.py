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
        self._requested = set()  # appids dont on a déjà demandé la jaquette
        self._dl_after = None
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
        ttk.Button(top, text="Optimisation PC", style="Plain.TButton",
                   command=self._open_pc).pack(side="right", padx=(0, 16))

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
        # ne fait défiler le catalogue que si la molette est sur la fenêtre principale
        try:
            if e.widget.winfo_toplevel() is not self:
                return
        except (tk.TclError, KeyError, AttributeError):
            return
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
        # uniquement les jeux installés sur ce PC
        self._section("Détectés sur ton PC", installed,
                      "Aucun jeu détecté pour l'instant : lance un jeu une fois pour qu'il crée "
                      "sa configuration." if not q else "Aucun jeu détecté ne correspond.")

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
        if path is None and Image is not None:
            self._queue_download(g)
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

    def _queue_download(self, g):
        if g.id in self._requested:
            return
        self._requested.add(g.id)

        def work():
            appid = getattr(g, "steam_appid", None)
            if not appid:  # pas d'appid connu : recherche par nom exact dans le magasin Steam
                appid = covers.lookup_appid(g.name.split(" (")[0])
                if appid:
                    g.steam_appid = appid
            if appid and covers.download_cover(appid):
                self.after(0, self._covers_changed)
        threading.Thread(target=work, daemon=True).start()

    def _covers_changed(self):
        """Une jaquette vient d'arriver : on rafraîchit le catalogue (regroupé)."""
        if self._dl_after:
            self.after_cancel(self._dl_after)
        def redo():
            self._dl_after = None
            for k in [k for k, v in self._images.items() if v is None]:
                del self._images[k]
            self._render()
        self._dl_after = self.after(700, redo)

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

    # ---------------------------------------------------------------- PC (Windows)
    def _open_pc(self):
        from . import pcopt
        win = tk.Toplevel(self)
        win.title("Optimisation du PC")
        win.configure(bg=BG)
        win.transient(self)
        tk.Label(win, text="Optimisation du PC", bg=BG, fg=FG,
                 font=("Segoe UI", 18, "bold"), anchor="w").pack(fill="x", padx=PAD, pady=(PAD, 2))
        tk.Label(win, text="Réglages de ton compte Windows utiles aux jeux. Tout est sauvegardé "
                           "avant changement et se restaure d'un clic.",
                 bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=640,
                 font=("Segoe UI", 9)).pack(fill="x", padx=PAD)

        bar = tk.Frame(win, bg=BG)
        bar.pack(side="bottom", fill="x", padx=PAD, pady=PAD)
        status = tk.Label(win, text="", bg=BG, fg="#5ee38b", anchor="w", wraplength=640,
                          justify="left")
        status.pack(side="bottom", fill="x", padx=PAD)
        why_lbl = tk.Label(win, text="Clique sur une ligne pour voir à quoi elle sert.",
                           bg="#202020", fg="#ffd479", anchor="w", wraplength=640,
                           justify="left", font=("Segoe UI", 10), padx=8, pady=6)
        why_lbl.pack(side="bottom", fill="x", padx=PAD, pady=6)

        box = tk.Frame(win, bg=BG)
        box.pack(fill="both", expand=True, padx=PAD, pady=8)
        cols = ("Réglage", "Actuel", "Cible")
        tree = ttk.Treeview(box, columns=cols, show="headings", height=9)
        for col, wd in zip(cols, (380, 130, 130)):
            tree.heading(col, text=col)
            tree.column(col, width=wd)
        vsb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        whys = {}
        tree.bind("<<TreeviewSelect>>", lambda _e: why_lbl.config(
            text=whys.get((tree.selection() or [""])[0], "")))

        btn_apply = ttk.Button(bar, text="Appliquer", style="Accent.TButton")
        btn_restore = ttk.Button(bar, text="Restaurer l'original", style="Plain.TButton")
        btn_apply.pack(side="left")
        btn_restore.pack(side="left", padx=6)

        def refresh():
            tree.delete(*tree.get_children())
            whys.clear()
            try:
                items = pcopt.tweaks([g for g in self.games if g.find_config() and g.exe])
            except Exception as exc:  # registre / powercfg indisponible
                items = []
                status.config(text=f"Lecture impossible : {exc}", fg="#ff6b6b")
            if not items and not pcopt.IS_WINDOWS:
                status.config(text="Cette fonction n'est disponible que sous Windows.", fg="#ffb347")
            for t in items:
                iid = tree.insert("", "end", values=(
                    ("✔ " if t.done else "") + t.label, t.current, t.target))
                whys[iid] = t.why
            todo = any(not t.done for t in items)
            btn_apply.state(["!disabled"] if todo else ["disabled"])
            has_backup = os.path.exists(pcopt.backup_path())
            btn_restore.state(["!disabled"] if has_backup else ["disabled"])
            if items and not todo:
                status.config(text="Tout est déjà appliqué.", fg="#5ee38b")

        def do_apply():
            try:
                done = pcopt.apply([g for g in self.games if g.find_config() and g.exe])
            except Exception as exc:
                messagebox.showerror("OpenFPS", f"Impossible d'appliquer : {exc}", parent=win)
                return
            refresh()
            status.config(text=f"{len(done)} réglage(s) appliqué(s). Sauvegarde créée.", fg="#5ee38b")

        def do_restore():
            try:
                n = pcopt.restore()
            except Exception as exc:
                messagebox.showerror("OpenFPS", f"Restauration impossible : {exc}", parent=win)
                return
            refresh()
            status.config(text=f"{n} réglage(s) restauré(s).", fg="#5ee38b")

        btn_apply.configure(command=do_apply)
        btn_restore.configure(command=do_restore)
        refresh()
        win.update_idletasks()
        w, h = max(720, win.winfo_reqwidth()), win.winfo_reqheight() + 20
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + 40
        win.geometry(f"{w}x{h}+{x}+{y}")

    # -------------------------------------------------------------------- fiche
    def _open_detail(self, g):
        win = tk.Toplevel(self)
        win.title(g.name)
        win.configure(bg=BG)
        w, h = 900, 640
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.minsize(760, 520)
        win.transient(self)
        win.focus_set()

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
        # barre de boutons, conseils et statut ancrés en bas : toujours visibles
        bar = tk.Frame(right, bg=BG)
        bar.pack(side="bottom", fill="x", pady=(4, 0))
        status = tk.Label(right, text="", bg=BG, fg="#5ee38b", anchor="w")
        status.pack(side="bottom", fill="x")
        tips = tk.Label(right, text="", bg=BG, fg=MUTED, anchor="w", wraplength=500,
                        justify="left", font=("Segoe UI", 9))
        tips.pack(side="bottom", fill="x", pady=6)
        why_lbl = tk.Label(right, text="Clique sur un réglage pour voir pourquoi il change.",
                           bg="#202020", fg="#ffd479", anchor="w", wraplength=520,
                           justify="left", font=("Segoe UI", 10), padx=8, pady=6)
        why_lbl.pack(side="bottom", fill="x", pady=(6, 0))
        why_map = {}

        tree_box = tk.Frame(right, bg=BG)
        tree_box.pack(fill="both", expand=True)
        tree = ttk.Treeview(tree_box, columns=cols, show="headings", height=8)
        for col, wd in zip(cols, (270, 110, 110)):
            tree.heading(col, text=col)
            tree.column(col, width=wd)
        def on_select(_e=None):
            sel = tree.selection()
            if sel:
                why_lbl.config(text=why_map.get(sel[0]) or "Réglage ajusté pour gagner en FPS.")
        tree.bind("<<TreeviewSelect>>", on_select)
        vsb = ttk.Scrollbar(tree_box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        btn_opt = ttk.Button(bar, text="Optimiser", style="Accent.TButton")
        btn_res = ttk.Button(bar, text="Restaurer l'original", style="Plain.TButton")
        btn_browse = ttk.Button(bar, text="Choisir le fichier...", style="Plain.TButton")
        btn_opt.pack(side="left")
        btn_res.pack(side="left", padx=6)
        btn_browse.pack(side="left")

        state = {"running": False}

        def watch():
            """Surveille le lancement/la fermeture du jeu et met la fiche à jour."""
            if not win.winfo_exists():
                return
            if g.process and catalog.is_running(g.process) != state["running"]:
                refresh()
            win.after(2000, watch)

        def refresh():
            for w in poster_holder.winfo_children():
                w.destroy()
            self._poster(poster_holder, g, 180, 270, bool(g.find_config()),
                         clickable=False).pack()
            tree.delete(*tree.get_children())
            why_map.clear()
            path = g.find_config()
            path_lbl.config(text=path or "Fichier de config introuvable : lance le jeu une "
                                         "fois, ou utilise « Choisir le fichier... ».")
            running = catalog.is_running(g.process)
            state["running"] = running
            ready = bool(path) and self.env is not None and not running
            btn_opt.state(["!disabled"] if ready else ["disabled"])
            has_backup = bool(path) and os.path.exists(path + catalog.BACKUP_SUFFIX)
            btn_res.state(["!disabled"] if has_backup and not running else ["disabled"])
            if self.env is None:
                tips.config(text="Détection de ta configuration en cours...")
                win.after(800, refresh)
                return
            tips.config(text="\n".join(catalog.render_tips(g, self.env)))
            if path:
                try:
                    for ch in catalog.plan(g, path, self.env):
                        iid = tree.insert("", "end", values=(ch.label, ch.old, ch.new))
                        why_map[iid] = ch.why
                except OSError as exc:
                    status.config(text=f"Lecture impossible : {exc}", fg="#ff6b6b")
            if running:
                status.config(text=f"{g.name} est lancé : ferme le jeu pour pouvoir optimiser "
                                   "(il réécrirait sinon ses réglages à la fermeture).",
                              fg="#ffb347")
            elif path and not tree.get_children():
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

        # dimensionne la fenêtre selon son contenu pour que les boutons ne soient jamais coupés
        if g.process:
            win.after(2000, watch)
        win.update_idletasks()
        w = max(900, win.winfo_reqwidth())
        h = max(640, win.winfo_reqheight() + 24)
        h = min(h, max(480, self.winfo_screenheight() - 80))
        x = max(0, self.winfo_rootx() + (self.winfo_width() - w) // 2)
        y = max(0, min(self.winfo_rooty(), self.winfo_screenheight() - h - 40))
        win.geometry(f"{w}x{h}+{x}+{y}")


def run():
    App().mainloop()
