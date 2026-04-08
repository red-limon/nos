# CodeMirror console bundle

Single ESM bundle for the node panel Python editor so only one instance of `@codemirror/state` is loaded (avoids "Unrecognized extension value" errors).

**Rebuild after changing dependencies or entry.js:**

```bash
cd src/nos/www/static/js/codemirror-console-src
npm install   # only when package.json changes
npm run build
```

Output: `../codemirror-console.bundle.js` (used by `node_form_panel.html`).
