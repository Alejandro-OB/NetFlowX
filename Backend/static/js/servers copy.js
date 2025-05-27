// Las constantes API_BASE_URL y MININET_AGENT_URL se asumen globales desde index.js
// Variable para almacenar el ID del host_name que se está editando en el modal
let currentHostForChange = null;

// Cargar hosts disponibles y servidores activos al iniciar
document.addEventListener('DOMContentLoaded', () => {
  // fetchHosts(); // Ahora se llama desde clients.js si es necesario para el selector de cliente
  loadActiveServers(); // Cargar servidores activos
});


// Obtener servidores activos (procesos ffmpeg)
async function loadActiveServers() {
  try {
    const response = await fetch(`${API_BASE_URL}/servers/active_servers`);
    const data = await response.json();
    const serversListDiv = document.getElementById('active-servers-list');
    serversListDiv.innerHTML = '';
    if (data.length > 0) {
        data.forEach(server => {
            const serverDiv = document.createElement('div');
            serverDiv.className = 'p-2 border-b border-gray-200 flex justify-between items-center';
            serverDiv.innerHTML = `
                <div>
                    <p class="font-semibold">${server.host_name}</p>
                    <p>Video: ${server.video_path}</p>
                    <p>IP Multicast: ${server.ip_destino}:${server.puerto}</p>
                    <p>Peso: ${server.server_weight}</p>
                    <p class="text-xs text-gray-500">Estado: ${server.status} (Última actualización: ${new Date(server.last_updated).toLocaleString()})</p>
                </div>
                <button data-host-name="${server.host_name}" class="remove-server-btn px-3 py-1 bg-red-500 text-white rounded-md hover:bg-red-600 transition-colors">Eliminar</button>
            `;
            serversListDiv.appendChild(serverDiv);
        });
        // Adjuntar listeners de eventos a los nuevos botones de eliminar
        document.querySelectorAll('.remove-server-btn').forEach(button => {
            button.addEventListener('click', handleRemoveServer);
        });
    } else {
        serversListDiv.textContent = 'No hay servidores de video activos.';
    }
  } catch (error) {
    console.error('Error cargando servidores activos:', error);
    showMessageModal('Error', 'No se pudo cargar la lista de servidores activos.');
  }
}

document.getElementById('add-server-btn').addEventListener('click', async () => {
    const hostName = document.getElementById('server-host-name').value;
    const videoPath = document.getElementById('server-video-path').value;
    const serverWeight = parseInt(document.getElementById('server-weight').value);
    const statusMessage = document.getElementById('server-status-message');

    if (!hostName || !videoPath || isNaN(serverWeight) || serverWeight < 1) {
        statusMessage.textContent = 'Por favor, completa todos los campos y asegúrate de que el peso sea un número positivo.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/servers/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host_name: hostName, video_path: videoPath, server_weight: serverWeight })
        });
        const data = await response.json();
        if (response.ok) {
            statusMessage.textContent = data.message;
            statusMessage.className = 'mt-2 text-sm text-green-600';
            showMessageModal('Éxito', `Servidor ${hostName} activado. IP Multicast: ${data.multicast_ip}:${data.multicast_port}`);
            document.getElementById('server-host-name').value = '';
            document.getElementById('server-video-path').value = '';
            document.getElementById('server-weight').value = '1';
            loadActiveServers(); // Refrescar lista de servidores
            updateDashboard(); // Refrescar dashboard (función de index.js)
        } else {
            statusMessage.textContent = data.error;
            statusMessage.className = 'mt-2 text-sm text-red-600';
            showMessageModal('Error', `Error al activar servidor: ${data.error}`);
        }
    } catch (error) {
        console.error('Error añadiendo servidor:', error);
        statusMessage.textContent = 'Error de conexión con el servidor.';
        statusMessage.className = 'mt-2 text-sm text-red-600';
        showMessageModal('Error', 'Error de conexión al activar el servidor.');
    }
});

async function handleRemoveServer(event) {
    const hostName = event.target.dataset.hostName;
    showMessageModal('Confirmar Eliminación', `¿Estás seguro de que quieres eliminar el servidor ${hostName}? Esto detendrá el streaming de video en ese host.`, true, async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/servers/remove`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host_name: hostName })
            });
            const data = await response.json();
            if (response.ok) {
                showMessageModal('Éxito', data.message);
                loadActiveServers(); // Refrescar lista de servidores
                updateDashboard(); // Refrescar dashboard (función de index.js)
            } else {
                showMessageModal('Error', `Error al eliminar servidor: ${data.error}`);
            }
        } catch (error) {
            console.error('Error eliminando servidor:', error);
            showMessageModal('Error', 'Error de conexión al eliminar el servidor.');
        }
    });
}

// Las funciones showChangeVideoModal, closeModal, confirmVideoChange, startVideoFromUI, removeAsServer
// del servers.js original no son directamente usadas por el HTML actual,
// pero se mantienen aquí por si se reintroduce la tabla de gestión de servidores con esos botones.
// Si no se usan, pueden ser eliminadas.

// Función para reiniciar un servidor (cuando estaba inactivo en la tabla de activos)
// Esta función asume que hay un endpoint para "iniciar" un servidor existente.
/*
async function startVideoFromUI(host, video_path, ip_destino, puerto) {
    try {
        const response = await fetch(`${API_BASE_URL}/servers/add`, { // Reutilizamos /servers/add para "reiniciar"
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host_name: host, video_path: video_path, ip_destino: ip_destino, puerto: puerto, server_weight: 1 }) // Asume peso 1
        });
        const data = await response.json();
        if (response.ok) {
            showMessageModal('Éxito', `Servidor ${host} reiniciado. IP Multicast: ${data.multicast_ip}:${data.multicast_port}`);
            loadActiveServers();
            updateDashboard();
        } else {
            showMessageModal('Error', `Error al reiniciar servidor: ${data.error}`);
        }
    } catch (error) {
        console.error('Error reiniciando servidor:', error);
        showMessageModal('Error', 'Error de conexión al reiniciar el servidor.');
    }
}
*/

// Función para detener un servidor de video (si se usa un botón de "detener" individual)
/*
async function stopVideoServer(host) {
    showMessageModal(
        'Confirmar Detención',
        `¿Estás seguro de que quieres detener el servidor de video en ${host}?`,
        true,
        async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/servers/remove`, { // Reutilizamos /servers/remove para "detener"
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host_name: host })
                });
                const data = await response.json();
                if (response.ok) {
                    showMessageModal('Éxito', data.message);
                    loadActiveServers();
                    updateDashboard();
                } else {
                    showMessageModal('Error', `Error al detener servidor: ${data.error}`);
                }
            } catch (error) {
                console.error('Error deteniendo servidor:', error);
                showMessageModal('Error', 'Error de conexión al detener el servidor.');
            }
        }
    );
}
*/
