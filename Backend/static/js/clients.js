
let activeHttpClients = [];


async function loadMininetHosts() {
    try {
        // 1. Obtener todos los hosts de Mininet (ahora filtrados por el backend)
        const allHostsResponse = await fetch(`${API_BASE_URL}/client/hosts`);
        if (!allHostsResponse.ok) {
            throw new Error(`HTTP error! status: ${allHostsResponse.status}`);
        }
        const allHostsData = await allHostsResponse.json();
        const availableClientHosts = allHostsData.hosts || []; // Ya vienen filtrados

        const clientHostSelect = document.getElementById('clientHost');
        clientHostSelect.innerHTML = ''; // Limpiar opciones existentes

        // 2. Poblar el dropdown con la lista filtrada
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
        console.error('Error cargando hosts de Mininet:', error);
        showMessageModal('Error', 'No se pudieron cargar los hosts de Mininet: ' + error.message);
        const clientHostSelect = document.getElementById('clientHost');
        clientHostSelect.innerHTML = '<option value="">Error al cargar hosts</option>';
        clientHostSelect.disabled = true;
    }
}

/**
 * Renderiza o actualiza la tabla de clientes FFplay activos.
 */
function updateActiveClientsTable() {
    const tableBody = document.getElementById('active-http-clients-list');
    tableBody.innerHTML = ''; // Limpiar tabla existente

    if (activeHttpClients.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No hay solicitudes activas.</td></tr>';
        return;
    }

    activeHttpClients.forEach(client => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="py-2 px-4 border-b border-gray-200">${client.host}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.server_ip}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.port}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.video}</td>
            <td class="py-2 px-4 border-b border-gray-200">
                <button class="px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm stop-http-client-btn"
                    data-host="${client.host}"
                    data-video="${client.video}">Detener</button>
            </td>
        `;
        tableBody.appendChild(tr);
    });

    // Añadir event listeners a los botones de detener recién creados
    document.querySelectorAll('.stop-http-client-btn').forEach(button => {
        button.addEventListener('click', async (event) => {
            const host = event.target.dataset.host;
            const video = event.target.dataset.video;
            await stopHTTPClient(host, video); // Esta función debes definirla para detener la reproducción
        });
    });
}


document.getElementById('requestStreamBtn').addEventListener('click', async () => {
  const clientHost = document.getElementById('clientHost').value;
  const videoFile = document.getElementById('videoFileName').value;
  const streamInfo = document.getElementById('streamInfo');

  if (!clientHost || !videoFile) {
    streamInfo.textContent = 'Por favor, selecciona un cliente y escribe el nombre del video.';
    streamInfo.className = 'mt-2 text-sm text-red-600';
    return;
  }

  try {
    const response = await fetch(`${MININET_AGENT_URL}/mininet/start_http_client`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: clientHost,
        video_file: videoFile
      })
    });

    const data = await response.json();

    if (response.ok && data.success) {
      streamInfo.textContent = `Reproducción iniciada en ${clientHost}`;
      streamInfo.className = 'mt-2 text-sm text-green-600';
      showMessageModal('Éxito', `El cliente ${clientHost} está reproduciendo ${videoFile}`);
      
      // Actualizar el estado 'es_cliente' a TRUE en la base de datos
      await updateHostClientStatus(clientHost, true);

      // ASUMIMOS un puerto fijo y una IP de servidor si no la obtienes dinámicamente
      const serverIp = '10.0.0.100'; // Define esto según tu configuración
      const port = 8080; // Define esto según tu configuración

      // Añadir registro a la tabla clientes_activos en la DB
      await addActiveClientToDB(clientHost, serverIp, port, videoFile);
      
      loadActiveClientsFromDB(); // Recargar la lista de clientes activos desde la DB
      loadMininetHosts(); // Recargar la lista de hosts disponibles (filtrados)
    } else {
      streamInfo.textContent = `Error al iniciar cliente: ${data.error || 'Desconocido'}`;
      streamInfo.className = 'mt-2 text-sm text-red-600';
    }

  } catch (error) {
    console.error('Error al iniciar cliente HTTP:', error);
    streamInfo.textContent = 'Error de conexión con el agente.';
    streamInfo.className = 'mt-2 text-sm text-red-600';
  }
});

async function stopHttpClient(host) {
  try {
    const response = await fetch(`${MININET_AGENT_URL}/mininet/stop_http_client`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host: host })
    });

    const data = await response.json();

    if (response.ok && data.success) {
      showMessageModal('Éxito', `Cliente FFplay detenido en ${host}.`);
      // Actualizar el estado 'es_cliente' a FALSE en la base de datos
      await updateHostClientStatus(host, false);

      // Eliminar registro de la tabla clientes_activos en la DB
      await removeActiveClientFromDB(host);
      
      loadActiveClientsFromDB(); // Recargar la lista de clientes activos desde la DB
      loadMininetHosts(); // Recargar la lista de hosts disponibles
    } else {
      showMessageModal('Error', `No se pudo detener el cliente: ${data.error || 'Desconocido'}`);
    }
  } catch (error) {
    console.error('Error deteniendo cliente HTTP:', error);
    showMessageModal('Error', 'Error de conexión con el agente al detener el cliente.');
  }
}

// Nueva función para añadir un cliente a la tabla clientes_activos en la DB
async function addActiveClientToDB(host, serverIp, port, videoFile) {
    try {
        const response = await fetch(`${API_BASE_URL}/client/add_active_client`, { // Nuevo endpoint
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: host,
                server_ip: serverIp, // Se espera en el backend
                port: port, // Se espera en el backend
                video_file: videoFile
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            console.error(`Error al añadir cliente activo a la DB para ${host}: ${data.error || 'Desconocido'}`);
        }
    } catch (error) {
        console.error(`Error de conexión al añadir cliente activo a la DB para ${host}:`, error);
    }
}

// Nueva función para eliminar un cliente de la tabla clientes_activos en la DB
async function removeActiveClientFromDB(host) {
    try {
        const response = await fetch(`${API_BASE_URL}/client/remove_active_client`, { // Nuevo endpoint
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

function updateActiveClientsTable() {
    const tableBody = document.getElementById('active-http-clients-list');
    tableBody.innerHTML = ''; // Limpiar opciones existentes

    if (activeHttpClients.length === 0) {
        // Si no hay clientes activos, muestra un mensaje
        tableBody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No hay solicitudes activas.</td></tr>';
        return;
    }

    // Iterar sobre la lista de clientes activos y crear una fila de tabla para cada uno
    activeHttpClients.forEach(client => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="py-2 px-4 border-b border-gray-200">${client.host}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.server_display_name || 'N/A'}</td> <td class="py-2 px-4 border-b border-gray-200">${client.port || 'N/A'}</td>
            <td class="py-2 px-4 border-b border-gray-200">${client.video}</td>
            <td class="py-2 px-4 border-b border-gray-200">
                <button class="px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm stop-http-client-btn"
                    data-host="${client.host}"
                    data-video="${client.video}">Detener</button>
            </td>
        `;
        tableBody.appendChild(tr);
    });

    // Añadir event listeners a los botones "Detener" recién creados
    // Es crucial hacer esto DESPUÉS de que los botones han sido añadidos al DOM
    document.querySelectorAll('.stop-http-client-btn').forEach(button => {
        button.addEventListener('click', async (event) => {
            const host = event.target.dataset.host; // Obtiene el host del atributo data-host
            // No necesitas el video para detener el cliente según tu stopHttpClient actual
            await stopHttpClient(host); // Llama a la función para detener el cliente
        });
    });
}

async function loadActiveClientsFromDB() {
    try {
        const response = await fetch(`${API_BASE_URL}/client/active_clients`); // Nuevo endpoint
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        if (data.active_clients) {
            activeHttpClients = data.active_clients; // Actualizar la lista local
        } else {
            activeHttpClients = [];
        }
        updateActiveClientsTable(); // Actualizar la tabla con los datos cargados
    } catch (error) {
        console.error('Error cargando clientes activos desde la DB:', error);
        showMessageModal('Error', 'No se pudieron cargar los clientes activos: ' + error.message);
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
            console.error(`Error al actualizar el estado de es_cliente para ${hostName}: ${data.error || 'Desconocido'}`);
        }
    } catch (error) {
        console.error(`Error de conexión al actualizar el estado de es_cliente para ${hostName}:`, error);
    }
}

function updateActiveClientsDashboard() {
    const dashboardListDiv = document.getElementById('active-http-clients-dashboard-list');
    dashboardListDiv.innerHTML = ''; // Clear existing content

    if (activeHttpClients.length === 0) {
        dashboardListDiv.textContent = 'No hay clientes activos.';
        return;
    }

    const ul = document.createElement('ul');
    ul.className = 'list-disc list-inside';
    activeHttpClients.forEach(client => {
        const li = document.createElement('li');
        li.textContent = `Cliente: ${client.host} - Servidor: ${client.server_display_name || client.server_ip}`;
        ul.appendChild(li);
    });
    dashboardListDiv.appendChild(ul);
}



// --- Inicialización ---
document.addEventListener('DOMContentLoaded', () => {
    loadMininetHosts(); // Cargar hosts al inicio
    loadActiveClientsFromDB();
    updateActiveClientsDashboard();
    updateActiveClientsTable(); // Inicializar la tabla de clientes activos
    // Refrescar la lista de servidores periódicamente si es necesario para el dashboard
    setInterval(() => {
        loadActiveClientsFromDB();
        updateActiveClientsTable(); // This is already in clients.js for the table
        updateActiveClientsDashboard(); // Add this line to update the dashboard
    }, 10000); 
});
