"""Validate the explicit public-only Pages bundle; uses the Python stdlib."""

from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


EXPECTED_FILES = {
    'index.html', 'styles.css', 'app.js', 'robots.txt', '_headers',
    'assets/mark.svg',
}
SITE = Path(__file__).resolve().parents[1] / 'docs/site/brandagent'


class PublicPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.references = []
        self.h1_count = 0
        self.has_title = False
        self.has_description = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        self.h1_count += tag == 'h1'
        self.has_title |= tag == 'title'
        self.has_description |= tag == 'meta' and attrs.get('name') == 'description'
        if 'style' in attrs:
            raise ValueError('Inline styles are blocked by the deployed CSP')
        if tag in {'form', 'iframe'}:
            raise ValueError('This static introduction must not include forms or frames')
        if tag == 'script' and not attrs.get('src'):
            raise ValueError('Inline scripts are blocked by the deployed CSP')
        for attribute in ('src', 'href'):
            if attribute in attrs:
                self.references.append((tag, attribute, attrs[attribute], attrs.get('rel', '')))


def validate_site(root):
    root = Path(root)
    paths = list(root.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError('Symlinks must never enter the public bundle')
    files = {path.relative_to(root).as_posix() for path in paths if path.is_file()}
    if files != EXPECTED_FILES:
        raise ValueError(f'Public file boundary differs: {sorted(files ^ EXPECTED_FILES)}')
    for name in files:
        if (root / name).stat().st_size > 25 * 1024 * 1024:
            raise ValueError(f'Pages single-file limit exceeded: {name}')
    page = PublicPage()
    page.feed((root / 'index.html').read_text(encoding='utf-8'))
    if page.h1_count != 1 or not page.has_title or not page.has_description:
        raise ValueError('Expected one h1 plus title and description')
    if len(page.ids) != len(set(page.ids)):
        raise ValueError('Duplicate HTML IDs')
    for tag, attribute, value, rel in page.references:
        parsed = urlsplit(value)
        if value.startswith('#'):
            if value != '#' and value[1:] not in page.ids:
                raise ValueError(f'Broken section anchor: {value}')
            continue
        if parsed.scheme == 'data' and tag == 'link' and value.startswith('data:image/'):
            continue
        if tag == 'link' and rel == 'canonical' and value == 'https://brandagent.pages.dev/':
            continue
        if tag == 'a' and parsed.scheme == 'https' and parsed.hostname:
            continue
        if parsed.scheme or parsed.netloc:
            raise ValueError(f'Unexpected external resource: {value}')
        relative = unquote(parsed.path)
        if not relative or relative.startswith('/') or '..' in Path(relative).parts:
            raise ValueError(f'Unsafe local asset path: {value}')
        if relative not in files:
            raise ValueError(f'Missing local asset: {value}')
    return sorted(files)


if __name__ == '__main__':
    try:
        files = validate_site(SITE)
    except (OSError, ValueError) as exc:
        sys.exit(f'Pages validation failed: {exc}')
    print(f'Pages public-only bundle validated: {len(files)} files')
    for name in files:
        print(f'  {name}')
