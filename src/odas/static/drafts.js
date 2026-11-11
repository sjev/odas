// Unsent text in a form, kept in this browser until the form is sent or cancelled.
// A form opts in with data-draft="name"; data-draft-guard marks an edit form, whose
// draft comes back only over the same saved text it started from. Nothing goes to
// the server. Falls back to memory when the browser blocks storage.
(function (root) {
    const KEY = "odas-drafts";
    const MAX_AGE = 14 * 24 * 3600 * 1000;
    let backend;

    function memory() {
        const map = new Map();
        return {
            getItem: k => (map.has(k) ? map.get(k) : null),
            setItem: (k, v) => map.set(k, v),
            removeItem: k => map.delete(k),
        };
    }

    function use(storage) {
        try {
            storage.getItem(KEY);
            backend = storage;
        } catch (e) {
            backend = memory();
        }
    }

    function all() {
        try {
            const obj = JSON.parse(backend.getItem(KEY) || "{}");
            return obj && typeof obj === "object" ? obj : {};
        } catch (e) {
            return {};
        }
    }

    function put(obj) {
        try { backend.setItem(KEY, JSON.stringify(obj)); } catch (e) {}  // full: keep typing
    }

    function save(key, values, base = null, at = Date.now()) {
        const now = Date.now();
        const kept = Object.fromEntries(Object.entries(all()).filter(([, d]) => now - d.at < MAX_AGE));
        kept[key] = { at, values, base };
        put(kept);
    }

    function load(key, base = null, now = Date.now()) {
        const d = all()[key];
        if (!d || now - d.at >= MAX_AGE) return null;
        if (JSON.stringify(d.base) !== JSON.stringify(base)) return null;
        return d.values;
    }

    function drop(key) {
        const kept = all();
        delete kept[key];
        put(kept);
    }

    function dropAll() {
        try { backend.removeItem(KEY); } catch (e) {}
    }

    // Same-named inputs (tick boxes) repeat, so a field is known by its place too.
    function fields(form) {
        return [...form.elements]
            .filter(el => el.name && !el.dataset.draftSkip
                && !["file", "hidden", "submit", "button", "reset"].includes(el.type))
            .map((el, i) => [`${i}:${el.name}`, el]);
    }

    function read(form) {
        return Object.fromEntries(fields(form).map(([k, el]) =>
            [k, el.type === "checkbox" || el.type === "radio" ? el.checked : el.value]));
    }

    function attach(form) {
        const key = `${location.pathname}:${form.dataset.draft}`;
        const base = "draftGuard" in form.dataset ? read(form) : null;
        const kept = load(key, base);
        if (kept) {
            for (const [k, el] of fields(form)) {
                if (!(k in kept)) continue;
                if (typeof kept[k] === "boolean") el.checked = kept[k];
                else el.value = kept[k];
                // As if typed: the send button wakes on input. Not change, which
                // would add the closing line again to a body that dropped it.
                el.dispatchEvent(new Event("input", { bubbles: true }));
            }
            const opener = document.getElementById(form.dataset.draftOpener || "");
            if (opener && !opener.hidden) opener.click();
        }
        const keep = () => save(key, read(form), base);
        form.addEventListener("input", keep);
        form.addEventListener("change", keep);
        form.addEventListener("submit", () => drop(key));
        form.querySelectorAll(".btn-cancel").forEach(b => b.addEventListener("click", () => drop(key)));
    }

    use(root.localStorage);
    const api = { use, save, load, drop, dropAll };
    if (typeof module !== "undefined") module.exports = api;
    else {
        root.odasDrafts = api;
        // After the page scripts, so an opener button already has its handler.
        document.addEventListener("DOMContentLoaded", () =>
            document.querySelectorAll("form[data-draft]").forEach(attach));
    }
})(globalThis);
