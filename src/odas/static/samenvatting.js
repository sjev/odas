// A document being read answers by itself, so nobody sits on a blank page.
// Every row carries its own address in data-samenvatting; a row that says it is
// busy is polled until the summary lands or the attempt fails.
//
// Without this file the page still works: the button is a form, and a reload
// shows whatever the row has become.

(function () {
    const EVERY = 3000;

    function fold(text) {
        const details = document.createElement("details");
        details.className = "doc-summary";
        const label = document.createElement("summary");
        label.textContent = "Samenvatting";
        const prose = document.createElement("div");
        prose.className = "prose";
        prose.textContent = text;
        details.append(label, prose);
        return details;
    }

    function settle(row, state) {
        const busy = row.querySelector(".doc-busy");
        if (busy) busy.remove();
        if (state.status === "klaar") {
            const slot = row.querySelector(".doc-summary-slot");
            if (slot) slot.replaceChildren(fold(state.samenvatting));
        } else {
            // A failure needs the button back beside it, and the row is rebuilt
            // server-side rather than here: one place decides what a row looks like.
            window.location.reload();
        }
    }

    function watch(row) {
        const url = row.dataset.samenvatting;
        const timer = setInterval(function () {
            fetch(url, { headers: { Accept: "application/json" } })
                .then((r) => (r.ok ? r.json() : null))
                .then(function (state) {
                    if (!state || state.status === "bezig") return;
                    clearInterval(timer);
                    settle(row, state);
                })
                .catch(function () {
                    clearInterval(timer);
                });
        }, EVERY);
    }

    document.querySelectorAll(".doc-row .doc-busy").forEach(function (busy) {
        const row = busy.closest(".doc-row");
        if (row && row.dataset.samenvatting) watch(row);
    });
})();
