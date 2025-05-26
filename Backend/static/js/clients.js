// --- Constantes globales para las URLs de la API (asumidas desde index.js) ---
// const API_BASE_URL = 'http://192.168.18.151:5000'; 
// const MININET_AGENT_URL = 'http://192.168.18.206:5002';

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
function updateActiveClientsTable() {
    const tableBody = document.getElementById('active-ffplay-clients-list');
    tableBody.innerHTML = ''; // Limpiar tabla existente

    if (activeFFplayClients.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No hay clientes FFplay activos.</td></tr>';
        return;
    }

    activeFFplayClients.forEach(client => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="py-2 px-4 border-b border-gray-200">${client.host}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.multicastIp}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.multicastPort}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.ffplayPid || 'N/A'}</td>
            <td class="py-2 px-4 border-b border-gray-200">
                <button class="px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm stop-ffplay-client-btn"
                    data-host="${client.host}"
                    data-ffplay-pid="${client.ffplayPid}">Detener</button>
            </td>
        `;
        tableBody.appendChild(tr);
    });

    // Añadir event listeners a los botones de detener recién creados
    document.querySelectorAll('.stop-ffplay-client-btn').forEach(button => {
        button.addEventListener('click', async (event) => {
            const host = event.target.dataset.host;
            const ffplayPid = event.target.dataset.ffplayPid; // Obtener el PID específico
            await stopFFmpegClient(host, ffplayPid); // Llamar a la función de detención
        });
    });
}

/**
 * Inicia un cliente FFplay en un host de Mininet.
 * @param {string} host - Nombre del host cliente.
 * @param {string} multicastIp - IP Multicast del stream.
 * @param {number} multicastPort - Puerto Multicast del stream.
 */
async function startFFmpegClient(host, multicastIp, multicastPort) {
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
            // Añadir el cliente a la lista de activos
            activeFFplayClients.push({
                host: host,
                multicastIp: multicastIp,
                multicastPort: multicastPort,
                ffplayPid: data.ffplay_client_pid // Asegúrate de que el agente devuelva este PID
            });
            updateActiveClientsTable(); // Actualizar la tabla
            loadMininetHosts(); // Volver a cargar la lista de hosts para actualizar el dropdown
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
async function stopFFmpegClient(host, ffplayPid) {
    showMessageModal('Confirmar Detención', `¿Estás seguro de que quieres detener el cliente FFplay en ${host} (PID: ${ffplayPid})?`, true, async () => {
        try {
            const response = await fetch(`${MININET_AGENT_URL}/mininet/stop_ffmpeg_client`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host: host, ffplay_pid: ffplayPid }) // Enviar el PID específico
            });
            const data = await response.json();
            if (response.ok && data.success) {
                showMessageModal('Éxito', `FFplay detenido en ${host}.`);
                // Eliminar el cliente de la lista de activos
                activeFFplayClients = activeFFplayClients.filter(client => client.ffplayPid !== ffplayPid);
                updateActiveClientsTable(); // <--- ¡Aquí está la llamada que faltaba!
                loadMininetHosts(); // Volver a cargar la lista de hosts para actualizar el dropdown
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

        if (response.ok && data.multicast_ip && data.multicast_port) {
            streamInfoParagraph.textContent = `Asignado al servidor: ${data.host_name}. IP Multicast: ${data.multicast_ip}:${data.multicast_port}. Iniciando cliente FFplay...`;
            streamInfoParagraph.className = 'mt-2 text-sm text-green-600';
            
            // Iniciar FFplay automáticamente después de obtener la info del stream
            await startFFmpegClient(clientHost, data.multicast_ip, data.multicast_port);

        } else {
            streamInfoParagraph.textContent = `Error: ${data.error || 'No se pudo obtener información del stream.'}`;
            streamInfoParagraph.className = 'mt-2 text-sm text-red-600';
        }
    } catch (error) {
        console.error('Error solicitando información del stream:', error);
        streamInfoParagraph.textContent = 'Error de conexión al solicitar información del stream.';
        streamInfoParagraph.className = 'mt-2 text-sm text-red-600';
    }
});


// --- Inicialización ---
document.addEventListener('DOMContentLoaded', () => {
    loadMininetHosts(); // Cargar hosts al inicio
    updateActiveClientsTable(); // Inicializar la tabla de clientes activos
    // Refrescar la lista de servidores periódicamente si es necesario para el dashboard
    // setInterval(loadActiveServers, 10000); 
});
