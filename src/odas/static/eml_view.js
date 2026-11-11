// The `.eml` link opens the message in a window instead of saving it first.
// Expects #eml-dialog with #eml-onderwerp, #eml-source and #eml-download.
//
// Without this file the page still works: the link is an address of its own and
// the browser shows the same text on a page.

(function () {
    const dialog = document.getElementById("eml-dialog");
    const source = document.getElementById("eml-source");
    const download = document.getElementById("eml-download");
    const heading = document.getElementById("eml-onderwerp");
    if (!dialog || !source || !download) return;

    document.querySelectorAll(".eml-link").forEach(function (link) {
        link.addEventListener("click", function (event) {
            event.preventDefault();
            source.textContent = "Bezig met laden…";
            heading.textContent = link.dataset.onderwerp || "Bericht";
            download.href = link.dataset.eml || "";
            dialog.showModal();
            fetch(link.href)
                .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
                .then(function (text) {
                    source.textContent = text;
                })
                .catch(function () {
                    source.textContent = "Het bericht kan niet worden geladen.";
                });
        });
    });
})();
