// Read-only map. Every a.map-link carries its own points in data-latlon
// ("lat,lon;lat,lon;..."), so a page may show several. Expects #map-dialog with
// #map inside, and #map-close.

function initMapView() {
    const dialog = document.getElementById("map-dialog");
    const links = document.querySelectorAll("a.map-link");
    if (!dialog || !links.length) return;

    let map, markers;

    function points(link) {
        return (link.dataset.latlon || "")
            .split(";")
            .map((pair) => {
                const parts = pair.split(",");
                const lat = parseFloat(parts[0]);
                const lon = parseFloat(parts[1]);
                if (parts.length !== 2 || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
                return [lat, lon];
            })
            .filter((p) => p !== null);
    }

    links.forEach((link) => {
        const pts = points(link);
        if (!pts.length) {
            link.hidden = true;
            return;
        }
        link.addEventListener("click", (e) => {
            e.preventDefault();
            dialog.showModal();
            if (!map) {
                map = L.map("map");
                L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                    maxZoom: 19, attribution: "© OpenStreetMap",
                }).addTo(map);
                markers = L.layerGroup().addTo(map);
            }
            markers.clearLayers();
            pts.forEach((p) => markers.addLayer(L.marker(p)));
            map.invalidateSize();
            if (pts.length === 1) {
                map.setView(pts[0], 10);
            } else {
                map.fitBounds(L.latLngBounds(pts), { padding: [30, 30] });
            }
        });
    });

    document.getElementById("map-close").addEventListener("click", () => dialog.close());
}
