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
        self.html = '<html lang="en"><head><title>BrandAgent</title><meta name="description" content="Intro"><link href="styles.css" rel="stylesheet"><script src="app.js" defer></script></head><body><h1 id="main">Intro</h1><a href="#main">Read</a><img src="assets/mark.svg" alt="Workspace"></body></html>'
        (self.root / 'index.html').write_text(self.html, encoding='utf-8')

    def test_checked_in_site_matches_shared_sources(self):
        source = SCRIPT.with_name('generate_pages_site.py')
        build_spec = importlib.util.spec_from_file_location('generate_pages_site', source)
        generator = importlib.util.module_from_spec(build_spec)
        build_spec.loader.exec_module(generator)
        for name, expected in generator.build_outputs().items():
            self.assertEqual((module.SITE / name).read_text(), expected)

    def test_rejects_inline_style_blocked_by_production_csp(self):
        (self.root / 'index.html').write_text(self.html.replace('<h1 ', '<h1 style="color:red" '))
        with self.assertRaises(ValueError):
            module.validate_site(self.root)

    def test_valid_static_bundle(self):
        module.validate_site(self.root)

    def test_canonical_only_allows_the_known_public_origin(self):
        path = self.root / 'index.html'
        path.write_text(self.html.replace('</head>', '<link rel="canonical" href="https://brandagent.pages.dev/"></head>'))
        module.validate_site(self.root)
        path.write_text(path.read_text().replace('https://brandagent.pages.dev/', 'https://other.example/'))
        with self.assertRaises(ValueError):
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
        path = self.root / 'assets/mark.svg'
        path.unlink()
        path.symlink_to(self.root / 'index.html')
        with self.assertRaises(ValueError):
            module.validate_site(self.root)

    def test_rejects_missing_asset_and_path_escape(self):
        for source in ('missing.png', '../private.png', 'https://example.com/tracker.js'):
            with self.subTest(source=source):
                (self.root / 'index.html').write_text(self.html.replace('assets/mark.svg', source), encoding='utf-8')
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
