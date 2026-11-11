// Multi-file upload widget. Wires a drop-area + <input type=file multiple>
// inside `root` so chosen files (click or drag) are listed with a remove button
// and kept in sync with the input's FileList. Mirrors the intake form widget.
function initUpload(root) {
    const input = root.querySelector('input[type=file]');
    const dropArea = root.querySelector('.drop-area');
    const list = root.querySelector('.docs-list');
    const count = root.querySelector('.docs-count');
    let docs = [];  // chosen files; the input's FileList is rebuilt from this

    dropArea.addEventListener('click', () => input.click());

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

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
}
