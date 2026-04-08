"""
Load and parse markdown documentation files.

To generate static docs.html: python -m nos.web.export_docs
"""

import re
from pathlib import Path
from typing import List, Dict, Any
import markdown
from markdown.extensions import codehilite, fenced_code, tables


def parse_markdown_file(file_path: Path) -> Dict[str, Any]:
    """
    Parse a markdown file and extract structure.
    
    Returns:
        Dictionary with:
        - title: File title (first h1 or filename)
        - h1_sections: List of h1 sections with nested h2/h3
        - html_content: Full HTML content
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Get file title (first h1 or filename)
    first_h1_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    file_title = first_h1_match.group(1) if first_h1_match else file_path.stem
    
    # Parse headings structure
    lines = content.split('\n')
    h1_sections = []
    current_h1 = None
    current_h2 = None
    
    for i, line in enumerate(lines):
        # H1
        h1_match = re.match(r'^#\s+(.+)$', line)
        if h1_match:
            if current_h1:
                h1_sections.append(current_h1)
            current_h1 = {
                'title': h1_match.group(1),
                'anchor': slugify(h1_match.group(1)),
                'h2_sections': [],
                'line_number': i
            }
            current_h2 = None
            continue
        
        # H2
        h2_match = re.match(r'^##\s+(.+)$', line)
        if h2_match:
            if current_h1:
                if current_h2:
                    current_h1['h2_sections'].append(current_h2)
                current_h2 = {
                    'title': h2_match.group(1),
                    'anchor': slugify(h2_match.group(1)),
                    'h3_sections': [],
                    'line_number': i
                }
            continue
        
        # H3
        h3_match = re.match(r'^###\s+(.+)$', line)
        if h3_match:
            if current_h2 and current_h1:
                current_h2['h3_sections'].append({
                    'title': h3_match.group(1),
                    'anchor': slugify(h3_match.group(1)),
                    'line_number': i
                })
            continue
    
    # Add last h1 and h2
    if current_h2 and current_h1:
        current_h1['h2_sections'].append(current_h2)
    if current_h1:
        h1_sections.append(current_h1)
    
    # Convert markdown to HTML
    md = markdown.Markdown(
        extensions=[
            'codehilite',
            'fenced_code',
            'tables',
            'nl2br',
            'sane_lists'
        ]
    )
    html_content = md.convert(content)
    
    # Add anchors to headings in HTML
    html_content = add_anchors_to_headings(html_content)
    
    return {
        'id': file_path.stem.lower().replace(' ', '-'),
        'title': file_title,
        'filename': file_path.name,
        'h1_sections': h1_sections,
        'html_content': html_content
    }


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and special chars with hyphens
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def add_anchors_to_headings(html: str) -> str:
    """Add anchor IDs to all headings in HTML."""
    # H1
    html = re.sub(
        r'<h1>(.+?)</h1>',
        lambda m: f'<h1 id="{slugify(m.group(1))}">{m.group(1)}</h1>',
        html
    )
    # H2
    html = re.sub(
        r'<h2>(.+?)</h2>',
        lambda m: f'<h2 id="{slugify(m.group(1))}">{m.group(1)}</h2>',
        html
    )
    # H3
    html = re.sub(
        r'<h3>(.+?)</h3>',
        lambda m: f'<h3 id="{slugify(m.group(1))}">{m.group(1)}</h3>',
        html
    )
    return html


def load_all_docs() -> List[Dict[str, Any]]:
    """Load all markdown files from docs/ and parse to HTML."""
    docs = []
    project_root = Path(__file__).parent.parent.parent.parent
    docs_dir = project_root / 'docs'
    if docs_dir.exists():
        for md_file in sorted(docs_dir.glob('*.md')):
            try:
                doc = parse_markdown_file(md_file)
                docs.append(doc)
            except Exception as e:
                print(f"Error parsing {md_file}: {e}")
    return docs
