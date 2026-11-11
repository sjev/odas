// Shared logic for the "add log entry" form used on zaak and dossier pages.

function initLogForm() {
    const logForm = document.getElementById('log-form');
    const logNewBtn = document.getElementById('log-new-btn');
    if (!logForm || !logNewBtn) return;

    const logDocs = document.getElementById('log-docs');
    if (logDocs) initUpload(logDocs);

    function showLogForm() {
        logNewBtn.hidden = true;
        logForm.hidden = false;
        logForm.querySelector('textarea[name="body"]').focus();
    }
    logNewBtn.addEventListener('click', showLogForm);
    if (!logForm.hidden) showLogForm();  // validation error: form already open

    initMailFooter(logForm);
    initSendButton(logForm);
}

// Without a recipient there is nothing to send, so the button stays off until
// Aan or Cc holds text. The server checks the same rule on the way in.
function initSendButton(logForm) {
    const sendBtn = logForm.querySelector('.btn-send');
    if (!sendBtn) return;

    const boxes = [...logForm.querySelectorAll('[name="aan"], [name="cc"]')];
    const update = () => {
        sendBtn.disabled = !boxes.some(b => b.value.trim());
    };
    boxes.forEach(b => b.addEventListener('input', update));
    update();  // a validation error brings the typed recipients back

    const known = (logForm.dataset.known || '').split(',').filter(Boolean);
    let confirmed = false;
    sendBtn.addEventListener('click', event => {
        if (confirmed) return;
        event.preventDefault();
        confirmSend(boxes, known, () => {
            confirmed = true;
            logForm.requestSubmit(sendBtn);
        });
    });
}

// A wrong address cannot be called back, so every recipient is shown once more.
function confirmSend(boxes, known, send) {
    const dialog = document.createElement('dialog');
    dialog.className = 'send-dialog';
    const article = document.createElement('article');
    const heading = document.createElement('h3');
    heading.textContent = 'E-mail versturen aan';
    article.append(heading);
    boxes.filter(b => b.value.trim()).forEach(box => {
        const line = document.createElement('p');
        const label = document.createElement('b');
        label.textContent = box.name === 'cc' ? 'Cc: ' : 'Aan: ';
        line.append(label);
        markRecipients(box.value, known).forEach((r, i) => {
            if (i) line.append(', ');
            const span = document.createElement('span');
            span.textContent = r.text;
            if (r.unknown) {
                span.className = 'addr-unknown';
                span.title = 'niet de indiener en geen teamlid';
            }
            line.append(span);
        });
        article.append(line);
    });
    const footer = document.createElement('footer');
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'secondary';
    cancel.textContent = 'Annuleren';
    cancel.autofocus = true;
    const ok = document.createElement('button');
    ok.type = 'button';
    ok.textContent = 'Versturen';
    footer.append(cancel, ok);
    article.append(footer);
    dialog.append(article);
    document.body.append(dialog);

    dialog.addEventListener('close', () => dialog.remove());
    cancel.addEventListener('click', () => dialog.close());
    ok.addEventListener('click', () => { dialog.close(); send(); });
    dialog.showModal();
}

// The recipients as typed, each marked when it is neither the zaak's own nor a
// colleague's. A comma inside a quoted name does not split it.
function markRecipients(line, known) {
    return (line.match(/("[^"]*"|[^,])+/g) || []).map(s => s.trim()).filter(Boolean).map(text => {
        const found = text.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/);
        return { text, unknown: !found || !known.includes(found[0].toLowerCase()) };
    });
}

// The closing line the data dir offers. A filled Aan says a mail is meant, so the
// line goes in there. A person reads it, and may change or remove it, before it goes.
function initMailFooter(logForm) {
    const footer = logForm.dataset.footer;
    const aan = logForm.querySelector('[name="aan"]');
    if (!footer || !aan) return;

    const body = logForm.querySelector('textarea[name="body"]');
    aan.addEventListener('change', () => {
        if (!aan.value.trim() || body.value.includes(footer)) return;
        body.value = body.value.replace(/\s*$/, '') + '\n\n' + footer + '\n';
    });
}

// Clamp long log entries; add a toggle only when the body actually overflows.
function initEntryClamp() {
    document.querySelectorAll('.log-entry .entry-text').forEach(el => {
        el.classList.add('clamped');
        if (el.scrollHeight <= el.clientHeight + 4) {
            el.classList.remove('clamped');  // short entry: leave as-is
            return;
        }
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'entry-toggle';
        btn.textContent = '⌄';
        btn.title = 'Toon meer';
        btn.addEventListener('click', () => {
            const open = el.classList.toggle('expanded');
            el.classList.toggle('clamped', !open);
            btn.classList.toggle('open', open);
            btn.title = open ? 'Toon minder' : 'Toon meer';
        });
        el.after(btn);
    });
}

if (typeof module !== 'undefined') module.exports = { markRecipients };
