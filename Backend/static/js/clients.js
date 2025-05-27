
let activeHttpClients = [];


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
      
      // Añadir a la lista local si estás usando una tabla de clientes activos
      activeHttpClients.push({
        host: clientHost,
        video: videoFile,
        server: '10.0.0.100',
        port: 8080
      });
      updateActiveHttpClientsTable();
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
      // Eliminarlo de la lista local y actualizar la tabla si tienes una estructura así
      activeHttpClients = activeHttpClients.filter(client => client.host !== host);
      updateActiveHttpClientsTable();
      loadMininetHosts();
    } else {
      showMessageModal('Error', `No se pudo detener el cliente: ${data.error || 'Desconocido'}`);
    }
  } catch (error) {
    console.error('Error deteniendo cliente HTTP:', error);
    showMessageModal('Error', 'Error de conexión con el agente al detener el cliente.');
  }
}





function updateActiveHttpClientsTable() {
  const tableBody = document.getElementById('active-http-clients-list');
  tableBody.innerHTML = '';

  if (activeHttpClients.length === 0) {
    tableBody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No hay solicitudes activas.</td></tr>';
    return;
  }

  activeHttpClients.forEach(client => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="py-2 px-4 border-b border-gray-200">${client.host}</td>
      <td class="py-2 px-4 border-b border-gray-200">${client.serverIp}</td>
      <td class="py-2 px-4 border-b border-gray-200">${client.port}</td>
      <td class="py-2 px-4 border-b border-gray-200">${client.video}</td>
      <td class="py-2 px-4 border-b border-gray-200">
        <button class="px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm" onclick="stopHttpClient('${client.host}')">Detener</button>
      </td>
    `;
    tableBody.appendChild(tr);
  });
}


// --- Inicialización ---
document.addEventListener('DOMContentLoaded', () => {
    loadMininetHosts(); // Cargar hosts al inicio
    updateActiveClientsTable(); // Inicializar la tabla de clientes activos
    // Refrescar la lista de servidores periódicamente si es necesario para el dashboard
    // setInterval(loadActiveServers, 10000); 
});
