// The "pick a location" dialog, shared by the zaak and inzien editors.
// Every button.map-pick names its own input through data-target, so a type may
// declare more than one latlon field. Expects #map-dialog with #map, #map-hint,
// #map-confirm and #map-cancel.

function initMapPicker() {
    const NL_CENTER = [52.1, 5.3], NL_ZOOM = 7, PICK_ZOOM = 15;
    const dialog = document.getElementById("map-dialog");
    const buttons = document.querySelectorAll("button.map-pick");
    if (!dialog || !buttons.length) return;

    const mapHint = document.getElementById("map-hint");
    let map, marker, target;

    // Mirrors LatLonField.coords: decimal `lat,lon`, or degrees as Google Maps
    // copies them (51°27'27.9"N 5°38'54.1"E).
    const AXIS = String.raw`(\d+(?:\.\d+)?)°\s*(?:(\d+(?:\.\d+)?)'\s*)?(?:(\d+(?:\.\d+)?)"\s*)?`;
    const DMS = new RegExp(String.raw`^${AXIS}([NS])[\s,]*${AXIS}([EW])$`);

    function axis(d, m, s, hemi) {
        const v = parseFloat(d) + parseFloat(m || 0) / 60 + parseFloat(s || 0) / 3600;
        return "SW".includes(hemi) ? -v : v;
    }

    function parseLatLon(text) {
        const dms = (text || "").trim().match(DMS);
        if (dms) return [axis(...dms.slice(1, 5)), axis(...dms.slice(5, 9))];
        const parts = (text || "").split(",");
        if (parts.length !== 2) return null;
        const lat = parseFloat(parts[0]), lon = parseFloat(parts[1]);
        return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
    }

    function setMarker(latlng) {
        if (marker) {
            marker.setLatLng(latlng);
        } else {
            marker = L.marker(latlng, { draggable: true }).addTo(map);
        }
        mapHint.style.display = "none";
    }

    buttons.forEach((btn) => btn.addEventListener("click", () => {
        target = document.getElementById(btn.dataset.target);
        dialog.showModal();
        if (!map) {
            map = L.map("map").setView(NL_CENTER, NL_ZOOM);
            L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19, attribution: "© OpenStreetMap",
            }).addTo(map);
            map.on("click", (e) => setMarker(e.latlng));
        }
        map.invalidateSize();

        // Start from this field's own value, not whatever the last one held.
        if (marker) { marker.remove(); marker = null; }
        const existing = parseLatLon(target.value);
        if (existing) {
            map.setView(existing, PICK_ZOOM);
            setMarker(existing);
        } else {
            map.setView(NL_CENTER, NL_ZOOM);
            mapHint.style.display = "";
        }
    }));

    document.getElementById("map-confirm").addEventListener("click", () => {
        if (marker && target) {
            const p = marker.getLatLng();
            target.value = p.lat.toFixed(6) + "," + p.lng.toFixed(6);
        }
        dialog.close();
    });

    document.getElementById("map-cancel").addEventListener("click", () => dialog.close());
}
