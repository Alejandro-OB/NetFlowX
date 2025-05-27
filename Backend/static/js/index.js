// --- Global Constants for API URLs ---
const API_BASE_URL = 'http://192.168.18.151:5000';
const MININET_AGENT_URL = 'http://192.168.18.157:5002'; // For Mininet agent calls

// --- Centralized Message Modal Functions ---
// This function replaces alert/confirm and is used by all JS modules
function showMessageModal(title, message, isConfirm = false, onConfirm = null) {
  const modal = document.getElementById('message-modal');
  document.getElementById('message-modal-title').textContent = title;
  document.getElementById('message-modal-content').textContent = message;
  const confirmBtn = document.getElementById('message-modal-confirm-btn');
  const cancelBtn = document.getElementById('message-modal-cancel-btn');

  // Clear previous listeners to prevent multiple executions
  confirmBtn.onclick = null;
  cancelBtn.onclick = null;

  confirmBtn.onclick = () => {
    modal.classList.add('hidden');
    if (isConfirm && onConfirm) {
      onConfirm();
    }
  };

  if (isConfirm) {
    cancelBtn.classList.remove('hidden');
    cancelBtn.onclick = () => {
      modal.classList.add('hidden');
    };
  } else {
    cancelBtn.classList.add('hidden');
  }

  modal.classList.remove('hidden');
}


// --- Topology Functions ---
let map;
let markers = {}; // {dpid: marker_obj}
let polylines = []; // Array of polyline objects

async function loadTopology() {
    try {
        const response = await fetch(`${API_BASE_URL}/topology/get`);

        // Check if the HTTP response was successful
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${response.status} - ${errorData.message || response.statusText}`);
        }

        const data = await response.json();
        console.log("Data received from backend:", data); // Debugging log

        if (map) {
            map.remove(); // Remove existing map instance
        }
        // Set the initial map view to the desired coordinates
        map = L.map('mapa-topologia').setView([54.5, 15.3], 4); // Coordinates and zoom from your original code

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);

        // Clear existing markers and polylines
        Object.values(markers).forEach(marker => marker.remove());
        polylines.forEach(polyline => polyline.remove());
        markers = {};
        polylines = [];

        let allLatLngs = []; // To adjust map bounds

        // Add switches
        if (data.switches && Array.isArray(data.switches)) {
            data.switches.forEach(sw => {
                // Ensure latitude and longitude exist and are numbers
                if (typeof sw.latitud === 'number' && typeof sw.longitud === 'number') {
                    const marker = L.marker([sw.latitud, sw.longitud]).addTo(map)
                        .bindPopup(`<b>${sw.nombre}</b><br>DPID: ${sw.dpid}<br>Estado: ${sw.status || 'Desconocido'}`);
                    markers[sw.dpid] = marker;
                    allLatLngs.push([sw.latitud, sw.longitud]); // Add to the list to adjust bounds
                } else {
                    console.warn(`Invalid coordinates for switch ${sw.nombre}: latitud=${sw.latitud}, longitud=${sw.longitud}`);
                }
            });
        } else {
            console.warn('data.switches is not an array or is undefined:', data.switches);
        }


        // Add hosts (optional, if you want to visualize them)
        if (data.hosts && Array.isArray(data.hosts)) {
            data.hosts.forEach(host => {
                const connectedSwitch = data.switches.find(sw => sw.id_switch === host.id_switch_conectado);
                if (connectedSwitch && typeof connectedSwitch.latitud === 'number' && typeof connectedSwitch.longitud === 'number') {
                    // Slight displacement from the switch for visibility
                    const lat = connectedSwitch.latitud + (Math.random() - 0.5) * 0.01;
                    const lon = connectedSwitch.longitud + (Math.random() - 0.5) * 0.01;
                    L.marker([lat, lon], {
                        icon: L.divIcon({
                            className: 'custom-host-icon',
                            html: `<div style="background-color: #4CAF50; color: white; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold;">H</div>`,
                            iconSize: [24, 24],
                            iconAnchor: [12, 12]
                        })
                    }).addTo(map)
                    .bindPopup(`<b>${host.nombre}</b><br>MAC: ${host.mac}<br>IP: ${host.ip}<br>Connected to: ${connectedSwitch.nombre}`);
                    allLatLngs.push([lat, lon]); // Add to the list to adjust bounds
                } else {
                    console.warn(`Invalid connected switch coordinates for host ${host.nombre}:`, connectedSwitch);
                }
            });
        } else {
            console.warn('data.hosts is not an array or is undefined:', data.hosts);
        }


        // Add links
        if (data.enlaces && Array.isArray(data.enlaces)) {
            data.enlaces.forEach(link => {
                const sourceSwitch = data.switches.find(sw => sw.id_switch === link.id_origen);
                const destSwitch = data.switches.find(sw => sw.id_switch === link.id_destino);
                if (sourceSwitch && destSwitch &&
                    typeof sourceSwitch.latitud === 'number' && typeof sourceSwitch.longitud === 'number' &&
                    typeof destSwitch.latitud === 'number' && typeof destSwitch.longitud === 'number') {

                    // Use the colorByBandwidth function for link color
                    const linkColor = colorPorAnchoBanda(link.ancho_banda);

                    const polyline = L.polyline([
                        [sourceSwitch.latitud, sourceSwitch.longitud],
                        [destSwitch.latitud, destSwitch.longitud]
                    ], {
                        color: linkColor, // Apply color based on bandwidth
                        weight: 3,
                        opacity: 0.7
                    }).addTo(map)
                      .bindPopup(`Link: ${sourceSwitch.nombre} <-> ${destSwitch.nombre}<br>BW: ${link.ancho_banda} Mbps`);
                    polylines.push(polyline);
                    allLatLngs.push([sourceSwitch.latitud, sourceSwitch.longitud]);
                    allLatLngs.push([destSwitch.latitud, destSwitch.longitud]);
                } else {
                    console.warn(`Invalid link switch coordinates for link ${link.id_origen}-${link.id_destino}:`, sourceSwitch, destSwitch);
                }
            });
        } else {
            console.warn('data.enlaces is not an array or is undefined:', data.enlaces);
        }


        // Adjust map bounds to fit all markers
        // Only adjust if there are markers to prevent the map from "zooming out" too much if there's no data.
        if (allLatLngs.length > 0) {
            const bounds = L.latLngBounds(allLatLngs);
            map.fitBounds(bounds, { padding: [50, 50] });
        } else {
            // If no markers, the map will already be at the initial view defined above
            console.log("No markers to adjust map bounds. Keeping initial view.");
        }

    } catch (error) {
        console.error('Error loading topology:', error);
        showMessageModal('Error', 'Could not load network topology: ' + error.message);
    }
}

// --- Dashboard Functions ---
async function updateDashboard() {
    try {
        // Get active server count
        const serversResponse = await fetch(`${API_BASE_URL}/servers/active_servers`);

        // Check if the HTTP response was successful
        if (!serversResponse.ok) {
            const errorData = await serversResponse.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${serversResponse.status} - ${errorData.message || serversResponse.statusText}`);
        }

        const serversData = await serversResponse.json();
        document.getElementById('active-servers-count').textContent = serversData.length;


        // Get current load balancing algorithm
        const configResponse = await fetch(`${API_BASE_URL}/config/current`);

        // Check if the HTTP response was successful
        if (!configResponse.ok) {
            const errorData = await configResponse.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${configResponse.status} - ${errorData.message || configResponse.statusText}`);
        }

        const configData = await configResponse.json();
        document.getElementById('current-lb-algo').textContent = configData.algoritmo_balanceo || 'Not configured';
        document.getElementById('current-routing-algo').textContent = configData.algoritmo_enrutamiento || 'Not configured';

        // Lógica para mostrar/ocultar el input de peso del servidor para WRR
        const serverWeightInputGroup = document.getElementById('server-weight-input-group');
        if (serverWeightInputGroup) { // Asegúrate de que el elemento existe antes de intentar manipularlo
            if (configData.algoritmo_balanceo === 'weighted_round_robin') {
                serverWeightInputGroup.classList.remove('hidden');
            } else {
                serverWeightInputGroup.classList.add('hidden');
            }
        }

        // Update controller status based on switch connectivity
        await updateControllerStatus();

    } catch (error) {
        console.error('Error updating dashboard:', error);
        showMessageModal('Error', 'Could not update dashboard: ' + error.message);
    }
}

async function updateControllerStatus() {
    const controllerStatusElement = document.getElementById('controller-status');
    try {
        const response = await fetch(`${API_BASE_URL}/topology/get`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${response.status} - ${errorData.message || response.statusText}`);
        }
        const data = await response.json();
        const switches = data.switches || [];

        let isConnected = false;
        if (switches.length > 0) {
            isConnected = switches.some(s => s.status === 'conectado');
        }

        if (isConnected) {
            controllerStatusElement.textContent = 'Conectado';
            controllerStatusElement.className = 'text-green-700'; // Green for connected
        } else {
            controllerStatusElement.textContent = 'Desconectado';
            controllerStatusElement.className = 'text-red-700'; // Red for disconnected
        }
    } catch (error) {
        console.error('Error updating controller status:', error);
        controllerStatusElement.textContent = 'Error de Conexión';
        controllerStatusElement.className = 'text-red-700'; // Red for error
    }
}


// --- Configuration Functions ---
async function loadConfigHistory() {
    try {
        const response = await fetch(`${API_BASE_URL}/config/history`);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${response.status} - ${errorData.message || response.statusText}`);
        }

        const data = await response.json();
        const historyDiv = document.getElementById('config-history');
        historyDiv.innerHTML = '';
        if (data.length > 0) {
            data.forEach(item => {
                const p = document.createElement('p');
                p.textContent = `Balanceo: ${item.algoritmo_balanceo || 'N/A'}, Enrutamiento: ${item.algoritmo_enrutamiento || 'N/A'} (Activated: ${new Date(item.fecha_activacion).toLocaleString()})`;
                historyDiv.appendChild(p);
            });
        } else {
            historyDiv.textContent = 'No configuration history.';
        }
    } catch (error) {
        console.error('Error loading configuration history:', error);
        showMessageModal('Error', 'Could not load configuration history: ' + error.message);
    }
}

document.getElementById('save-lb-algo').addEventListener('click', async () => {
    const algo = document.getElementById('lb-algo-select').value;
    const statusMessage = document.getElementById('lb-status-message');
    if (!algo) {
        statusMessage.textContent = 'Please select an algorithm.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/config/balanceo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ algoritmo_balanceo: algo })
        });
        const data = await response.json();
        if (response.ok) {
            statusMessage.textContent = data.message;
            statusMessage.className = 'mt-2 text-sm text-green-600';
            showMessageModal('Success', 'Load balancing algorithm saved successfully.');
            updateDashboard(); // Refresh dashboard
            loadConfigHistory(); // Refresh history
        } else {
            statusMessage.textContent = data.error;
            statusMessage.className = 'mt-2 text-sm text-red-600';
            showMessageModal('Error', `Error saving algorithm: ${data.error}`);
        }
    } catch (error) {
        console.error('Error saving load balancing algorithm:', error);
        statusMessage.textContent = 'Server connection error.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        showMessageModal('Error', 'Connection error when saving algorithm.');
    }
});

document.getElementById('save-routing-algo').addEventListener('click', async () => {
    const algo = document.getElementById('routing-algo-select').value;
    const statusMessage = document.getElementById('routing-status-message');
    if (!algo) {
        statusMessage.textContent = 'Please select a routing algorithm.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/config/enrutamiento`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ algoritmo_enrutamiento: algo })
        });
        const data = await response.json();
        if (response.ok) {
            statusMessage.textContent = data.message;
            statusMessage.className = 'mt-2 text-sm text-green-600';
            showMessageModal('Success', 'Routing algorithm saved successfully.');
            updateDashboard(); // Refresh dashboard
            loadConfigHistory(); // Refresh history
        } else {
            statusMessage.textContent = data.error;
            statusMessage.className = 'mt-2 text-sm text-red-600';
            showMessageModal('Error', `Error saving algorithm: ${data.error}`);
        }
    } catch (error) {
        console.error('Error saving routing algorithm:', error);
        statusMessage.textContent = 'Server connection error.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        showMessageModal('Error', 'Connection error when saving routing algorithm.');
    }
});

// --- Statistics Functions (example, if you have them in your backend) ---
async function cargarEstadisticas() {
    try {
        // Adjust this URL to your actual statistics endpoint
        const res = await fetch(`${API_BASE_URL}/stats/resumen`);

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${res.status} - ${errorData.message || res.statusText}`);
        }

        const data = await res.json();
        const tbody = document.getElementById('tabla-estadisticas'); // Make sure this ID exists in your HTML
        if (tbody) {
            tbody.innerHTML = '';
            data.forEach(row => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td class="p-2">${row.tipo}</td><td class="p-2">${row.total}</td>`;
                tbody.appendChild(tr);
            });
        }
    } catch (err) {
        console.error('Error loading statistics:', err);
        // showMessageModal('Error loading statistics: ' + err.message); // Uncomment if you want the modal
    }
}

async function cargarLogs() {
    try {
        // Adjust this URL to your actual logs endpoint
        const res = await fetch(`${API_BASE_URL}/stats/logs`);

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${res.status} - ${errorData.message || res.statusText}`);
        }

        const data = await res.json();
        const lista = document.getElementById('lista-logs'); // Make sure this ID exists in your HTML
        if (lista) {
            lista.innerHTML = '';
            data.forEach(log => {
                const li = document.createElement('li');
                li.innerHTML = `<span class="font-semibold text-blue-600">${log.origen}</span> - ${log.tipo_evento} - ${log.fecha}`;
                lista.appendChild(li);
            });
        }
    } catch (err) {
        console.error('Error loading logs:', err);
        // showMessageModal('Error loading logs: ' + err.message); // Uncomment if you want the modal
    }
}

// --- Link management functions ---
// Function to assign color to link based on bandwidth
function colorPorAnchoBanda(bw) {
    if (bw >= 1000) return 'green'; // Very high
    if (bw >= 100) return 'yellow';
    if (bw >= 10) return 'orange';
    return 'red'; // Low
}

let allSwitches = []; // To store switch data for dropdowns

async function loadSwitchesForLinks() {
    try {
        const response = await fetch(`${API_BASE_URL}/topology/get`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${response.status} - ${errorData.message || response.statusText}`);
        }
        const data = await response.json();
        allSwitches = data.switches || []; // Store all switches
        populateLinkDropdowns(allSwitches);
    } catch (error) {
        console.error('Error loading switches for link management:', error);
        showMessageModal('Error', 'No se pudieron cargar los switches para la gestión de enlaces.');
    }
}

function populateLinkDropdowns(switches) {
    const newLinkOrigenSelect = document.getElementById("new-link-origen");
    const newLinkDestinoSelect = document.getElementById("new-link-destino");

    [newLinkOrigenSelect, newLinkDestinoSelect].forEach(sel => {
        sel.innerHTML = `<option value="">Seleccionar</option>`;
        switches.forEach(sw => {
            const opt = document.createElement("option");
            opt.value = sw.id_switch;
            opt.textContent = sw.nombre;
            sel.appendChild(opt);
        });
    });
}

async function loadActiveLinks() {
    try {
        const response = await fetch(`${API_BASE_URL}/topology/get`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${response.status} - ${errorData.message || response.statusText}`);
        }
        const data = await response.json();
        const activeLinksList = document.getElementById('active-links-list');
        activeLinksList.innerHTML = '';

        if (data.enlaces && Array.isArray(data.enlaces) && data.enlaces.length > 0) {
            data.enlaces.forEach(link => {
                const sourceSwitch = data.switches.find(sw => sw.id_switch === link.id_origen);
                const destSwitch = data.switches.find(sw => sw.id_switch === link.id_destino);

                if (sourceSwitch && destSwitch) {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td class="py-2 px-4 border-b border-gray-200">${sourceSwitch.nombre}</td>
                        <td class="py-2 px-4 border-b border-gray-200">${destSwitch.nombre}</td>
                        <td class="py-2 px-4 border-b border-gray-200">${link.ancho_banda}</td>
                        <td class="py-2 px-4 border-b border-gray-200">
                            <button class="px-3 py-1 bg-yellow-500 text-white rounded-md hover:bg-yellow-600 transition-colors text-sm edit-link-btn"
                                data-origen-id="${link.id_origen}"
                                data-destino-id="${link.id_destino}"
                                data-bw="${link.ancho_banda}"
                                data-origen-name="${sourceSwitch.nombre}"
                                data-destino-name="${destSwitch.nombre}">Editar</button>
                            <button class="ml-2 px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm delete-link-btn"
                                data-origen-id="${link.id_origen}"
                                data-destino-id="${link.id_destino}"
                                data-origen-name="${sourceSwitch.nombre}"
                                data-destino-name="${destSwitch.nombre}">Eliminar</button>
                        </td>
                    `;
                    activeLinksList.appendChild(tr);
                }
            });

            // Add event listeners for edit and delete buttons after they are rendered
            document.querySelectorAll('.edit-link-btn').forEach(button => {
                button.addEventListener('click', (event) => {
                    const origenId = event.target.dataset.origenId;
                    const destinoId = event.target.dataset.destinoId;
                    const bw = event.target.dataset.bw;
                    const origenName = event.target.dataset.origenName;
                    const destinoName = event.target.dataset.destinoName;
                    openEditLinkModal(origenId, destinoId, bw, origenName, destinoName);
                });
            });

            document.querySelectorAll('.delete-link-btn').forEach(button => {
                button.addEventListener('click', (event) => {
                    const origenId = event.target.dataset.origenId;
                    const destinoId = event.target.dataset.destinoId;
                    const origenName = event.target.dataset.origenName;
                    const destinoName = event.target.dataset.destinoName;
                    deleteLink(origenId, destinoId, origenName, destinoName);
                });
            });

        } else {
            activeLinksList.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-gray-500">No hay enlaces activos.</td></tr>';
        }
    } catch (error) {
        console.error('Error loading active links:', error);
        document.getElementById('active-links-list').innerHTML = '<tr><td colspan="4" class="text-center py-4 text-red-500">Error al cargar enlaces.</td></tr>';
        showMessageModal('Error', 'No se pudieron cargar los enlaces activos: ' + error.message);
    }
}

document.getElementById('create-link-btn').addEventListener('click', async () => {
    const origenId = document.getElementById("new-link-origen").value;
    const destinoId = document.getElementById("new-link-destino").value;
    const bw = document.getElementById("new-link-bw").value;
    const statusMessage = document.getElementById('create-link-status-message');

    if (!origenId || !destinoId || !bw) {
        statusMessage.textContent = 'Por favor, completa todos los campos.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        return;
    }

    if (origenId === destinoId) {
        statusMessage.textContent = 'El origen y el destino no pueden ser el mismo switch.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        return;
    }

    try {
        const res = await fetch(`${API_BASE_URL}/topology/enlace`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                id_origen: parseInt(origenId),
                id_destino: parseInt(destinoId),
                ancho_banda: parseInt(bw)
            })
        });

        const data = await res.json();
        if (res.ok) {
            statusMessage.textContent = data.message || "Enlace creado exitosamente.";
            statusMessage.className = 'mt-2 text-sm text-green-600';
            showMessageModal("Éxito", data.message || "Enlace creado exitosamente.");
            loadTopology(); // Refresh map
            loadActiveLinks(); // Refresh link list
            document.getElementById("new-link-origen").value = "";
            document.getElementById("new-link-destino").value = "";
            document.getElementById("new-link-bw").value = "";
        } else {
            statusMessage.textContent = data.error || "Error al crear el enlace.";
            statusMessage.className = 'mt-2 text-sm text-red-600';
            showMessageModal("Error", data.error || "Error al crear el enlace.");
        }
    } catch (err) {
        console.error('Error creating link:', err);
        statusMessage.textContent = 'Error de conexión con el servidor.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        showMessageModal('Error', 'Error de conexión al crear el enlace: ' + err.message);
    }
});

async function deleteLink(origenId, destinoId, origenName, destinoName) {
    showMessageModal('Confirmar Eliminación', `¿Estás seguro de que quieres eliminar el enlace entre ${origenName} y ${destinoName}?`, true, async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/topology/enlace`, {
                method: "DELETE",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id_origen: parseInt(origenId),
                    id_destino: parseInt(destinoId)
                })
            });

            const data = await res.json();
            if (res.ok) {
                showMessageModal("Éxito", data.message || "Enlace eliminado exitosamente.");
                loadTopology();
                loadActiveLinks();
            } else {
                showMessageModal("Error", data.error || "Error al eliminar el enlace.");
            }
        } catch (err) {
            console.error('Error deleting link:', err);
            showMessageModal('Error', 'Error de conexión al eliminar el enlace: ' + err.message);
        }
    });
}

function openEditLinkModal(origenId, destinoId, bw, origenName, destinoName) {
    document.getElementById('edit-link-origen-display').value = origenName;
    document.getElementById('edit-link-destino-display').value = destinoName;
    document.getElementById('edit-link-bw-input').value = bw;
    document.getElementById('edit-link-origen-id').value = origenId;
    document.getElementById('edit-link-destino-id').value = destinoId;
    document.getElementById('edit-link-modal').classList.remove('hidden');
}

document.getElementById('cancel-edit-link-btn').addEventListener('click', () => {
    document.getElementById('edit-link-modal').classList.add('hidden');
});

document.getElementById('save-edited-link-btn').addEventListener('click', async () => {
    const origenId = document.getElementById('edit-link-origen-id').value;
    const destinoId = document.getElementById('edit-link-destino-id').value;
    const newBw = document.getElementById('edit-link-bw-input').value;

    if (!newBw || newBw <= 0) {
        showMessageModal('Advertencia', 'El ancho de banda debe ser un número positivo.');
        return;
    }

    try {
        const res = await fetch(`${API_BASE_URL}/topology/enlace`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id_origen: parseInt(origenId),
                id_destino: parseInt(destinoId),
                ancho_banda: parseInt(newBw)
            })
        });
        const data = await res.json();
        if (res.ok) {
            showMessageModal('Éxito', data.message || "Enlace actualizado exitosamente.");
            document.getElementById('edit-link-modal').classList.add('hidden');
            loadTopology(); // Refresh map
            loadActiveLinks(); // Refresh link list
        } else {
            showMessageModal('Error', data.error || 'Error al actualizar el enlace.');
        }
    } catch (err) {
        console.error('Error updating link:', err);
        showMessageModal('Error', 'Error de conexión al actualizar el enlace: ' + err.message);
    }
});


// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    loadTopology();
    updateDashboard();
    loadConfigHistory();
    loadSwitchesForLinks(); // Load switches for link dropdowns
    loadActiveLinks(); // Load and display active links

    // Refresh data periodically
    setInterval(updateDashboard, 5000);
    setInterval(loadActiveLinks, 10000); // Refresh links every 10 seconds
});
