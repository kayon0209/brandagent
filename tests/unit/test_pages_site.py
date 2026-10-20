"""Release-boundary tests for the public static site, without app dependencies."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_pages_site.py'
spec = importlib.util.spec_from_file_location('verify_pages_site', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PagesReleaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir()
        for name in module.EXPECTED_FILES:
            (self.root / name).write_text('fixture', encoding='utf-8')
        self.html = '<html lang="en"><head><title>BrandAgent</title><meta name="description" content="Intro"><link href="styles.css" rel="stylesheet"><script src="app.js" defer></script></head><body><h1 id="main">Intro</h1><a href="#main">Read</a><img src="assets/workspace.png" alt="Workspace"></body></html>'
        (self.root / 'index.html').write_text(self.html, encoding='utf-8')

    def test_valid_static_bundle(self):
        module.validate_site(self.root)

    def test_rejects_accidental_environment_or_server_upload(self):
        for name in ('.env.local', '_worker.js', 'functions/api.js'):
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text('must not publish', encoding='utf-8')
                with self.assertRaises(ValueError):
                    module.validate_site(self.root)
                path.unlink()

    def test_rejects_symlink_to_a_file_outside_bundle(self):
        path = self.root / 'assets/workspace.png'
        path.unlink()
        path.symlink_to(self.root / 'index.html')
        with self.assertRaises(ValueError):
            module.validate_site(self.root)

    def test_rejects_missing_asset_and_path_escape(self):
        for source in ('missing.png', '../private.png', 'https://example.com/tracker.js'):
            with self.subTest(source=source):
                (self.root / 'index.html').write_text(self.html.replace('assets/workspace.png', source), encoding='utf-8')
                with self.assertRaises(ValueError):
                    module.validate_site(self.root)

    def test_rejects_duplicate_ids_and_broken_anchor(self):
        for html in (self.html.replace('</body>', '<p id="main">Duplicate</p></body>'), self.html.replace('href="#main"', 'href="#missing"')):
            with self.subTest(html=html):
                (self.root / 'index.html').write_text(html, encoding='utf-8')
                with self.assertRaises(ValueError):
                    module.validate_site(self.root)


if __name__ == '__main__':
    unittest.main()
