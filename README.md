# OpenFPS

Optimiseur de FPS open source pour Windows. Tu choisis un jeu dans le catalogue, tu cliques sur **Optimiser** : OpenFPS détecte ta configuration (CPU, GPU, RAM, résolution d'écran), calcule des réglages par formules et les écrit dans le fichier de config du jeu. Pas d'IA, pas de réseau, tout est local et lisible.

> Objectif : le maximum de FPS, quitte à baisser la qualité graphique.

## Installer

1. Va dans l'onglet **Releases** du dépôt et télécharge `OpenFPS.exe`.
2. Lance-le, choisis ton jeu, clique sur **Optimiser**.

Une sauvegarde `fichier.openfps.bak` de ta config d'origine est créée au premier passage. Le bouton **Restaurer l'original** la remet en place.

## Comment ça marche

1. **Détection** : `nvidia-smi` si présent, sinon PowerShell/WMI pour le GPU ; API Windows pour la RAM ; nombre de threads CPU ; résolution de l'écran.
2. **Scores 0-100** (`openfps/scoring.py`) : GPU via une table de modèles (repli sur la VRAM), CPU = `25 × log2(threads)`, RAM = `Go / 16`. Ce sont des estimations relatives, pas des benchmarks.
3. **Formules** : chaque jeu décrit ses réglages dans un fichier JSON, par exemple `clamp(round((4 + gpu * 0.10) / max(res_ratio, 1) ** 0.5), 4, 16)`. Un évaluateur sécurisé n'autorise que l'arithmétique, les conditions et quelques fonctions.

Variables disponibles : `gpu`, `cpu`, `ram`, `threads`, `ram_gb`, `vram_gb`, `width`, `height`, `res_ratio`, `integrated`, `target_fps`, `ram_alloc`.

## Ajouter un jeu

Crée un fichier dans `openfps/games/` (ou dans `%APPDATA%\OpenFPS\games\` sans recompiler) :

```json
{
  "id": "mon_jeu",
  "name": "Mon jeu",
  "paths": ["%APPDATA%\\MonJeu\\settings.cfg"],
  "separator": "=",
  "only_existing": true,
  "settings": [
    {"key": "ViewDistance", "label": "Distance", "formula": "clamp(round(gpu / 10), 2, 10)"}
  ]
}
```

- `separator` : `:`, `=` ou `" "` (format `commande valeur`).
- `only_existing: true` ne modifie que les clés déjà présentes (recommandé : évite de casser une version différente du jeu).
- `separator: "vdf"` pour les fichiers `"clé"  "valeur"` (Source, Apex, CS2).
- `read_only_after: true` verrouille le fichier si le jeu l'écrase à chaque lancement (Restaurer le déverrouille).
- `section` (optionnel, par réglage) pour les fichiers `.ini` avec `[sections]`.
- Les valeurs entre guillemets dans le fichier d'origine gardent leurs guillemets.

Les formats non textuels ou binaires (JSON imbriqué, registre, XML) ne sont pas encore gérés : les contributions sont bienvenues.

## Jeux du catalogue

| Jeu | État |
|---|---|
| Minecraft (Java Edition) | Clés vérifiées sur `options.txt` |
| Apex Legends | `videoconfig.txt` (fichier passé en lecture seule après optimisation) |
| Counter-Strike 2 | `cs2_video.txt`, **expérimental** (Steam Cloud peut réécrire le fichier) |
| Fortnite, Valorant | Détectés via Unreal Engine (voir ci-dessous) |
| **Tous les jeux Unreal Engine installés** | Détection automatique de `%LOCALAPPDATA%\\<Jeu>\\Saved\\Config\\*\\GameUserSettings.ini` |

Les jeux Unreal Engine détectés apparaissent d'eux-mêmes en haut de la liste (réglages `sg.*Quality`, échelle de rendu, limite de FPS, VSync). Seules les clés déjà présentes dans le fichier sont modifiées.

**Call of Duty (Warzone, MW, BO6)** n'est pas encore pris en charge : ses réglages sont dans des fichiers `.cst` dont le format n'est pas documenté. Une contribution avec un fichier d'exemple est la bienvenue.

Les autres moteurs (Unity, Source, etc.) stockent leurs réglages différemment : chaque jeu ou famille de jeux demande un fichier JSON vérifié avant d'être ajouté. Un fichier JSON peut aussi servir de modèle de découverte (clé `discover`, voir `unreal_engine_auto.json`) pour couvrir toute une famille de jeux d'un coup.

## Ligne de commande

```
OpenFPS.exe                      # interface graphique
python -m openfps list
python -m openfps hardware
python -m openfps optimize minecraft_java --dry-run
python -m openfps restore minecraft_java
```

## Développement

```
python -m unittest discover -s tests -v
pip install pyinstaller
pyinstaller --onefile --windowed --name OpenFPS --add-data "openfps/games;openfps/games" run_openfps.py
```

Pousser un tag `v0.1.0` lance le workflow GitHub Actions qui compile l'exe et le publie dans les Releases.

## Limites connues

- Windows uniquement pour le moment (la détection Linux/macOS existe mais n'est pas testée).
- Les tables de scores GPU sont approximatives : corrige-les par pull request.
- Certains jeux en ligne avec anti-triche peuvent surveiller leurs fichiers : n'utilise OpenFPS que sur la config locale permise par le jeu.

## Licence

MIT
