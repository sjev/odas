// Multi-file upload widget. Wires a drop-area + <input type=file multiple>
// inside `root` so chosen files (click or drag) are listed with a remove button
// and kept in sync with the input's FileList.
//
// A form with files goes out by XHR, not as a plain post: an upload can take
// minutes, and a plain post shows nothing meanwhile. A form without files posts
// as it always did.
function initUpload(root) {
    const input = root.querySelector('input[type=file]');
    const dropArea = root.querySelector('.drop-area');
    const list = root.querySelector('.docs-list');
    const count = root.querySelector('.docs-count');
    const form = root.closest('form');
    let docs = [];  // chosen files; the input's FileList is rebuilt from this

    dropArea.addEventListener('click', () => input.click());

    function syncInput() {
        const dt = new DataTransfer();
        docs.forEach(f => dt.items.add(f));
        input.files = dt.files;
        render();
    }

    function addFiles(fileList) {
        for (const f of fileList) {
            if (!docs.some(d => d.name === f.name && d.size === f.size)) docs.push(f);
        }
        syncInput();
    }

    function render() {
        count.textContent = docs.length
            ? (docs.length === 1 ? '1 bestand toegevoegd' : docs.length + ' bestanden toegevoegd')
            : '';
        list.innerHTML = '';
        docs.forEach((f, i) => {
            const li = document.createElement('li');
            const name = document.createElement('span');
            name.className = 'docs-name';
            name.textContent = '📄 ' + f.name;
            const size = document.createElement('span');
            size.className = 'docs-size';
            size.textContent = formatSize(f.size);
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'docs-remove';
            btn.textContent = 'Verwijderen';
            btn.onclick = () => { docs.splice(i, 1); syncInput(); };
            li.append(name, size, btn);
            list.appendChild(li);
        });
    }

    input.addEventListener('change', () => {
        addFiles(input.files);
        if (docs.length === 0) input.value = '';
    });
    ['dragover', 'dragenter'].forEach(ev =>
        dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.add('drop-active'); }));
    ['dragleave', 'drop'].forEach(ev =>
        dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.remove('drop-active'); }));
    dropArea.addEventListener('drop', e => addFiles(e.dataTransfer.files));

    if (!form) return;
    const status = uploadStatus(form);
    form.addEventListener('submit', e => {
        if (!docs.length || e.defaultPrevented) return;
        e.preventDefault();
        sendWithProgress(form, e.submitter, docs, status);
    });
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// A bar and one line of text above the buttons, hidden until a send starts.
function uploadStatus(form) {
    const box = document.createElement('div');
    box.className = 'upload-status';
    box.hidden = true;
    const bar = document.createElement('progress');
    bar.max = 100;
    const text = document.createElement('p');
    text.setAttribute('role', 'status');
    box.append(bar, text);
    const actions = form.querySelector('.form-actions') || form.querySelector('button[type=submit]');
    actions ? actions.before(box) : form.append(box);
    return {
        show(message, percent) {  // percent null: busy, but nobody knows how long
            box.hidden = false;
            box.classList.remove('failed');
            bar.hidden = false;
            if (percent === null) bar.removeAttribute('value'); else bar.value = percent;
            text.textContent = message;
        },
        fail(message) {
            box.hidden = false;
            box.classList.add('failed');
            bar.hidden = true;
            text.textContent = message;
        },
    };
}

// A file the browser cannot read fails the whole post with no reason given:
// one in iCloud that is not on this computer, or one changed after it was chosen.
async function unreadableFile(files) {
    for (const f of files) {
        try {
            await f.slice(0, 1).arrayBuffer();
        } catch {
            return f.name;
        }
    }
    return null;
}

// What a refused save says, read from the page the server sent back. A field's
// own message goes beside the same field here, where the files are still chosen.
function showRefusal(form, html) {
    const page = new DOMParser().parseFromString(html, 'text/html');
    form.querySelectorAll('small.error').forEach(el => el.remove());
    form.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
    for (const msg of page.querySelectorAll('small.error')) {
        const named = msg.parentElement.querySelector('[name]');
        const here = named && form.querySelector(`[name="${CSS.escape(named.name)}"]`);
        if (!here) continue;
        here.setAttribute('aria-invalid', 'true');
        const copy = document.createElement('small');
        copy.className = 'error';
        copy.textContent = msg.textContent;
        here.parentElement.append(copy);
    }
    const alerts = page.querySelectorAll('[role=alert]');
    const found = alerts.length ? alerts : page.querySelectorAll('.error');
    return [...new Set([...found].map(el => el.textContent.trim()).filter(Boolean))].join(' ');
}

// Put the answer in place of this page. Its scripts do not run, so a mail alert
// it holds is opened here.
function showPage(html) {
    const page = new DOMParser().parseFromString(html, 'text/html');
    document.title = page.title;
    document.body.replaceWith(page.body);
    document.querySelectorAll('dialog.mail-alert').forEach(d => d.showModal());
    window.scrollTo(0, 0);
}

async function sendWithProgress(form, submitter, files, status) {
    const buttons = [...form.querySelectorAll('button[type=submit]')];
    const bad = await unreadableFile(files);
    if (bad) {
        return status.fail(`Het bestand '${bad}' kan niet worden gelezen. Verwijder het en voeg het `
            + 'opnieuw toe. Staat het in iCloud of OneDrive? Zet het dan eerst op deze computer.');
    }
    const data = new FormData(form);
    if (submitter && submitter.name) data.append(submitter.name, submitter.value);

    // Not `form.action`: the send button is named `action`, and it shadows the URL.
    const url = new URL(form.getAttribute('action') || '', location.href).href;
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    const done = () => buttons.forEach(b => { b.disabled = false; });
    xhr.upload.onprogress = e => {
        if (!e.lengthComputable) return;
        const percent = Math.floor(100 * e.loaded / e.total);
        status.show(`Uploaden: ${percent}% (${formatSize(e.loaded)} van ${formatSize(e.total)})`, percent);
    };
    xhr.upload.onload = () => status.show('Bestanden ontvangen. Ze worden nu verwerkt…', null);
    xhr.onload = () => {
        if (xhr.status < 400) {
            status.show('Opgeslagen.', 100);
            if (xhr.responseURL !== url) return location.assign(xhr.responseURL);
            showPage(xhr.responseText);  // an answer without a redirect, like the intake receipt
            return;
        }
        done();
        const html = (xhr.getResponseHeader('content-type') || '').includes('text/html');
        status.fail((html && showRefusal(form, xhr.responseText))
            || `Niet opgeslagen: de server gaf fout ${xhr.status}. Probeer het opnieuw.`);
    };
    xhr.onerror = xhr.onabort = () => {
        done();
        status.fail('Het uploaden is niet gelukt: de verbinding viel weg. Uw tekst en bestanden '
            + 'staan er nog. Controleer uw verbinding en probeer het opnieuw.');
    };
    buttons.forEach(b => { b.disabled = true; });
    status.show('Uploaden…', 0);
    xhr.send(data);
}
