'use strict';

document.addEventListener('DOMContentLoaded', () => {

    let currentGpxDuration = 0; // in seconds
    let isRunning = false;
    let hasStarted = false; // To track if we are in 'Resume' state

    // Map variables
    let map, routeLayer, markerLayer;
    let ws; // WebSocket instance

    // --- DOM Elements ---
    const deviceListBody = document.getElementById('device-list');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const refreshDevicesBtn = document.getElementById('refresh-devices-btn');
    const gpxUploadInput = document.getElementById('gpx-upload-input');
    const gpxUploadLabel = document.getElementById('gpx-upload-label');
    const uploadGpxBtn = document.getElementById('upload-gpx-btn');
    const gpxSelect = document.getElementById('gpx-select');
    const fileCountBadge = document.getElementById('file-count-badge');
    const deleteFileBtn = document.getElementById('delete-file-btn');
    const refreshFileListBtn = document.getElementById('refresh-file-list-btn');
    const routeMetadataDiv = document.getElementById('route-metadata');
    const metadataDistance = document.getElementById('metadata-distance');
    const metadataDuration = document.getElementById('metadata-duration');
    const metadataPoints = document.getElementById('metadata-points');
    const targetDurationInput = document.getElementById('target-duration-input');
    const speedMultiplierInput = document.getElementById('speed-multiplier-input');
    const loopCheckbox = document.getElementById('loop-checkbox');
    const toggleSimulationBtn = document.getElementById('toggle-simulation-btn');
    const resetSimulationBtn = document.getElementById('reset-simulation-btn');
    const simulationStatus = document.getElementById('simulation-status');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    // --- Map Initialization ---

    /**
     * Initializes the Leaflet map with TianDiTu layers.
     */
    function initMap() {
        // Default view (will be updated when GPX loads)
        map = L.map('map').setView([39.9042, 116.4074], 4); // Center on China

        const tk = window.TIANDITU_KEY; // Fallback for development

        // TianDiTu Vector Base Layer (vec_w)
        const vecLayer = L.tileLayer(`http://t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${tk}`, {
            subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
            attribution: '&copy; <a href="http://www.tianditu.gov.cn">Tianditu</a>'
        }).addTo(map);

        // TianDiTu Vector Annotation Layer (cva_w) - Labels
        const cvaLayer = L.tileLayer(`http://t{s}.tianditu.gov.cn/cva_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cva&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${tk}`, {
            subdomains: ['0', '1', '2', '3', '4', '5', '6', '7']
        }).addTo(map);
    }

    // --- WebSocket ---

    function initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/status`;
        
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            const status = JSON.parse(event.data);
            handleStatusUpdate(status);
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting in 2s...');
            setTimeout(initWebSocket, 2000);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            ws.close();
        };
    }

    // --- Devices ---

    /**
     * Fetches and displays the list of connected devices.
     */
    async function refreshDevices() {
        try {
            const res = await axios.get('/api/devices');
            deviceListBody.innerHTML = '';

            if (res.data.length === 0) {
                deviceListBody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No devices found. Click Scan.</td></tr>';
                return;
            }

            res.data.forEach(dev => {
                const tr = document.createElement('tr');
                const displayName = dev.name;
                const realNameInfo = dev.real_name && dev.real_name !== dev.name ?
                    `<div class="real-name"><i class="bi bi-phone"></i> ${dev.real_name}</div>` : '';

                // Device type icon and badge
                const deviceIcon = dev.device_type === 'iOS' ? 'bi-apple' : 'bi-android2';
                const deviceBadgeClass = dev.device_type === 'iOS' ? 'text-bg-dark' : 'text-bg-success';

                // Connection type formatting
                let connTypeDisplay = dev.connection_type.toUpperCase();
                let connBadgeClass = 'text-bg-secondary';
                if (dev.connection_type === 'wifi' || dev.connection_type === 'rsd') {
                    connBadgeClass = 'text-bg-info';
                    connTypeDisplay = 'RSD';
                } else if (dev.connection_type === 'usb') {
                    connBadgeClass = 'text-bg-primary';
                } else if (dev.connection_type === 'adb') {
                    connBadgeClass = 'text-bg-warning';
                }

                tr.innerHTML = `
                    <td><input type="checkbox" class="dev-check" value="${dev.udid}"></td>
                    <td>
                        <div class="d-flex align-items-center">
                            <span class="device-name"></span>
                            <i class="bi bi-pencil-square rename-btn" title="Rename"></i>
                        </div>
                        ${realNameInfo}
                        <div class="real-name text-muted small device-id">ID: ${dev.udid}</div>
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

                const nameSpan = tr.querySelector('.device-name');
                nameSpan.textContent = displayName;

                const renameBtn = tr.querySelector('.rename-btn');
                renameBtn.dataset.udid = dev.udid;
                renameBtn.dataset.name = displayName;
                renameBtn.addEventListener('click', () => {
                    renameDevice(renameBtn.dataset.udid, renameBtn.dataset.name);
                });

                // Add event listener to device checkbox
                const deviceCheckbox = tr.querySelector('.dev-check');
                deviceCheckbox.addEventListener('change', updateSelectAllCheckbox);

                deviceListBody.appendChild(tr);
            });
            
            // Update select-all checkbox state after loading devices
            updateSelectAllCheckbox();
        } catch (e) {
            console.error(e);
        }
    }

    /**
     * Prompts the user to rename a device and sends the request to the server.
     * @param {string} udid - The UDID of the device to rename.
     * @param {string} currentName - The current name of the device.
     */
    async function renameDevice(udid, currentName) {
        const newName = prompt('Enter new name for device:', currentName);
        if (newName && newName.trim() !== '') {
            try {
                await axios.post('/api/devices/rename', {
                    udid: udid,
                    name: newName
                });
                refreshDevices();
            } catch (e) {
                alert('Failed to rename: ' + (e.response?.data?.error || e.message));
            }
        }
    }

    /**
     * Toggles the checked state of all device checkboxes.
     */
    function toggleSelectAll() {
        document.querySelectorAll('.dev-check').forEach(c => c.checked = selectAllCheckbox.checked);
    }

    /**
     * Updates the select-all checkbox state based on individual device checkboxes.
     */
    function updateSelectAllCheckbox() {
        const allCheckboxes = document.querySelectorAll('.dev-check');
        const checkedCheckboxes = document.querySelectorAll('.dev-check:checked');
        
        if (allCheckboxes.length === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (checkedCheckboxes.length === allCheckboxes.length) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else if (checkedCheckboxes.length > 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        }
    }

    // --- Files & Metadata ---

    /**
     * Uploads the selected GPX file to the server.
     */
    async function uploadGpx() {
        if (!gpxUploadInput.files[0]) return;
        const formData = new FormData();
        formData.append('file', gpxUploadInput.files[0]);
        try {
            await axios.post('/api/upload', formData);
            loadFileList();
            gpxUploadInput.value = '';
            updateFileInputLabel(); // Reset label
        } catch (e) {
            alert('Upload failed');
        }
    }

    /**
     * Updates the file input display text to show the selected filename.
     */
    function updateFileInputLabel() {
        if (gpxUploadInput.files.length > 0) {
            gpxUploadLabel.textContent = gpxUploadInput.files[0].name;
        } else {
            gpxUploadLabel.textContent = 'No file chosen';
        }
    }

    /**
     * Fetches the list of available GPX files and populates the select dropdown.
     */
    async function loadFileList() {
        try {
            const res = await axios.get('/api/gpx_files');
            const current = gpxSelect.value;
            gpxSelect.innerHTML = '<option value="">-- Select a file --</option>';

            // Update file count badge
            fileCountBadge.textContent = res.data.length;

            // Load each file with metadata
            for (const f of res.data) {
                try {
                    const detailRes = await axios.get(`/api/gpx_files/${f}/details`);
                    const data = detailRes.data;
                    const opt = document.createElement('option');
                    opt.value = f;

                    // Format metadata
                    const distKm = (data.total_distance / 1000).toFixed(2);
                    const durMin = (data.total_duration / 60).toFixed(0);
                    const pts = data.point_count;

                    opt.text = `${f} (${distKm}km · ${durMin}min · ${pts}pts)`;
                    gpxSelect.appendChild(opt);
                } catch (e) {
                    // Fallback if metadata fails
                    const opt = document.createElement('option');
                    opt.value = f;
                    opt.text = f;
                    gpxSelect.appendChild(opt);
                }
            }
            gpxSelect.value = current;

            // Enable/disable delete button
            deleteFileBtn.disabled = !gpxSelect.value;
        } catch (error) {
            console.error('Failed to load file list:', error);
        }
    }

    /**
     * Deletes the currently selected GPX file.
     */
    async function deleteSelectedFile() {
        const filename = gpxSelect.value;
        if (!filename) return;

        if (!confirm(`Delete "${filename}"?`)) return;

        try {
            await axios.delete(`/api/gpx_files/${filename}`);
            await loadFileList();
            // Clear metadata and map if deleted file was selected
            routeMetadataDiv.classList.add('d-none');
            if (routeLayer) map.removeLayer(routeLayer);
            if (markerLayer) map.removeLayer(markerLayer);
        } catch (e) {
            alert('Delete failed: ' + (e.response?.data?.error || e.message));
        }
    }
    
    /**
     * Handles the selection of a GPX file, fetching its details and displaying them.
     */
    async function onGpxSelected() {
        const filename = gpxSelect.value;

        // Enable/disable delete button
        deleteFileBtn.disabled = !filename;

        // Clear map layers
        if (routeLayer) map.removeLayer(routeLayer);
        if (markerLayer) map.removeLayer(markerLayer);
        routeLayer = null;
        markerLayer = null;

        if (!filename) {
            routeMetadataDiv.classList.add('d-none');
            currentGpxDuration = 0;
            return;
        }

        try {
            const res = await axios.get(`/api/gpx_files/${filename}/details`);
            const data = res.data;

            routeMetadataDiv.classList.remove('d-none');
            metadataDistance.innerText = (data.total_distance / 1000).toFixed(2) + ' km';
            metadataPoints.innerText = data.point_count;

            currentGpxDuration = data.total_duration;
            const durMin = (currentGpxDuration / 60).toFixed(1);
            metadataDuration.innerText = formatDuration(currentGpxDuration);

            // Draw Route on Map
            if (data.points && data.points.length > 0) {
                const latlngs = data.points.map(p => [p.lat, p.lon]);
                routeLayer = L.polyline(latlngs, {
                    color: 'red'
                }).addTo(map);
                map.fitBounds(routeLayer.getBounds(), {
                    padding: [50, 50]
                });
            }

            // Set defaults
            speedMultiplierInput.value = 1.0;
            if (currentGpxDuration > 0) {
                targetDurationInput.value = durMin;
                speedMultiplierInput.disabled = false;
            } else {
                // No timestamp case
                metadataDuration.innerText = 'N/A';
                targetDurationInput.value = 30; // Default 30 mins
                speedMultiplierInput.value = 'N/A';
                speedMultiplierInput.disabled = true;
            }

        } catch (e) {
            console.error(e);
        }
    }
    
    /**
     * Formats a duration from seconds to a human-readable string (e.g., "1h 23m").
     * @param {number} seconds - The duration in seconds.
     * @returns {string} The formatted duration string.
     */
    function formatDuration(seconds) {
        if (!seconds) return '0s';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m ${s}s`;
    }

    // --- Speed/Duration Sync ---
    
    /**
     * Calculates and sets the speed multiplier based on the target duration.
     */
    function onTargetDurationChange() {
        if (currentGpxDuration <= 0) return; // No base time to calc from
        const targetMin = parseFloat(targetDurationInput.value);
        if (targetMin > 0) {
            const speed = (currentGpxDuration / 60) / targetMin;
            speedMultiplierInput.value = speed.toFixed(2);
        }
    }
    
    /**
     * Calculates and sets the target duration based on the speed multiplier.
     */
    function onSpeedMultChange() {
        if (currentGpxDuration <= 0) return;
        const speed = parseFloat(speedMultiplierInput.value);
        if (speed > 0) {
            const targetMin = (currentGpxDuration / 60) / speed;
            targetDurationInput.value = targetMin.toFixed(1);
        }
    }

    // --- Control ---
    
    /**
     * Toggles the simulation state between start/resume and pause.
     */
    async function toggleSim() {
        if (isRunning) {
            // If running, action is PAUSE
            await stopSim();
        } else {
            // If stopped, action is START or RESUME
            await startSim();
        }
    }
    
    /**
     * Starts or resumes the location simulation.
     */
    async function startSim() {
        const filename = gpxSelect.value;
        const udids = Array.from(document.querySelectorAll('.dev-check:checked')).map(c => c.value);
        const loop = loopCheckbox.checked;

        let payload = {
            filename,
            udids,
            loop
        };

        if (currentGpxDuration > 0) {
            payload.speed = speedMultiplierInput.value;
        } else {
            const targetMin = parseFloat(targetDurationInput.value);
            if (!targetMin || targetMin <= 0) return alert('Please enter a valid target duration.');
            payload.target_duration = targetMin * 60;
        }

        if (!filename) return alert('Select a GPX file');
        if (udids.length === 0) return alert('Select at least one device');

        try {
            await axios.post('/api/start', payload);
            // State update handled by WebSocket/polling
        } catch (e) {
            alert('Failed to start: ' + (e.response?.data?.error || e.message));
        }
    }
    
    /**
     * Stops (pauses) the location simulation.
     */
    async function stopSim() {
        try {
            await axios.post('/api/stop');
        } catch (e) {
            console.error(e);
        }
    }
    
    /**
     * Resets the simulation to the beginning.
     */
    async function resetSim() {
        try {
            await axios.post('/api/reset');
            hasStarted = false; // Reset local state
            if (markerLayer) {
                map.removeLayer(markerLayer);
                markerLayer = null;
            }
        } catch (e) {
            console.error(e);
        }
    }
    
    /**
     * Updates the UI elements based on the simulation state.
     */
    function handleStatusUpdate(s) {
        const total = s.total_points || 0;
        const current = s.current_index || 0;
        const running = s.running;

        isRunning = running;
        if (current > 0) hasStarted = true;
        if (current === 0 && !running) hasStarted = false;

        // Button States
        if (running) {
            toggleSimulationBtn.innerText = 'Pause';
            toggleSimulationBtn.className = 'btn btn-warning flex-grow-1';
            resetSimulationBtn.disabled = false;
            simulationStatus.innerText = 'Running';
            simulationStatus.className = 'status-running';
        } else {
            resetSimulationBtn.disabled = !hasStarted;
            if (hasStarted && current < total) {
                toggleSimulationBtn.innerText = 'Resume';
                simulationStatus.innerText = 'Paused';
            } else {
                toggleSimulationBtn.innerText = 'Start';
                simulationStatus.innerText = 'Idle';
            }
            toggleSimulationBtn.className = 'btn btn-success flex-grow-1';
            simulationStatus.className = 'status-stopped';
        }

        // Progress Bar
        const pct = total > 0 ? (current / total) * 100 : 0;
        progressBar.style.width = pct + '%';
        progressText.innerText = `${current} / ${total} points`;

        // Update Map Marker
        if (s.current_lat && s.current_lon) {
            if (!markerLayer) {
                markerLayer = L.marker([s.current_lat, s.current_lon]).addTo(map);
            } else {
                markerLayer.setLatLng([s.current_lat, s.current_lon]);
            }
        }
    }

    // --- Event Listeners ---
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

    // --- Initial Load ---
    function initialize() {
        refreshDevices();
        loadFileList();
        initMap();
        initWebSocket(); // Connect WebSocket
    }
    
    initialize();
});
