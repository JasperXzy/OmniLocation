'use strict';

document.addEventListener('DOMContentLoaded', () => {

    let currentGpxDuration = 0; // seconds
    let isRunning = false;
    let hasStarted = false;

    // Map / WS
    let map;
    let routeLayer;        // full planned route (red)
    let traveledLayer;     // walked-so-far overlay (green)
    let traveledLatLngs = [];
    let markerLayer;
    let currentRoutePoints = [];
    let ws;

    // --- DOM ---
    const $ = (id) => document.getElementById(id);
    const deviceListBody = $('device-list');
    const selectAllCheckbox = $('select-all-checkbox');
    const refreshDevicesBtn = $('refresh-devices-btn');
    const refreshDevicesSpinner = $('refresh-devices-spinner');
    const gpxUploadInput = $('gpx-upload-input');
    const gpxUploadLabel = $('gpx-upload-label');
    const uploadGpxBtn = $('upload-gpx-btn');
    const uploadGpxSpinner = $('upload-gpx-spinner');
    const gpxSelect = $('gpx-select');
    const fileCountBadge = $('file-count-badge');
    const deleteFileBtn = $('delete-file-btn');
    const refreshFileListBtn = $('refresh-file-list-btn');
    const routeMetadataDiv = $('route-metadata');
    const metadataDistance = $('metadata-distance');
    const metadataDuration = $('metadata-duration');
    const metadataPoints = $('metadata-points');
    const targetDurationInput = $('target-duration-input');
    const speedMultiplierInput = $('speed-multiplier-input');
    const loopCheckbox = $('loop-checkbox');
    const toggleSimulationBtn = $('toggle-simulation-btn');
    const resetSimulationBtn = $('reset-simulation-btn');
    const simulationStatus = $('simulation-status');
    const progressBar = $('progress-bar');
    const progressText = $('progress-text');
    const toastContainer = $('toast-container');

    // Bootstrap modal instances
    const renameModalEl = $('rename-modal');
    const renameModal = new bootstrap.Modal(renameModalEl);
    const renameModalInput = $('rename-modal-input');
    const renameModalUdid = $('rename-modal-udid');
    const renameModalConfirm = $('rename-modal-confirm');

    const confirmModalEl = $('confirm-modal');
    const confirmModal = new bootstrap.Modal(confirmModalEl);
    const confirmModalBody = $('confirm-modal-body');
    const confirmModalConfirm = $('confirm-modal-confirm');
    let confirmCallback = null;

    // --- HTTP helper (replaces axios) ---

    async function request(method, url, body, isForm) {
        const opts = { method, headers: {} };
        if (body !== undefined) {
            if (isForm) {
                opts.body = body;
            } else {
                opts.headers['Content-Type'] = 'application/json';
                opts.body = JSON.stringify(body);
            }
        }
        const res = await fetch(url, opts);
        let data = null;
        const text = await res.text();
        if (text) {
            try { data = JSON.parse(text); } catch (e) { data = text; }
        }
        if (!res.ok) {
            const msg = (data && data.message) || (data && data.error) || res.statusText;
            const err = new Error(msg);
            err.status = res.status;
            err.data = data;
            throw err;
        }
        return data;
    }
    const api = {
        get: (url) => request('GET', url),
        post: (url, body) => request('POST', url, body),
        del: (url) => request('DELETE', url),
        upload: (url, formData) => request('POST', url, formData, true),
    };

    // --- Toast / Modal helpers ---

    function showToast(message, variant) {
        variant = variant || 'primary';
        const toastEl = document.createElement('div');
        toastEl.className = `toast align-items-center text-bg-${variant} border-0`;
        toastEl.setAttribute('role', 'alert');
        toastEl.setAttribute('aria-live', 'assertive');
        toastEl.setAttribute('aria-atomic', 'true');
        toastEl.innerHTML = `
            <div class="d-flex">
                <div class="toast-body"></div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>`;
        toastEl.querySelector('.toast-body').textContent = message;
        toastContainer.appendChild(toastEl);
        const t = new bootstrap.Toast(toastEl, { delay: 3500 });
        t.show();
        toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
    }

    function notifyError(prefix, e) {
        const msg = (e && (e.message || e.toString())) || 'Unknown error';
        showToast(`${prefix}: ${msg}`, 'danger');
        console.error(prefix, e);
    }

    function openConfirm(message, onConfirm) {
        confirmModalBody.textContent = message;
        confirmCallback = onConfirm;
        confirmModal.show();
    }

    confirmModalConfirm.addEventListener('click', () => {
        confirmModal.hide();
        if (typeof confirmCallback === 'function') {
            const cb = confirmCallback;
            confirmCallback = null;
            cb();
        }
    });

    function openRename(udid, currentName) {
        renameModalUdid.value = udid;
        renameModalInput.value = currentName || '';
        renameModal.show();
        setTimeout(() => renameModalInput.focus(), 200);
    }

    renameModalConfirm.addEventListener('click', async () => {
        const newName = renameModalInput.value.trim();
        const udid = renameModalUdid.value;
        if (!newName) { showToast('Name cannot be empty', 'warning'); return; }
        try {
            await api.post('/api/devices/rename', { udid, name: newName });
            renameModal.hide();
            showToast('Device renamed', 'success');
            refreshDevices();
        } catch (e) {
            notifyError('Rename failed', e);
        }
    });
    renameModalInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); renameModalConfirm.click(); }
    });

    // --- Map ---

    function initMap() {
        map = L.map('map').setView([39.9042, 116.4074], 4);

        const tk = window.TIANDITU_KEY;
        // Protocol-relative URLs avoid mixed-content when page is HTTPS.
        const vecUrl = `//t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${tk}`;
        const cvaUrl = `//t{s}.tianditu.gov.cn/cva_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cva&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${tk}`;

        L.tileLayer(vecUrl, {
            subdomains: ['0','1','2','3','4','5','6','7'],
            attribution: '&copy; <a href="https://www.tianditu.gov.cn">Tianditu</a>'
        }).addTo(map);
        L.tileLayer(cvaUrl, {
            subdomains: ['0','1','2','3','4','5','6','7']
        }).addTo(map);
    }

    function clearMapLayers() {
        if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
        if (traveledLayer) { map.removeLayer(traveledLayer); traveledLayer = null; }
        if (markerLayer) { map.removeLayer(markerLayer); markerLayer = null; }
        traveledLatLngs = [];
        currentRoutePoints = [];
    }

    // --- WebSocket ---

    function initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${window.location.host}/ws/status`);
        ws.onopen = () => console.log('WebSocket connected');
        ws.onmessage = (event) => {
            try { handleStatusUpdate(JSON.parse(event.data)); }
            catch (e) { console.error('Bad WS payload', e); }
        };
        ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting in 2s...');
            setTimeout(initWebSocket, 2000);
        };
        ws.onerror = (error) => { console.error('WebSocket error:', error); ws.close(); };
    }

    // --- Devices ---

    async function refreshDevices() {
        refreshDevicesBtn.disabled = true;
        refreshDevicesSpinner.classList.remove('d-none');
        try {
            const data = await api.get('/api/devices');
            deviceListBody.innerHTML = '';

            if (!data.length) {
                deviceListBody.innerHTML =
                    '<tr><td colspan="4" class="text-center text-muted">No devices found. Click Scan.</td></tr>';
                return;
            }

            for (const dev of data) {
                const tr = document.createElement('tr');
                const realNameInfo = dev.real_name && dev.real_name !== dev.name
                    ? `<div class="real-name"><i class="bi bi-phone"></i> </div>` : '';

                const deviceIcon = 'bi-apple';
                const deviceBadgeClass = 'text-bg-dark';

                let connTypeDisplay = (dev.connection_type || '').toUpperCase();
                let connBadgeClass = 'text-bg-secondary';
                if (dev.connection_type === 'wifi' || dev.connection_type === 'rsd') {
                    connBadgeClass = 'text-bg-info'; connTypeDisplay = 'RSD';
                } else if (dev.connection_type === 'usb') {
                    connBadgeClass = 'text-bg-primary';
                }

                tr.innerHTML = `
                    <td><input type="checkbox" class="dev-check" aria-label="Select device"></td>
                    <td>
                        <div class="d-flex align-items-center">
                            <span class="device-name"></span>
                            <button type="button" class="rename-btn" title="Rename" aria-label="Rename device">
                                <i class="bi bi-pencil-square"></i>
                            </button>
                        </div>
                        ${realNameInfo}
                        <div class="real-name text-muted small device-id">ID: <span class="dev-id"></span></div>
                        <div class="device-badges">
                            <span class="badge ${deviceBadgeClass} me-1">
                                <i class="bi ${deviceIcon}"></i> ${dev.device_type}
                            </span>
                            <span class="badge ${connBadgeClass}">${connTypeDisplay}</span>
                        </div>
                    </td>
                    <td class="device-type-col">
                        <span class="badge ${deviceBadgeClass}">
                            <i class="bi ${deviceIcon}"></i> ${dev.device_type}
                        </span>
                    </td>
                    <td class="connection-col">
                        <span class="badge ${connBadgeClass}">${connTypeDisplay}</span>
                    </td>
                `;

                tr.querySelector('.device-name').textContent = dev.name;
                tr.querySelector('.dev-id').textContent = dev.udid;
                if (realNameInfo) {
                    tr.querySelector('.real-name i').insertAdjacentText('afterend', ' ' + dev.real_name);
                }

                const cb = tr.querySelector('.dev-check');
                cb.value = dev.udid;
                cb.addEventListener('change', updateSelectAllCheckbox);

                tr.querySelector('.rename-btn').addEventListener('click', () => openRename(dev.udid, dev.name));

                deviceListBody.appendChild(tr);
            }

            updateSelectAllCheckbox();
        } catch (e) {
            notifyError('Failed to load devices', e);
        } finally {
            refreshDevicesBtn.disabled = false;
            refreshDevicesSpinner.classList.add('d-none');
        }
    }

    function toggleSelectAll() {
        document.querySelectorAll('.dev-check').forEach(c => c.checked = selectAllCheckbox.checked);
    }

    function updateSelectAllCheckbox() {
        const all = document.querySelectorAll('.dev-check');
        const checked = document.querySelectorAll('.dev-check:checked');
        if (!all.length) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (checked.length === all.length) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else if (checked.length > 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        }
    }

    // --- Files ---

    async function uploadGpx() {
        if (!gpxUploadInput.files[0]) return;
        const formData = new FormData();
        formData.append('file', gpxUploadInput.files[0]);
        uploadGpxBtn.disabled = true;
        uploadGpxSpinner.classList.remove('d-none');
        try {
            await api.upload('/api/upload', formData);
            showToast('Upload successful', 'success');
            gpxUploadInput.value = '';
            updateFileInputLabel();
            await loadFileList();
        } catch (e) {
            notifyError('Upload failed', e);
        } finally {
            uploadGpxBtn.disabled = false;
            uploadGpxSpinner.classList.add('d-none');
        }
    }

    function updateFileInputLabel() {
        gpxUploadLabel.textContent = gpxUploadInput.files.length > 0
            ? gpxUploadInput.files[0].name
            : 'No file chosen';
    }

    async function loadFileList() {
        try {
            const data = await api.get('/api/gpx_files');
            const current = gpxSelect.value;
            gpxSelect.innerHTML = '<option value="">-- Select a file --</option>';
            fileCountBadge.textContent = data.length;

            for (const entry of data) {
                const opt = document.createElement('option');
                opt.value = entry.filename;
                if (entry.error || entry.point_count === undefined) {
                    opt.textContent = entry.filename;
                } else {
                    const distKm = (entry.total_distance / 1000).toFixed(2);
                    const durMin = (entry.total_duration / 60).toFixed(0);
                    opt.textContent = `${entry.filename} (${distKm}km · ${durMin}min · ${entry.point_count}pts)`;
                }
                gpxSelect.appendChild(opt);
            }
            gpxSelect.value = current;
            deleteFileBtn.disabled = !gpxSelect.value;
        } catch (e) {
            notifyError('Failed to load file list', e);
        }
    }

    function deleteSelectedFile() {
        const filename = gpxSelect.value;
        if (!filename) return;
        openConfirm(`Delete "${filename}"?`, async () => {
            try {
                await api.del(`/api/gpx_files/${encodeURIComponent(filename)}`);
                await loadFileList();
                routeMetadataDiv.classList.add('d-none');
                clearMapLayers();
                showToast('File deleted', 'success');
            } catch (e) {
                notifyError('Delete failed', e);
            }
        });
    }

    async function onGpxSelected() {
        const filename = gpxSelect.value;
        deleteFileBtn.disabled = !filename;
        clearMapLayers();

        if (!filename) {
            routeMetadataDiv.classList.add('d-none');
            currentGpxDuration = 0;
            return;
        }

        try {
            const data = await api.get(`/api/gpx_files/${encodeURIComponent(filename)}/details`);
            routeMetadataDiv.classList.remove('d-none');
            metadataDistance.textContent = (data.total_distance / 1000).toFixed(2) + ' km';
            metadataPoints.textContent = data.point_count;

            currentGpxDuration = data.total_duration;
            const durMin = (currentGpxDuration / 60).toFixed(1);
            metadataDuration.textContent = formatDuration(currentGpxDuration);

            currentRoutePoints = data.points || [];
            if (currentRoutePoints.length) {
                const latlngs = currentRoutePoints.map(p => [p.lat, p.lon]);
                routeLayer = L.polyline(latlngs, { color: 'red' }).addTo(map);
                map.fitBounds(routeLayer.getBounds(), { padding: [50, 50] });
            }

            speedMultiplierInput.value = 1.0;
            if (currentGpxDuration > 0) {
                targetDurationInput.value = durMin;
                speedMultiplierInput.disabled = false;
            } else {
                metadataDuration.textContent = 'N/A';
                targetDurationInput.value = 30;
                speedMultiplierInput.value = '';
                speedMultiplierInput.disabled = true;
            }
        } catch (e) {
            notifyError('Failed to load GPX details', e);
        }
    }

    function formatDuration(seconds) {
        if (!seconds) return '0s';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m ${s}s`;
    }

    // --- Speed/Duration sync ---

    function onTargetDurationChange() {
        if (currentGpxDuration <= 0) return;
        const targetMin = parseFloat(targetDurationInput.value);
        if (targetMin > 0) {
            speedMultiplierInput.value = ((currentGpxDuration / 60) / targetMin).toFixed(2);
        }
    }

    function onSpeedMultChange() {
        if (currentGpxDuration <= 0) return;
        const speed = parseFloat(speedMultiplierInput.value);
        if (speed > 0) {
            targetDurationInput.value = ((currentGpxDuration / 60) / speed).toFixed(1);
        }
    }

    // --- Control ---

    async function toggleSim() {
        if (isRunning) await stopSim();
        else await startSim();
    }

    async function startSim() {
        const filename = gpxSelect.value;
        const udids = Array.from(document.querySelectorAll('.dev-check:checked')).map(c => c.value);
        const loop = loopCheckbox.checked;

        if (!filename) { showToast('Select a GPX file', 'warning'); return; }
        if (!udids.length) { showToast('Select at least one device', 'warning'); return; }

        const payload = { filename, udids, loop };
        if (currentGpxDuration > 0) {
            payload.speed = parseFloat(speedMultiplierInput.value) || 1.0;
        } else {
            const targetMin = parseFloat(targetDurationInput.value);
            if (!targetMin || targetMin <= 0) {
                showToast('Please enter a valid target duration', 'warning');
                return;
            }
            payload.target_duration = targetMin * 60;
        }

        try {
            await api.post('/api/start', payload);
            traveledLatLngs = [];
            if (traveledLayer) { map.removeLayer(traveledLayer); traveledLayer = null; }
        } catch (e) {
            notifyError('Failed to start', e);
        }
    }

    async function stopSim() {
        try { await api.post('/api/stop'); }
        catch (e) { notifyError('Failed to stop', e); }
    }

    async function resetSim() {
        try {
            await api.post('/api/reset');
            hasStarted = false;
            traveledLatLngs = [];
            if (markerLayer) { map.removeLayer(markerLayer); markerLayer = null; }
            if (traveledLayer) { map.removeLayer(traveledLayer); traveledLayer = null; }
        } catch (e) {
            notifyError('Failed to reset', e);
        }
    }

    function handleStatusUpdate(s) {
        const total = s.total_points || 0;
        const current = s.current_index || 0;
        const running = s.running;

        isRunning = running;
        if (current > 0) hasStarted = true;
        if (current === 0 && !running) hasStarted = false;

        if (running) {
            toggleSimulationBtn.textContent = 'Pause';
            toggleSimulationBtn.className = 'btn btn-warning flex-grow-1';
            resetSimulationBtn.disabled = false;
            simulationStatus.textContent = 'Running';
            simulationStatus.className = 'status-running';
        } else {
            resetSimulationBtn.disabled = !hasStarted;
            if (hasStarted && current < total) {
                toggleSimulationBtn.textContent = 'Resume';
                simulationStatus.textContent = 'Paused';
            } else {
                toggleSimulationBtn.textContent = 'Start';
                simulationStatus.textContent = 'Idle';
            }
            toggleSimulationBtn.className = 'btn btn-success flex-grow-1';
            simulationStatus.className = 'status-stopped';
        }

        const pct = total > 0 ? (current / total) * 100 : 0;
        progressBar.style.width = pct + '%';
        progressText.textContent = `${current} / ${total} points`;

        if (s.current_lat && s.current_lon) {
            const latlng = [s.current_lat, s.current_lon];
            if (!markerLayer) {
                markerLayer = L.marker(latlng).addTo(map);
            } else {
                markerLayer.setLatLng(latlng);
            }
            // Append to traveled trail (skip duplicates).
            const last = traveledLatLngs[traveledLatLngs.length - 1];
            if (!last || last[0] !== latlng[0] || last[1] !== latlng[1]) {
                traveledLatLngs.push(latlng);
                if (!traveledLayer) {
                    traveledLayer = L.polyline(traveledLatLngs, {
                        className: 'leaflet-traveled-path',
                        color: '#22c55e',
                        weight: 4,
                        opacity: 0.85,
                    }).addTo(map);
                } else {
                    traveledLayer.setLatLngs(traveledLatLngs);
                }
            }
        }
    }

    // --- Listeners ---
    refreshDevicesBtn.addEventListener('click', refreshDevices);
    selectAllCheckbox.addEventListener('click', toggleSelectAll);
    gpxUploadInput.addEventListener('change', updateFileInputLabel);
    uploadGpxBtn.addEventListener('click', uploadGpx);
    gpxSelect.addEventListener('change', onGpxSelected);
    refreshFileListBtn.addEventListener('click', loadFileList);
    deleteFileBtn.addEventListener('click', deleteSelectedFile);
    targetDurationInput.addEventListener('input', onTargetDurationChange);
    speedMultiplierInput.addEventListener('input', onSpeedMultChange);
    toggleSimulationBtn.addEventListener('click', toggleSim);
    resetSimulationBtn.addEventListener('click', resetSim);

    // --- Init ---
    function initialize() {
        refreshDevices();
        loadFileList();
        initMap();
        initWebSocket();
    }

    initialize();
});
