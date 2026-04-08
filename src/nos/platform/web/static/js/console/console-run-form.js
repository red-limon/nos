/**
 * Engine run form: render form from schema and handle file upload before submit.
 * Used by console_old (engine_console.html, run.html). Logic lives here so the
 * templates stay minimal and use dedicated JS for form + upload.
 *
 * Requires: UploadProgress (upload_progress.js) for file upload with progress.
 * Usage: EngineRunForm.renderFormFromSchema(formSchema, container, onSubmit, appendOutput);
 */

(function (global) {
    'use strict';

    var UPLOAD_URL = '/api/upload/temp';

    /** Canonical field rows match ``input_form_mapping.FormFieldSchema.to_dict`` (required, description, accept, …). Legacy API rows used nested validation + helpText; normalize here so one renderer covers both. */
    function fieldRequired(f) {
        if (f.validation && f.validation.required) return true;
        return !!f.required;
    }
    function fieldHelpText(f) {
        return f.helpText || f.description || '';
    }
    function fieldFileAccept(f) {
        if (f.validation && f.validation.accept != null) return f.validation.accept;
        return f.accept || '';
    }
    function fieldFileMultiple(f) {
        if (f.validation && f.validation.multiple) return true;
        return !!f.multiple;
    }
    function fieldFileMaxMb(f) {
        if (f.validation && f.validation.maxSizeMb != null) return f.validation.maxSizeMb;
        if (f.extra && f.extra.maxSizeMb != null) return f.extra.maxSizeMb;
        return null;
    }

    function renderFormFromSchema(formSchema, container, onSubmit, appendOutput) {
        var formContainer = document.createElement('div');
        formContainer.className = 'form-container';
        var title = formSchema.title || 'Form';
        var fields = formSchema.fields || [];
        var html = '<h3>' + title + '</h3>';
        if (formSchema.description) {
            html += '<p style="color:#858585;font-size:0.9rem;margin-bottom:0.75rem">' + formSchema.description + '</p>';
        }
        html += '<form id="engine-form-run" style="margin:0">';
        fields.forEach(function (f) {
            var name = f.name || '';
            var label = f.label || name;
            var fieldType = (f.type || 'text').toLowerCase();
            var val = f.value !== undefined && f.value !== null ? f.value : '';
            var req = fieldRequired(f) ? ' required' : '';
            var ht = fieldHelpText(f);
            var help = ht ? '<span class="help">' + ht + '</span>' : '';
            if (fieldType === 'checkbox') {
                html += '<div class="form-field"><label><input type="checkbox" name="' + name + '" value="1"' + (val ? ' checked' : '') + req + '> ' + label + '</label>' + help + '</div>';
            } else if (fieldType === 'select') {
                var opts = (f.options || []).map(function (o) {
                    return '<option value="' + (o.value || '') + '"' + (o.selected ? ' selected' : '') + '>' + (o.label || o.value) + '</option>';
                }).join('');
                html += '<div class="form-field"><label>' + label + '</label><select name="' + name + '"' + req + '>' + opts + '</select>' + help + '</div>';
            } else if (fieldType === 'textarea') {
                html += '<div class="form-field"><label>' + label + '</label><textarea name="' + name + '" rows="3"' + req + '>' + val + '</textarea>' + help + '</div>';
            } else if (fieldType === 'json') {
                // Dict/List/object field: JSON textarea — body filled via .value after innerHTML so
                // we never HTML-escape < > inside JSON (would break JSON.parse on submit).
                var rows = f.rows || 4;
                html += '<div class="form-field"><label>' + label + ' <small style="font-weight:normal;color:#888">(JSON)</small></label>'
                    + '<textarea name="' + name + '" rows="' + rows + '" data-decode="json"' + req + '></textarea>' + help + '</div>';
            } else if (fieldType === 'file') {
                var acc = fieldFileAccept(f);
                var accept = acc ? ' accept="' + String(acc).replace(/"/g, '&quot;') + '"' : '';
                var mult = fieldFileMultiple(f) ? ' multiple' : '';
                var maxMb = fieldFileMaxMb(f);
                var hint = maxMb != null ? ' (max ' + maxMb + ' MB)' : '';
                html += '<div class="form-field" data-field-name="' + name + '" data-file-field="1"><label>' + label + hint + '</label><input type="file" name="' + name + '"' + accept + mult + '>' + help + '<div class="upload-progress-placeholder" style="min-height:0"></div></div>';
            } else {
                var placeholder = f.placeholder ? ' placeholder="' + f.placeholder + '"' : '';
                html += '<div class="form-field"><label>' + label + '</label><input type="' + fieldType + '" name="' + name + '" value="' + String(val).replace(/"/g, '&quot;') + '"' + placeholder + req + '>' + help + '</div>';
            }
        });
        html += '<button type="submit">' + (formSchema.submitLabel || 'Run') + '</button></form>';
        formContainer.innerHTML = html;
        container.appendChild(formContainer);
        if (container.scrollTop !== undefined) {
            container.scrollTop = container.scrollHeight;
        }
        var form = formContainer.querySelector('form');
        fields.forEach(function (f) {
            if ((f.type || 'text').toLowerCase() !== 'json') return;
            var nm = f.name;
            if (!nm || !form.elements[nm]) return;
            var ta = form.elements[nm];
            if (!ta || ta.tagName !== 'TEXTAREA') return;
            var v = f.value !== undefined && f.value !== null ? f.value : '';
            var jsonVal = (v !== null && v !== undefined && v !== '') ? v : '{}';
            if (typeof jsonVal === 'object') {
                try {
                    jsonVal = JSON.stringify(jsonVal, null, 2);
                } catch (e) {
                    jsonVal = String(jsonVal);
                }
            }
            ta.value = String(jsonVal);
        });
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var fd = new FormData(form);
            var data = {};
            fd.forEach(function (v, k) { data[k] = v; });
            var fileFields = fields.filter(function (f) { return (f.type || '').toLowerCase() === 'file'; });
            var uploadPromises = [];
            fileFields.forEach(function (f) {
                var input = form.querySelector('input[name="' + (f.name || '') + '"]');
                if (!input || !input.files || input.files.length === 0) {
                    if (fieldRequired(f)) data[f.name] = '';
                    return;
                }
                var placeholder = formContainer.querySelector('.form-field[data-field-name="' + f.name + '"] .upload-progress-placeholder');
                var uploadFd = new FormData();
                for (var i = 0; i < input.files.length; i++) {
                    uploadFd.append(input.files.length > 1 ? 'files[]' : 'file', input.files[i]);
                }
                var uploadMaxMb = fieldFileMaxMb(f);
                if (uploadMaxMb != null) {
                    uploadFd.append('max_size_mb', String(uploadMaxMb));
                }
                var uploadAccept = fieldFileAccept(f);
                if (uploadAccept) {
                    uploadFd.append('accept', uploadAccept);
                }
                var fieldName = f.name;
                var multiple = fieldFileMultiple(f);
                uploadPromises.push(
                    (global.UploadProgress && global.UploadProgress.uploadWithProgress
                        ? global.UploadProgress.uploadWithProgress(UPLOAD_URL, uploadFd, { progressContainer: placeholder })
                        : Promise.resolve({ success: false, error: 'UploadProgress not loaded', uploads: [] })
                    ).then(function (res) {
                        if (!res.success) {
                            throw new Error(res.error || 'Upload failed');
                        }
                        if (multiple && res.uploads && res.uploads.length > 0) {
                            data[fieldName] = res.uploads.map(function (u) { return u.upload_id; });
                        } else if (res.uploads && res.uploads.length > 0) {
                            data[fieldName] = res.uploads[0].upload_id;
                        } else {
                            data[fieldName] = '';
                        }
                    })
                );
            });
            // Decode JSON fields (data-decode="json") back to objects before submit.
            form.querySelectorAll('textarea[data-decode="json"]').forEach(function (ta) {
                var k = ta.name;
                if (!k || !(k in data)) return;
                var raw = String(data[k] == null ? '' : data[k]).trim();
                if (raw === '') {
                    return;
                }
                try {
                    data[k] = JSON.parse(raw);
                    return;
                } catch (e1) { /* try fallbacks */ }
                // Loose URL list: [https://a,https://b] (not valid JSON)
                if (/^\[[\s\S]+\]$/.test(raw) && raw.indexOf('"') === -1 && raw.indexOf("'") === -1) {
                    var inner = raw.slice(1, -1).trim();
                    var parts = inner.split(',').map(function (p) { return p.trim(); }).filter(Boolean);
                    if (parts.length && parts.every(function (p) { return /^https?:\/\//i.test(p); })) {
                        data[k] = parts;
                        return;
                    }
                }
                // Leave as raw string; backend may still coerce (e.g. urls).
            });

            if (uploadPromises.length === 0) {
                formContainer.remove();
                onSubmit(data);
                return;
            }
            Promise.all(uploadPromises).then(function () {
                formContainer.remove();
                onSubmit(data);
            }).catch(function (err) {
                if (typeof appendOutput === 'function') {
                    appendOutput('Upload error: ' + (err && err.message ? err.message : String(err)), 'error');
                }
            });
        });
    }

    global.EngineRunForm = {
        renderFormFromSchema: renderFormFromSchema
    };
})(typeof window !== 'undefined' ? window : this);
