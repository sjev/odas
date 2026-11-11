// Shared "Geavanceerd" toggle between the form editor and the raw index.md editor.
// Expects #toggle-advanced, #mode-input, .field-grid, #body-label, #raw-label, #raw-editor.

function initRawToggle(reopenRaw) {
    const btn = document.getElementById("toggle-advanced");
    const modeInput = document.getElementById("mode-input");
    const fieldGrid = document.querySelector(".field-grid");
    const bodyLabel = document.getElementById("body-label");
    const rawLabel = document.getElementById("raw-label");
    let rawCm = null;

    btn.addEventListener("change", () => {
        if (btn.checked) {
            fieldGrid.style.display = "none";
            bodyLabel.style.display = "none";
            rawLabel.style.display = "";
            modeInput.value = "raw";
            if (!rawCm) {
                rawCm = CodeMirror.fromTextArea(document.getElementById("raw-editor"), {
                    mode: "yaml",
                    lineWrapping: true,
                    viewportMargin: Infinity,
                    autofocus: true,
                });
                rawCm.setSize(null, "70vh");
            }
        } else {
            fieldGrid.style.display = "";
            bodyLabel.style.display = "";
            rawLabel.style.display = "none";
            modeInput.value = "form";
        }
    });

    if (reopenRaw) btn.click();
}
