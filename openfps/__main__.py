"""Point d'entrée : sans argument -> interface graphique ; sinon ligne de commande."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, catalog, hardware, scoring


def _find(games, gid):
    for g in games:
        if g.id == gid:
            return g
    sys.exit(f"Jeu inconnu: {gid}. Voir: openfps list")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openfps", description="Optimise un jeu pour le max de FPS.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="ouvre l'interface graphique (défaut)")
    sub.add_parser("list", help="liste le catalogue")
    sub.add_parser("hardware", help="affiche la config détectée et les scores")
    for name, helptext in (("optimize", "optimise un jeu"), ("restore", "restaure la config d'origine")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("game")
        p.add_argument("--path", help="chemin du fichier de config (sinon auto)")
        if name == "optimize":
            p.add_argument("--dry-run", action="store_true", help="affiche sans écrire")
    args = ap.parse_args(argv)

    if args.cmd in (None, "gui"):
        try:
            from .gui import run
        except ImportError as exc:
            print(f"Interface graphique indisponible ({exc}). Utilise la CLI: openfps --help")
            return 1
        run()
        return 0

    games = catalog.load_catalog()

    if args.cmd == "list":
        for g in games:
            found = g.find_config()
            print(f"{g.id:20} {g.name:32} {'installé' if found else 'non trouvé'}")
        return 0

    hw = hardware.detect()
    env = scoring.variables(hw)

    if args.cmd == "hardware":
        print(json.dumps({"hardware": hw.to_dict(), "scores": env}, indent=2, ensure_ascii=False))
        return 0

    game = _find(games, args.game)
    if args.path:
        game.custom_path = args.path
    path = game.find_config()
    if not path:
        print(f"Fichier de config introuvable pour {game.name}. Lance le jeu une fois, ou utilise --path.")
        return 1

    if args.cmd == "restore":
        n = catalog.restore_all(game) if not args.path else int(catalog.restore(path))
        print(f"{n} fichier(s) restauré(s)." if n else "Aucune sauvegarde trouvée.")
        return 0

    changes = (catalog.plan(game, path, env) if args.dry_run
               else (catalog.apply(game, path, env) if args.path else catalog.apply_all(game, env)))
    print(f"{game.name} - GPU {env['gpu']}/100, CPU {env['cpu']}/100, RAM {hw.ram_gb} Go")
    for c in changes:
        print(f"  {c.key:24} {c.old} -> {c.new}")
    if not changes:
        print("  Déjà optimisé.")
    for t in catalog.render_tips(game, env):
        print(f"  conseil: {t}")
    if args.dry_run:
        print("(simulation, rien n'a été écrit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
