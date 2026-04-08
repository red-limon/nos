/**
 * Single bundle for CodeMirror 6 Python editor (one instance of @codemirror/state).
 * Export: createPythonEditor(containerElement) -> editor facade { value, readOnly, title }
 */
import { EditorState } from '@codemirror/state';
import { EditorView, keymap, lineNumbers } from '@codemirror/view';
import { defaultKeymap } from '@codemirror/commands';
import { indentUnit } from '@codemirror/language';
import { python } from '@codemirror/lang-python';
import { oneDark } from '@codemirror/theme-one-dark';

export function createPythonEditor(container) {
  const state = EditorState.create({
    doc: '',
    extensions: [
      lineNumbers(),
      python(),
      oneDark,
      EditorView.lineWrapping,
      keymap.of(defaultKeymap),
      EditorState.tabSize.of(4),
      indentUnit.of('    ')
    ]
  });
  const cmView = new EditorView({ state, parent: container });
  return {
    get value() { return cmView.state.doc.toString(); },
    set value(v) {
      const doc = cmView.state.doc.toString();
      cmView.dispatch({ changes: { from: 0, to: doc.length, insert: v || '' } });
    },
    get readOnly() { return container.getAttribute('data-readonly') === 'true'; },
    set readOnly(v) {
      container.setAttribute('data-readonly', v ? 'true' : 'false');
      cmView.contentDOM.contentEditable = v ? 'false' : 'true';
      cmView.contentDOM.style.pointerEvents = v ? 'none' : 'auto';
    },
    get title() { return container.title || ''; },
    set title(v) { container.title = v || ''; }
  };
}
