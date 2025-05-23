// Variable para almacenar el ID del host_name que se está editando en el modal
let currentHostForChange = null;

// La API_BASE_URL debe apuntar a tu servidor Flask principal
// Si tu app.py corre en 192.168.18.151:5000, entonces esta es la correcta.
// Los endpoints de servers.py se accederán a través del prefijo /servers/
const API_BASE_URL = 'http://192.168.18.151:5000'; 


// Cargar hosts disponibles y servidores activos al iniciar
document.addEventListener('DOMContentLoaded', () => {
  fetchHosts();
  fetchActiveServers();

  // Asignar el listener al botón de inicio de servidor principal
  const startBtn = document.getElementById('start-video-server-btn');
  if (startBtn) {
      // Modificamos el listener para que llame a startVideoServer sin parámetros,
      // la cual leerá los valores de los inputs.
      startBtn.addEventListener('click', () => startVideoServer());
  }
});

// Función para mostrar mensajes modales (reemplaza alert/confirm)
function showMessageModal(title, content, type = 'info', confirmCallback = null) {
    const modal = document.getElementById('message-modal');
    document.getElementById('message-modal-title').innerText = title;
    document.getElementById('message-modal-content').innerText = content;
    const confirmBtn = document.getElementById('message-modal-confirm-btn');
    const closeBtn = document.getElementById('message-modal-close-btn');

    // Limpiar listeners anteriores para evitar múltiples ejecuciones
    confirmBtn.onclick = null;
    closeBtn.onclick = null;

    if (confirmCallback) {
        confirmBtn.classList.remove('hidden');
        confirmBtn.onclick = () => {
            confirmCallback();
            modal.classList.add('hidden');
        };
    } else {
        confirmBtn.classList.add('hidden');
    }

    // Asegúrate de que el botón de cerrar siempre funcione
    closeBtn.onclick = () => {
        modal.classList.add('hidden');
    };


    modal.classList.remove('hidden');
}


// Obtener lista de hosts disponibles
async function fetchHosts() {
  try {
    // Apunta al nuevo endpoint /servers/api/hosts
    const response = await fetch(`${API_BASE_URL}/servers/api/hosts`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const hosts = await response.json();
    
    const select = document.getElementById('host-select');
    select.innerHTML = '';
    
    // Añadir opción por defecto
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = '-- Selecciona un host --';
    defaultOption.disabled = true;
    defaultOption.selected = true;
    select.appendChild(defaultOption);
    
    // Llenar con hosts disponibles
    if (hosts.length === 0) {
        const noHostsOption = document.createElement('option');
        noHostsOption.value = '';
        noHostsOption.textContent = 'No hay hosts disponibles';
        noHostsOption.disabled = true;
        select.appendChild(noHostsOption);
    } else {
        hosts.forEach(host => {
            const option = document.createElement('option');
            option.value = host; // El backend ahora devuelve solo el nombre
            option.textContent = host;
            select.appendChild(option);
        });
    }
    // select.selectedIndex = -1; // Deseleccionar por defecto - puede causar que no se detecte la selección
  } catch (error) {
    console.error('Error fetching hosts:', error);
    showMessageModal('Error', 'Error al cargar los hosts disponibles: ' + error.message);
  }
}

// Obtener servidores activos (procesos ffmpeg)
async function fetchActiveServers() {
  try {
    // Apunta al nuevo endpoint /servers/api/active_vlc_servers
    const response = await fetch(`${API_BASE_URL}/servers/api/active_vlc_servers`);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    
    const servers = await response.json();

    let activos = 0;
    let inactivos = 0;

    // Convertir la lista de servidores a un formato de objeto para updateActiveServersTable
    const activeServersMap = {};
    servers.forEach(server => {
      const status = server.status === 'activo' ? 'running' : 'detenido';
      if (server.status === 'activo') {
        activos++;
      } else {
        inactivos++;
      }
      activeServersMap[server.host] = {
        video_path: server.video, // 'video' viene del backend
        status: status,
        ip_destino: server.ip_destino,
        puerto: server.puerto
      };
    });

    // Asegúrate de que estos elementos existan en tu HTML si quieres mostrar contadores
    const vlcActivosElem = document.getElementById('vlc-activos');
    const vlcInactivosElem = document.getElementById('vlc-inactivos');
    if (vlcActivosElem) vlcActivosElem.textContent = activos;
    if (vlcInactivosElem) vlcInactivosElem.textContent = inactivos;

    updateActiveServersTable(activeServersMap);
  } catch (error) {
    console.error('Error fetching active servers:', error);
    showMessageModal('Error', 'Error al cargar los servidores activos: ' + error.message);
  }
}

// Actualizar tabla de servidores activos
function updateActiveServersTable(servers) {
  const tableBody = document.getElementById('active-servers-table-body'); // Asegúrate de que tu <tbody> tenga este ID
  if (!tableBody) {
      console.error("Elemento 'active-servers-table-body' no encontrado.");
      return;
  }
  tableBody.innerHTML = '';
  
  if (Object.keys(servers).length === 0) {
    tableBody.innerHTML = '<tr><td colspan="4" class="p-2 text-center text-gray-500">No hay servidores VLC activos.</td></tr>';
    return;
  }

  Object.entries(servers).forEach(([host, server]) => {
    const row = document.createElement('tr');
    row.className = 'border-t border-gray-200 hover:bg-gray-50';

    const estadoHTML = `
      <span class="px-2 py-1 rounded-full text-xs font-medium ${
        server.status === 'running' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
      }">
        ${server.status === 'running' ? 'Activo' : 'Inactivo'}
      </span>
    `;

    const accionesHTML = server.status === 'running'
      ? `
        <button onclick="showChangeVideoModal('${host}')" 
                class="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded text-xs">
          Cambiar
        </button>
        <button onclick="stopVideoServer('${host}')" 
                class="bg-red-500 hover:bg-red-600 text-white px-3 py-1 rounded text-xs">
          Detener
        </button>
      `
      : `
        <button onclick="startVideoFromUI('${host}', '${server.video_path || ''}', '${server.ip_destino || ''}', '${server.puerto || ''}')" 
                class="bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded text-xs">
          Iniciar
        </button>
        <button onclick="removeAsServer('${host}')" 
                class="bg-gray-500 hover:bg-gray-600 text-white px-3 py-1 rounded text-xs">
          Eliminar Rol
        </button>
      `;

    row.innerHTML = `
      <td class="p-2">${host}</td>
      <td class="p-2">${server.video_path || 'N/A'}</td>
      <td class="p-2">${estadoHTML}</td>
      <td class="p-2 space-x-2">${accionesHTML}</td>
    `;

    tableBody.appendChild(row);
  });
}


// Iniciar servidor de video - Lógica centralizada
// Ahora acepta parámetros opcionales para permitir ser llamada desde startVideoFromUI
async function startVideoServer(hostParam = null, videoPathParam = null, ipDestinoParam = null, puertoUdpParam = null) {
  let selectedHosts = [];
  let videoPath, ipDestino, puertoUdp;

  if (hostParam && videoPathParam && ipDestinoParam && puertoUdpParam) {
    // Si se llaman con parámetros (desde startVideoFromUI)
    selectedHosts = [hostParam];
    videoPath = videoPathParam;
    ipDestino = ipDestinoParam;
    puertoUdp = puertoUdpParam;
  } else {
    // Si se llaman desde el botón principal (sin parámetros)
    const hostSelect = document.getElementById('host-select');
    selectedHosts = Array.from(hostSelect.selectedOptions).map(opt => opt.value).filter(value => value !== ''); // Filtra la opción por defecto
    
    videoPath = document.getElementById('video-path').value;
    ipDestino = document.getElementById('ip-destino').value;
    puertoUdp = document.getElementById('puerto-udp').value;
  }

  if (selectedHosts.length === 0) {
    showMessageModal('Advertencia', 'Por favor selecciona al menos un host.');
    return;
  }
  if (!videoPath) {
    showMessageModal('Advertencia', 'La ruta del video es requerida.');
    return;
  }
  if (!ipDestino || !puertoUdp) {
    showMessageModal('Advertencia', 'La IP de Destino y el Puerto UDP son requeridos.');
    return;
  }
  
  const startBtn = document.getElementById('start-video-server-btn');
  const originalText = startBtn.textContent;
  if (startBtn) { // Asegúrate de que el botón existe antes de manipularlo
    startBtn.disabled = true;
    startBtn.textContent = 'Iniciando...';
  }
  
  let successCount = 0;
  let errorMessages = [];
  
  for (const host of selectedHosts) {
    try {
      const response = await fetch(`${API_BASE_URL}/servers/api/start_vlc_server`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          host: host,
          video_path: videoPath,
          ip_destino: ipDestino,
          puerto: parseInt(puertoUdp) // Asegúrate de que el puerto sea un número
        })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        // Lanzar un error para que el bloque catch lo capture
        throw new Error(data.message || data.error || `Error HTTP ${response.status}`);
      }
      
      console.log(`Servidor iniciado en ${host}:`, data);
      successCount++;
      
    } catch (error) {
      console.error(`Error al iniciar servidor en host ${host}:`, error);
      errorMessages.push(`• ${host}: ${error.message}`);
    }
  }
  
  // Mostrar resultados con el modal
  if (errorMessages.length > 0) {
    let title = 'Resultado Parcial';
    let message = `${successCount} servidor(es) iniciado(s) correctamente.\n\nErrores:\n${errorMessages.join('\n')}`;
    let type = 'warning';
    if (successCount === 0) { // Si no se inició ningún servidor
        title = 'Error';
        message = `No se pudo iniciar ningún servidor.\n\nErrores:\n${errorMessages.join('\n')}`;
        type = 'error';
    }
    showMessageModal(title, message, type);
  } else {
    showMessageModal('Éxito', `Todos los servidores (${successCount}) iniciados correctamente.`);
  }
  
  // Restaurar UI y recargar listas
  if (startBtn) { // Asegúrate de que el botón existe antes de manipularlo
    startBtn.disabled = false;
    startBtn.textContent = originalText;
  }
  fetchActiveServers(); 
  fetchHosts();       
}

// Detener servidor de video
async function stopVideoServer(host) {
  showMessageModal(
    'Confirmar Detención',
    `¿Estás seguro de que quieres detener el servidor de video en ${host}?`,
    'warning',
    async () => { // Callback de confirmación
      try {
        const response = await fetch(`${API_BASE_URL}/servers/api/stop_vlc_server`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ host: host })
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.message || data.error || 'Error al detener el servidor de video.');
        }
        
        showMessageModal('Éxito', data.message);
        fetchActiveServers();
        fetchHosts(); // Vuelve a cargar hosts para actualizar la lista de disponibles (no debería cambiar si solo se detuvo el VLC)
      } catch (error) {
        console.error('Error deteniendo servidor:', error);
        showMessageModal('Error', 'Error al detener el servidor: ' + error.message);
      }
    }
  );
}

// Mostrar modal para cambiar video
function showChangeVideoModal(host) {
  currentHostForChange = host;

  const activeServersTableBody = document.getElementById('active-servers-table-body');
  const row = Array.from(activeServersTableBody.rows).find(r => r.cells[0].textContent === host);
  if (row) {
      document.getElementById('new-video-path').value = row.cells[1].textContent;
  } else {
      document.getElementById('new-video-path').value = ''; // Limpiar campo si no se encuentra
  }
  document.getElementById('change-video-modal').classList.remove('hidden');
}

// Cerrar modal de cambio de video
function closeModal() {
  document.getElementById('change-video-modal').classList.add('hidden');
  currentHostForChange = null;
}

// Confirmar cambio de video
async function confirmVideoChange() {
  const newVideoPath = document.getElementById('new-video-path').value;
  
  if (!newVideoPath) {
    showMessageModal('Advertencia', 'Por favor ingresa una nueva ruta de video.');
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE_URL}/servers/api/change_vlc_video`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        host: currentHostForChange,
        new_video_path: newVideoPath
      })
    });
    
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || data.error || 'Error al cambiar el video.');
    }
    
    showMessageModal('Éxito', data.message);
    closeModal();
    fetchActiveServers(); // Recargar para ver el cambio
  } catch (error) {
    console.error('Error cambiando video:', error);
    showMessageModal('Error', 'Error al cambiar el video: ' + error.message);
  }
}

// Función para reiniciar un servidor (cuando estaba inactivo en la tabla de activos)
async function startVideoFromUI(host, video_path, ip_destino, puerto) {
    // Ahora, en lugar de llamar a startVideoServer sin parámetros,
    // la llamamos con los parámetros directamente.
    startVideoServer(host, video_path, ip_destino, puerto);
}

// Función para eliminar el rol de servidor de un host
async function removeAsServer(host) {
  showMessageModal(
    'Confirmar Eliminación de Rol',
    `¿Estás seguro de que quieres eliminar el rol de servidor de ${host}? Esto detendrá cualquier proceso de video asociado y eliminará su registro.`,
    'warning',
    async () => { // Callback de confirmación
      try {

        const response = await fetch(`${API_BASE_URL}/servers/hosts/remover-servidor/${host}`, {
          method: 'PUT' // Es PUT porque se está actualizando el rol de un recurso existente
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.message || data.error || 'Error al eliminar el rol de servidor.');
        }

        showMessageModal('Éxito', data.message);
        fetchActiveServers(); // Recargar para ver el cambio de rol
        fetchHosts(); // Recargar la lista de hosts disponibles (el host debería reaparecer aquí)
      } catch (error) {
        console.error('Error eliminando rol de servidor:', error);
        showMessageModal('Error', 'Error: ' + error.message);
      }
    }
  );
}