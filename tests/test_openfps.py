import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openfps import catalog, formula, scoring  # noqa: E402
from openfps.hardware import Hardware  # noqa: E402

OPTIONS = 'renderDistance:20\nsimulationDistance:20\nmaxFps:60\nenableVsync:true\n' \
          'graphicsMode:2\nparticles:0\nrenderClouds:"true"\nunrelated:keep\n'


def hw(gpu, threads=8, ram=16, w=1920, h=1080, vram=0, integrated=False):
    return Hardware(gpu_name=gpu, cpu_threads=threads, ram_gb=ram, screen_w=w,
                    screen_h=h, vram_gb=vram, gpu_integrated=integrated)


class FormulaTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(formula.evaluate("clamp(5 * 3, 0, 10)", {}), 10)
        self.assertEqual(formula.evaluate("1 if gpu < 5 else 2", {"gpu": 3}), 1)

    def test_rejects_code(self):
        for bad in ("__import__('os').system('x')", "open('f')", "().__class__", "x.y", "[1]"):
            with self.assertRaises(formula.FormulaError):
                formula.evaluate(bad, {"x": 1})


class ScoringTests(unittest.TestCase):
    def test_ordering(self):
        self.assertGreater(scoring.gpu_score("NVIDIA GeForce RTX 4080"),
                           scoring.gpu_score("NVIDIA GeForce GTX 1650"))
        self.assertGreater(scoring.gpu_score("NVIDIA GeForce GTX 1650"),
                           scoring.gpu_score("Intel(R) UHD Graphics 620"))

    def test_unknown_uses_vram(self):
        self.assertGreater(scoring.gpu_score("Mystery GPU", 8), scoring.gpu_score("Mystery GPU", 2))


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.game = next(g for g in catalog.load_catalog() if g.id == "minecraft_java")
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "options.txt")
        with open(self.path, "w", newline="") as f:
            f.write(OPTIONS)

    def read(self):
        with open(self.path) as f:
            return dict(l.split(":", 1) for l in f.read().splitlines())

    def test_low_end_gets_lower_settings_than_high_end(self):
        low = scoring.variables(hw("Intel(R) UHD Graphics 620", 4, 8, integrated=True))
        high = scoring.variables(hw("NVIDIA GeForce RTX 4090", 24, 32))
        catalog.apply(self.game, self.path, low)
        low_rd = int(self.read()["renderDistance"])
        catalog.restore(self.path)
        catalog.apply(self.game, self.path, high)
        high_rd = int(self.read()["renderDistance"])
        self.assertLess(low_rd, high_rd)

    def test_quotes_preserved_and_unrelated_kept(self):
        env = scoring.variables(hw("NVIDIA GeForce GTX 1650"))
        catalog.apply(self.game, self.path, env)
        d = self.read()
        self.assertEqual(d["renderClouds"], '"false"')
        self.assertEqual(d["unrelated"], "keep")
        self.assertEqual(d["enableVsync"], "false")
        self.assertEqual(d["maxFps"], "260")

    def test_missing_keys_not_added(self):
        env = scoring.variables(hw("NVIDIA GeForce GTX 1650"))
        catalog.apply(self.game, self.path, env)
        self.assertNotIn("biomeBlendRadius", self.read())

    def test_backup_and_restore(self):
        env = scoring.variables(hw("NVIDIA GeForce GTX 1650"))
        catalog.apply(self.game, self.path, env)
        catalog.apply(self.game, self.path, scoring.variables(hw("NVIDIA GeForce RTX 4090")))
        self.assertTrue(catalog.restore(self.path))  # l'original, pas la 1re optimisation
        with open(self.path) as f:
            self.assertEqual(f.read(), OPTIONS)

    def test_idempotent(self):
        env = scoring.variables(hw("NVIDIA GeForce GTX 1650"))
        catalog.apply(self.game, self.path, env)
        self.assertEqual(catalog.apply(self.game, self.path, env), [])

    def test_tips_rendered(self):
        env = scoring.variables(hw("x", ram=16))
        self.assertIn("-Xmx6G", catalog.render_tips(self.game, env)[0])


if __name__ == "__main__":
    unittest.main()


class DiscoveryTests(unittest.TestCase):
    def test_unreal_games_are_discovered_and_optimized(self):
        root = tempfile.mkdtemp()
        local = os.path.join(root, "AppData", "Local")
        cfg = os.path.join(local, "CoolGame", "Saved", "Config", "WindowsNoEditor")
        os.makedirs(cfg)
        ini = os.path.join(cfg, "GameUserSettings.ini")
        with open(ini, "w") as f:
            f.write("[ScalabilityGroups]\nsg.ShadowQuality=3\nsg.ViewDistanceQuality=3\n"
                    "[/Script/Engine.GameUserSettings]\nbUseVSync=True\nFrameRateLimit=60.000000\n")
        os.environ["LOCALAPPDATA"] = local
        games = [g for g in catalog.load_catalog() if g.id.startswith("ue:")]
        self.assertEqual([g.name for g in games], ["CoolGame (Unreal Engine, auto)"])
        env = scoring.variables(hw("Intel(R) UHD Graphics 620", 4, 8, integrated=True))
        catalog.apply(games[0], ini, env)
        text = open(ini).read()
        self.assertIn("sg.ShadowQuality=0", text)
        self.assertIn("bUseVSync=False", text)
        self.assertIn("FrameRateLimit=0", text)
        self.assertTrue(catalog.restore(ini))
        self.assertIn("sg.ShadowQuality=3", open(ini).read())


class PopularGamesTests(unittest.TestCase):
    def _game(self, gid):
        return next(g for g in catalog.load_catalog() if g.id == gid)

    def test_apex_vdf_format_and_read_only(self):
        import stat
        tmp = tempfile.mkdtemp()
        os.environ["USERPROFILE"] = tmp
        d = os.path.join(tmp, "Saved Games", "Respawn", "Apex", "local")
        os.makedirs(d)
        f = os.path.join(d, "videoconfig.txt")
        with open(f, "w") as fh:
            fh.write('"VideoConfig"\n{\n\t"setting.csm_enabled"\t\t"1"\n'
                     '\t"setting.mat_vsync_mode"\t\t"2"\n\t"setting.other"\t\t"keep"\n}\n')
        g = self._game("apex_legends")
        env = scoring.variables(hw("Intel(R) UHD Graphics 620", 4, 8, integrated=True))
        catalog.apply_all(g, env)
        text = open(f).read()
        self.assertIn('"setting.csm_enabled"\t\t"0"', text)
        self.assertIn('"setting.mat_vsync_mode"\t\t"0"', text)
        self.assertIn('"setting.other"\t\t"keep"', text)
        self.assertTrue(text.startswith('"VideoConfig"\n{'))
        self.assertFalse(os.stat(f).st_mode & stat.S_IWRITE)  # verrouillé
        self.assertEqual(catalog.restore_all(g), 1)
        self.assertTrue(os.stat(f).st_mode & stat.S_IWRITE)  # rendu modifiable
        self.assertIn('"setting.csm_enabled"\t\t"1"', open(f).read())

    def test_cs2_glob_with_parentheses_env_var(self):
        tmp = tempfile.mkdtemp()
        os.environ["ProgramFiles(x86)"] = tmp
        d = os.path.join(tmp, "Steam", "userdata", "12345", "730", "local", "cfg")
        os.makedirs(d)
        f = os.path.join(d, "cs2_video.txt")
        with open(f, "w") as fh:
            fh.write('"video.cfg"\n{\n\t"setting.msaa_samples"\t\t"8"\n}\n')
        g = self._game("cs2")
        self.assertEqual(g.find_all(), [f])
        catalog.apply_all(g, scoring.variables(hw("NVIDIA GeForce GTX 1650")))
        self.assertIn('"setting.msaa_samples"\t\t"0"', open(f).read())

    def test_valorant_multiple_account_folders_grouped(self):
        tmp = tempfile.mkdtemp()
        local = os.path.join(tmp, "AppData", "Local")
        files = []
        for sub in (("VALORANT", "Saved", "Config", "WindowsClient"),
                    ("VALORANT", "Saved", "Config", "abc-eu", "Windows"),
                    ("VALORANT", "Saved", "Config", "def-eu", "Windows")):
            d = os.path.join(local, *sub)
            os.makedirs(d)
            f = os.path.join(d, "GameUserSettings.ini")
            open(f, "w").write("[ScalabilityGroups]\nsg.ShadowQuality=3\n")
            files.append(f)
        os.environ["LOCALAPPDATA"] = local
        games = [g for g in catalog.load_catalog() if g.id.startswith("ue:")]
        self.assertEqual([g.name for g in games], ["Valorant (Unreal Engine, auto)"])
        catalog.apply_all(games[0], scoring.variables(hw("NVIDIA GeForce GTX 1650")))
        for f in files:
            self.assertIn("sg.ShadowQuality=0", open(f).read())


class CoverTests(unittest.TestCase):
    def test_steam_cache_old_and_new_layout_and_user_override(self):
        from openfps import covers
        tmp = tempfile.mkdtemp()
        steam = os.path.join(tmp, "Steam")
        cache = os.path.join(steam, "appcache", "librarycache")
        os.makedirs(os.path.join(cache, "730", "abcdef"))
        new = os.path.join(cache, "730", "abcdef", "library_600x900.jpg")
        open(new, "w").close()
        old = os.path.join(cache, "1172470_library_600x900.jpg")
        open(old, "w").close()
        os.environ["ProgramFiles(x86)"] = tmp
        os.environ["APPDATA"] = os.path.join(tmp, "Roaming")
        cs2 = next(g for g in catalog.load_catalog() if g.id == "cs2")
        apex = next(g for g in catalog.load_catalog() if g.id == "apex_legends")
        self.assertEqual(covers.find_cover(cs2), new)
        self.assertEqual(covers.find_cover(apex), old)
        mc = next(g for g in catalog.load_catalog() if g.id == "minecraft_java")
        self.assertIsNone(covers.find_cover(mc))
        mine = os.path.join(covers.user_covers_dir(), "minecraft_java.png")
        os.makedirs(os.path.dirname(mine))
        open(mine, "w").close()
        self.assertEqual(covers.find_cover(mc), mine)

    def test_tile_colors_are_stable_and_distinct(self):
        from openfps import covers
        self.assertEqual(covers.tile_colors("cs2"), covers.tile_colors("cs2"))
        self.assertNotEqual(covers.tile_colors("cs2"), covers.tile_colors("apex_legends"))
