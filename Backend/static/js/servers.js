let currentHostForChange = null;
const API_BASE_URL = 'http://192.168.18.151:5000';

// Cargar hosts disponibles al iniciar
document.addEventListener('DOMContentLoaded', () => {
  fetchHosts();
  fetchActiveServers();

});

// Obtener lista de hosts disponibles
async function fetchHosts() {
  try {
    const response = await fetch(`${API_BASE_URL}/servers/hosts/no-servidores`);
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
    hosts.forEach(host => {
      const option = document.createElement('option');
      option.value = host.nombre;
      option.textContent = host.nombre;
      select.appendChild(option);
    });
  } catch (error) {
    console.error('Error fetching hosts:', error);
    alert('Error al cargar los hosts disponibles');
  }
}

// Obtener servidores activos o declarados como servidores
async function fetchActiveServers() {
  try {
    const response = await fetch(`${API_BASE_URL}/servers/active_servers`);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    
    const servers = await response.json();

    const activeServers = {};
    let activos = 0;
    let inactivos = 0;

    servers.forEach(server => {
      const status = server.activo ? 'running' : 'detenido';
      if (server.activo) {
        activos++;
      } else {
        inactivos++;
      }

      activeServers[server.nombre] = {
        video_path: 'N/A',
        status: status
      };
    });

    // Actualizar contadores en el dashboard
    document.getElementById('vlc-activos').textContent = activos;
    document.getElementById('vlc-inactivos').textContent = inactivos;

    updateActiveServersTable(activeServers);
  } catch (error) {
    console.error('Error fetching active servers:', error);
  }
}



// Actualizar tabla de servidores activos
function updateActiveServersTable(servers) {
  const table = document.getElementById('active-servers-table');
  table.innerHTML = '';
  
  Object.entries(servers).forEach(([host, server]) => {
    const row = document.createElement('tr');
    row.className = 'border-t border-gray-200 hover:bg-gray-50';

    const estadoHTML = `
      <span class="px-2 py-1 rounded-full text-xs font-medium ${
        server.status === 'running' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
      }">
        ${server.status}
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
        <button onclick="startVideoFromUI('${host}')" 
                class="bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded text-xs">
          Iniciar
        </button>
        <button onclick="removeAsServer('${host}')" 
                class="bg-gray-500 hover:bg-gray-600 text-white px-3 py-1 rounded text-xs">
          Eliminar
        </button>
      `;

    row.innerHTML = `
      <td class="p-2">${host}</td>
      <td class="p-2">${server.video_path}</td>
      <td class="p-2">${estadoHTML}</td>
      <td class="p-2 space-x-2">${accionesHTML}</td>
    `;

    table.appendChild(row);
  });
}


// Iniciar servidor de video
async function startVideoServer() {
  const hostSelect = document.getElementById('host-select');
  const selectedHosts = Array.from(hostSelect.selectedOptions).map(opt => opt.value);
  const videoPath = document.getElementById('video-path').value;
  
  if (selectedHosts.length === 0 || !videoPath) {
    alert('Por favor selecciona al menos un host y especifica la ruta del video');
    return;
  }
  
  const startBtn = document.querySelector('[onclick="startVideoServer()"]');
  const originalText = startBtn.textContent;
  startBtn.disabled = true;
  startBtn.textContent = 'Iniciando...';
  
  let successCount = 0;
  let errorMessages = [];
  
  for (const host of selectedHosts) {
    try {
      // 1. Asignar como servidor
      const assignResponse = await fetch(`${API_BASE_URL}/servers/hosts/asignar-servidor`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nombres: [host]
        })
      });
      
      if (!assignResponse.ok) {
        const errorData = await assignResponse.json().catch(() => ({}));
        throw new Error(errorData.error || `Error HTTP ${assignResponse.status}`);
      }
      
      // 2. Iniciar video
      const videoResponse = await fetch(`${API_BASE_URL}/servers/start_video`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          host: host,
          video_path: videoPath
        })
      });
      
      // Manejar respuesta no JSON
      let result;
      try {
        result = await videoResponse.json();
      } catch (e) {
        const textResponse = await videoResponse.text();
        throw new Error(`Respuesta no es JSON: ${textResponse.substring(0, 100)}...`);
      }
      
      if (!videoResponse.ok) {
        throw new Error(result.error || `Error ${videoResponse.status}`);
      }
      
      console.log(`Servidor iniciado en ${host}:`, result);
      successCount++;
      
    } catch (error) {
      console.error(`Error en host ${host}:`, error);
      errorMessages.push(`• ${host}: ${error.message}`);
      
      // Intentar desactivar el host si falló
      try {
        await fetch(`${API_BASE_URL}/servers/active_servers/${host}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            activo: false
          })
        });
      } catch (dbError) {
        console.error(`Error al limpiar estado de ${host}:`, dbError);
      }
    }
  }
  
  // Mostrar resultados
  if (errorMessages.length > 0) {
    alert(`${successCount} servidores iniciados correctamente.\n\nErrores:\n${errorMessages.join('\n')}`);
  } else {
    alert(`Todos los servidores (${successCount}) iniciados correctamente`);
  }
  
  // Restaurar UI
  startBtn.disabled = false;
  startBtn.textContent = originalText;
  fetchActiveServers();
  fetchHosts();
}
// Detener servidor de video
async function stopVideoServer(host) {
  if (!confirm(`¿Detener el servidor en ${host}?`)) return;

  try {
    // 1. Desactivar el servidor en la base de datos
    const response = await fetch(`${API_BASE_URL}/servers/active_servers/${host}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activo: false })
    });

    if (!response.ok) {
      throw new Error('Error al desactivar el servidor en la base de datos');
    }

    // 2. Enviar petición para detener el video en el agente Mininet
    const stopResponse = await fetch(`${API_BASE_URL}/servers/active_servers/${host}`, {
      method: 'DELETE'
    });

    if (!stopResponse.ok) {
      // Leer mensaje de error si está disponible
      const errorData = await stopResponse.json().catch(() => ({}));
      throw new Error(errorData.error || 'Error al detener el video en el agente Mininet');
    }

    // 3. Actualizar UI llamando a funciones que recargan estados
    fetchActiveServers();
    fetchHosts();

    alert('Servidor detenido correctamente');
  } catch (error) {
    console.error('Error stopping server:', error);
    alert('Error al detener el servidor: ' + error.message);
  }
}


// Mostrar modal para cambiar video
function showChangeVideoModal(host) {
  currentHostForChange = host;
  document.getElementById('change-video-modal').classList.remove('hidden');
}

// Cerrar modal
function closeModal() {
  document.getElementById('change-video-modal').classList.add('hidden');
  currentHostForChange = null;
}

// Confirmar cambio de video
async function confirmVideoChange() {
  const newVideoPath = document.getElementById('new-video-path').value;
  
  if (!newVideoPath) {
    alert('Por favor ingresa una nueva ruta de video');
    return;
  }
  
  try {
    // Usar el mismo endpoint de inicio con la nueva ruta
    const response = await fetch(`${API_BASE_URL}/servers/start_video`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        host: currentHostForChange,
        video_path: newVideoPath
      })
    });
    
    if (!response.ok) {
      throw new Error('Error al cambiar el video');
    }
    
    closeModal();
    fetchActiveServers();
    alert('Video cambiado correctamente');
  } catch (error) {
    console.error('Error changing video:', error);
    alert('Error al cambiar el video: ' + error.message);
  }
}



async function startVideoFromUI(host) {
  const videoPath = prompt(`Ingresa la ruta del video para ${host}:`, "sample.mp4");
  if (!videoPath) return;

  try {
    const assignResponse = await fetch(`${API_BASE_URL}/servers/hosts/asignar-servidor`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombres: [host] })
    });

    if (!assignResponse.ok) throw new Error("Error al marcar como servidor");

    const response = await fetch(`${API_BASE_URL}/servers/start_video`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, video_path: videoPath })
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Error al iniciar servidor");
    }

    alert(`Servidor iniciado en ${host}`);
    fetchActiveServers();
    fetchHosts();

  } catch (error) {
    console.error('Error iniciando servidor:', error);
    alert('Error: ' + error.message);
  }
}

async function removeAsServer(host) {
  if (!confirm(`¿Eliminar el rol de servidor en ${host}?`)) return;

  try {
    const response = await fetch(`${API_BASE_URL}/servers/hosts/remover-servidor/${host}`, {
      method: 'PUT'
    });

    if (!response.ok) {
      throw new Error('Error al eliminar el rol de servidor');
    }

    alert(`Servidor ${host} eliminado correctamente del rol`);
    fetchActiveServers();
    fetchHosts();
  } catch (error) {
    console.error('Error eliminando rol de servidor:', error);
    alert('Error: ' + error.message);
  }
}

