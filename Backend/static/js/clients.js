// Array global para mantener el estado de los clientes FFplay activos
let activeFFplayClients = [];

// --- Funciones de Clientes Multicast ---
async function loadMininetHosts() {
    try {
        // 1. Obtener todos los hosts de Mininet
        const allHostsResponse = await fetch(`${API_BASE_URL}/client/hosts`);
        if (!allHostsResponse.ok) {
            throw new Error(`HTTP error! status: ${allHostsResponse.status}`);
        }
        const allHostsData = await allHostsResponse.json();
        const allMininetHosts = allHostsData.hosts || [];

        // 2. Obtener los servidores activos
        const activeServersResponse = await fetch(`${API_BASE_URL}/servers/active_servers`);
        if (!activeServersResponse.ok) {
            const errorData = await activeServersResponse.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${activeServersResponse.status} - ${errorData.message || activeServersResponse.statusText}`);
        }
        const activeServersData = await activeServersResponse.json();
        // Mapear los datos de los servidores activos a una lista de sus nombres de host
        const activeServerNames = activeServersData.map(server => server.host_name);

        const clientHostSelect = document.getElementById('clientHost');
        clientHostSelect.innerHTML = ''; // Limpiar opciones existentes

        // 3. Filtrar los hosts: solo incluir aquellos que NO son servidores activos
        const availableClientHosts = allMininetHosts.filter(host => {
            return !activeServerNames.includes(host.name);
        });

        // 4. Poblar el dropdown con la lista filtrada
        if (availableClientHosts.length > 0) {
            // Añadir una opción por defecto para seleccionar
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = 'Seleccionar Cliente';
            clientHostSelect.appendChild(defaultOption);

            availableClientHosts.forEach(host => {
                const option = document.createElement('option');
                option.value = host.name;
                option.textContent = host.name;
                clientHostSelect.appendChild(option);
            });
            clientHostSelect.disabled = false; // Habilitar el dropdown si hay hosts
        } else {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'No hay hosts disponibles para clientes';
            clientHostSelect.appendChild(option);
            clientHostSelect.disabled = true; // Deshabilitar si no hay hosts
        }
    } catch (error) {
        console.error('Error cargando hosts de Mininet o servidores activos:', error);
        showMessageModal('Error', 'No se pudieron cargar los hosts de Mininet o servidores activos: ' + error.message);
        const clientHostSelect = document.getElementById('clientHost');
        clientHostSelect.innerHTML = '<option value="">Error al cargar hosts</option>';
        clientHostSelect.disabled = true;
    }
}

/**
 * Renderiza o actualiza la tabla de clientes FFplay activos.
 */
async function updateActiveClientsTable() {
    const tableBody = document.getElementById('active-ffplay-clients-list');
    tableBody.innerHTML = ''; // Limpiar tabla existente

    try {
        const response = await fetch(`${API_BASE_URL}/client/active_clients`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        const activeClients = data.active_clients || [];

        if (activeClients.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-gray-500">No hay clientes activos.</td></tr>';
            return;
        }

        activeClients.forEach(client => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="py-2 px-4 border-b">${client.host}</td>
                <td class="py-2 px-4 border-b">${client.server_display_name || 'N/A'}</td>
                <td class="py-2 px-4 border-b">${client.ip_destino_raw || 'N/A'}</td>
                <td class="py-2 px-4 border-b">${client.port || 'N/A'}</td>
                <td class="py-2 px-4 border-b">${client.video}</td>
                <td class="py-2 px-4 border-b">${client.timestamp_inicio || '-'}</td>
                <td class="py-2 px-4 border-b">
                    <button class="px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm stop-ffplay-client-btn"
                        data-host="${client.host}">Detener</button>
                </td>
            `;
            tableBody.appendChild(tr);
        });

        // Listeners para los botones de "Detener"
        document.querySelectorAll('.stop-ffplay-client-btn').forEach(button => {
            button.addEventListener('click', async (event) => {
                const host = event.target.dataset.host;
                // Opcionalmente podrías pedir confirmación
                await stopFFmpegClient(host, null); // Debes modificar stopFFmpegClient para aceptar solo el host
            });
        });

    } catch (error) {
        console.error('Error al cargar clientes activos desde la base de datos:', error);
        tableBody.innerHTML = '<tr><td colspan="7" class="text-center text-red-600">Error al cargar datos.</td></tr>';
    }
}


/**
 * Inicia un cliente FFplay en un host de Mininet.
 * @param {string} host - Nombre del host cliente.
 * @param {string} multicastIp - IP Multicast del stream.
 * @param {number} multicastPort - Puerto Multicast del stream.
 */
async function startFFmpegClient(host, streamInfo) {
    const { multicastIp, multicastPort, serverName } = streamInfo;
    try {
        const response = await fetch(`${MININET_AGENT_URL}/mininet/start_ffmpeg_client`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: host,
                multicast_ip: multicastIp,
                puerto: parseInt(multicastPort)
            })
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showMessageModal('Éxito', `Cliente FFplay iniciado en ${host} para ${multicastIp}:${multicastPort}`);


            await updateHostClientStatus(host, true);

            console.log('Valores a enviar a la BD:', {
                host,
                multicastIp,
                multicastPort,
                videoFile: 'stream_multicast',
                serverName
            });

            if (!serverName || !multicastIp || !multicastPort) {
                console.error("❌ Datos incompletos del servidor:", streamInfo);
                showMessageModal("Error", "La información del servidor asignado está incompleta.");
                return;
            }

            await addActiveClientToDB(host, multicastIp, multicastPort, 'stream_multicast', serverName);
            loadActiveClientsFromDB();
            
            //updateActiveClientsTable();
            loadMininetHosts();
        } else {
            showMessageModal('Error', `Error al iniciar FFplay: ${data.error || 'Error desconocido'}`);
        }
    } catch (error) {
        console.error('Error iniciando FFplay cliente:', error);
        showMessageModal('Error', 'Error de conexión al iniciar FFplay cliente.');
    }
}



/**
 * Detiene un cliente FFplay específico en un host de Mininet.
 * @param {string} host - Nombre del host cliente.
 * @param {string} ffplayPid - PID del proceso FFplay a detener.
 */
async function stopFFmpegClient(host, ffplayPid = null) {
    const confirmMessage = `¿Deseas detener el cliente FFplay en ${host}${ffplayPid ? ` (PID: ${ffplayPid})` : ''}?`;
    showMessageModal('Confirmar Detención', confirmMessage, true, async () => {
        try {
            const payload = { host: host };
            if (ffplayPid) {
                payload.ffplay_pid = ffplayPid;
            }

            const response = await fetch(`${MININET_AGENT_URL}/mininet/stop_ffmpeg_client`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showMessageModal('Éxito', `FFplay detenido en ${host}.`);
                await updateHostClientStatus(host, false);
                await removeActiveClientFromDB(host);
                updateActiveClientsTable();
                loadMininetHosts();
            } else {
                showMessageModal('Error', `Error al detener FFplay: ${data.error || 'Error desconocido'}`);
            }
        } catch (error) {
            console.error('Error deteniendo FFplay cliente:', error);
            showMessageModal('Error', 'Error de conexión al detener FFplay cliente.');
        }
    });
}



// Event listener para el botón "Solicitar Video Multicast"
document.getElementById('requestStreamBtn').addEventListener('click', async () => {
    const clientHost = document.getElementById('clientHost').value;
    const streamInfoParagraph = document.getElementById('streamInfo');

    if (!clientHost) {
        streamInfoParagraph.textContent = 'Por favor, selecciona un host cliente.';
        streamInfoParagraph.className = 'mt-2 text-sm text-red-600';
        return;
    }

    // Verificar si el host ya está en la lista de clientes activos (para evitar duplicados)
    if (activeFFplayClients.some(client => client.host === clientHost)) {
        showMessageModal('Advertencia', `El host ${clientHost} ya tiene un cliente FFplay activo.`);
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/client/get_multicast_stream_info`);
        const data = await response.json();

        if (response.ok && data.host_name && data.multicast_ip && data.multicast_port) {
            streamInfoParagraph.textContent = `Asignado al servidor: ${data.host_name}. IP Multicast: ${data.multicast_ip}:${data.multicast_port}. Iniciando cliente FFplay...`;
            streamInfoParagraph.className = 'mt-2 text-sm text-green-600';

            // Crear objeto con la información del stream
            const streamInfo = {
                serverName: data.host_name,
                multicastIp: data.multicast_ip,
                multicastPort: data.multicast_port
            };

            // Iniciar cliente FFplay con toda la info del servidor
            await startFFmpegClient(clientHost, streamInfo);

        } else {
            console.error("❌ Datos incompletos del backend:", data);
            streamInfoParagraph.textContent = `Error: No se pudo obtener información completa del servidor.`;
            streamInfoParagraph.className = 'mt-2 text-sm text-red-600';
        }
    } catch (error) {
        console.error('Error solicitando información del stream:', error);
        streamInfoParagraph.textContent = 'Error de conexión al solicitar información del stream.';
        streamInfoParagraph.className = 'mt-2 text-sm text-red-600';
    }
});


async function updateActiveClientsDashboard() {
    const dashboardListDiv = document.getElementById('active-http-clients-dashboard-list');
    dashboardListDiv.innerHTML = ''; // Limpiar contenido previo

    try {
        const response = await fetch(`${API_BASE_URL}/client/active_clients`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        const activeClients = data.active_clients || [];

        if (activeClients.length === 0) {
            dashboardListDiv.textContent = 'No hay clientes activos.';
            return;
        }

        const ul = document.createElement('ul');
        ul.className = 'list-disc list-inside';

        activeClients.forEach(client => {
            const li = document.createElement('li');
            li.textContent = `Cliente: ${client.host} - Servidor: ${client.server_display_name || client.server_ip}`;
            ul.appendChild(li);
        });

        dashboardListDiv.appendChild(ul);

    } catch (error) {
        console.error('Error al cargar el dashboard de clientes activos desde la BD:', error);
        dashboardListDiv.textContent = 'Error al cargar clientes activos.';
    }
}



async function addActiveClientToDB(host, serverIp, port, videoFile, serverName) {
    if (!host || !serverIp || !port || !videoFile || !serverName) {
        console.error("❌ Parámetros incompletos para guardar en BD:", { host, serverIp, port, videoFile, serverName });
        return;
    }
    try {
        const response = await fetch(`${API_BASE_URL}/client/add_active_client`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: host,
                server_ip: serverIp,
                port: port,
                video_file: videoFile,
                server_name: serverName
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            console.error(`❌ Error al añadir cliente activo a la DB para ${host}: ${data.error || 'Desconocido'}`);
        }
    } catch (error) {
        console.error(`❌ Error de conexión al añadir cliente activo a la DB para ${host}:`, error);
    }
}



async function removeActiveClientFromDB(host) {
    try {
        const response = await fetch(`${API_BASE_URL}/client/remove_active_client`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host: host })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            console.error(`Error al eliminar cliente activo de la DB para ${host}: ${data.error || 'Desconocido'}`);
        }
    } catch (error) {
        console.error(`Error de conexión al eliminar cliente activo de la DB para ${host}:`, error);
    }
}

async function updateHostClientStatus(hostName, isClient) {
    try {
        const response = await fetch(`${API_BASE_URL}/client/update_client_status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host_name: hostName, is_client: isClient })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            console.error(`Error al actualizar es_cliente para ${hostName}: ${data.error || 'Desconocido'}`);
        }
    } catch (error) {
        console.error(`Error de conexión al actualizar es_cliente para ${hostName}:`, error);
    }
}

async function loadActiveClientsFromDB() {
    try {
        const response = await fetch(`${API_BASE_URL}/client/active_clients`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        if (data.active_clients) {
            activeFFplayClients = data.active_clients;
        } else {
            activeFFplayClients = [];
        }
        updateActiveClientsTable();
        updateActiveClientsDashboard();
    } catch (error) {
        console.error('Error cargando clientes activos desde la DB:', error);
        showMessageModal('Error', 'No se pudieron cargar los clientes activos: ' + error.message);
    }
}

// --- Inicialización ---
document.addEventListener('DOMContentLoaded', () => {
    loadMininetHosts(); 
    updateActiveClientsTable(); 
    updateActiveClientsDashboard();
    setInterval(() => {
        updateActiveClientsTable();
        updateActiveClientsDashboard(); 
    }, 10000);
});
