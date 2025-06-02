let currentHostForChange = null;

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

async function lanzarServidor({ hostName, videoPath, peso = 1 }) {
  try {
    const response = await fetch(`${API_BASE_URL}/servers/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host_name: hostName,
        video_path: videoPath,
        server_weight: peso
      })
    });

    const data = await response.json();

    if (response.ok) {
      showMessageModal('Éxito', `Servidor ${hostName} activado. IP Multicast: ${data.multicast_ip}:${data.multicast_port}`);
      loadActiveServers?.();
      updateDashboard?.();
      cerrarModal?.(); // ✅ CIERRA el modal si existe
      return { success: true, message: data.message };
    } else {
      showMessageModal('Error', `Error al activar servidor: ${data.error}`);
      return { success: false, message: data.error };
    }
  } catch (error) {
    console.error('Error lanzando servidor:', error);
    showMessageModal('Error', 'Error de conexión al activar el servidor.');
    return { success: false, message: 'Error de conexión con el servidor.' };
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

  const result = await lanzarServidor({ hostName, videoPath, peso: serverWeight });

  if (result.success) {
    statusMessage.textContent = result.message;
    statusMessage.className = 'mt-2 text-sm text-green-600';
    document.getElementById('server-host-name').value = '';
    document.getElementById('server-video-path').value = '';
    document.getElementById('server-weight').value = '1';
  } else {
    statusMessage.textContent = result.message;
    statusMessage.className = 'mt-2 text-sm text-red-600';
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

// --- servers.js ---

const VIDEO_OPTIONS = [
  { name: "Big Buck Bunny", path: "videos/conejo.mp4", thumbnail: "/static/thumbnails/conejo.jpg" },
  { name: "Fox & Bird", path: "videos/fox_bird.mp4", thumbnail: "/static/thumbnails/fox_bird.jpg" },
  { name: "Spring", path: "videos/spring.mp4", thumbnail: "/static/thumbnails/spring.jpg" },
  { name: "Charge", path: "videos/charge.mp4", thumbnail: "/static/thumbnails/charge.jpg" }
];

let algoritmoBalanceoActual = null;
window.servidoresActivos = [];
let selectedVideoPath = null;

async function verificarAlgoritmoBalanceo() {
  try {
    const res = await fetch(`${API_BASE_URL}/config/current`);
    const data = await res.json();
    algoritmoBalanceoActual = data.algoritmo_balanceo;

    const pesoGroup = document.getElementById('modal-server-weight-group');
    if (pesoGroup) {
      pesoGroup.classList.toggle('hidden', algoritmoBalanceoActual !== 'weighted_round_robin');
    }
  } catch (err) {
    console.error("Error al verificar algoritmo:", err);
  }
}

function abrirModalSeleccionVideo() {
  const overlay = document.getElementById('modal-selector-servidor-overlay');
  const content = document.getElementById('modal-selector-servidor');
  const gallery = document.getElementById('modal-video-gallery');
  const launchBtn = document.getElementById('btn-modal-launch-server');
  overlay.classList.add('show');


  //document.body.classList.add('overflow-hidden');
  selectedVideoPath = null;
  gallery.innerHTML = '';
  launchBtn.disabled = true;
  launchBtn.classList.add('opacity-50', 'cursor-not-allowed');

  VIDEO_OPTIONS.forEach(video => {
    const div = document.createElement('div');
    div.className = 'cursor-pointer border rounded-lg p-2 hover:shadow bg-white transition';
    div.innerHTML = `
      <img src="${video.thumbnail}" alt="${video.name}" class="w-full h-24 object-cover rounded mb-1">
      <p class="text-sm text-center font-semibold text-gray-800">${video.name}</p>
    `;
    div.addEventListener('click', () => {
      selectedVideoPath = video.path;
      document.querySelectorAll('#modal-video-gallery div').forEach(el => el.classList.remove('ring-2', 'ring-blue-500'));
      div.classList.add('ring-2', 'ring-blue-500');
      launchBtn.disabled = false;
      launchBtn.classList.remove('opacity-50', 'cursor-not-allowed');
    });
    gallery.appendChild(div);
  });

  verificarAlgoritmoBalanceo();
  setTimeout(() => {
    content.classList.remove('opacity-0', 'scale-95');
    content.classList.add('opacity-100', 'scale-100');
  }, 10);
}

function cerrarModal() {
  const overlay = document.getElementById('modal-selector-servidor-overlay');
  const content = document.getElementById('modal-selector-servidor');
  const launchBtn = document.getElementById('btn-modal-launch-server');
  overlay.classList.remove('show');
  content.classList.remove('opacity-100', 'scale-100');
  content.classList.add('opacity-0', 'scale-95');

  setTimeout(() => {
    overlay.classList.add('hidden');
    selectedVideoPath = null;
    if (launchBtn) {
      launchBtn.disabled = true;
      launchBtn.classList.add('opacity-50', 'cursor-not-allowed');
    }
  }, 200);
}

async function iniciarServidorDesdeModal() {
  if (selectedHosts.length !== 1) {
    showMessageModal('Error', 'Debes seleccionar un host desde la topología.');
    return;
  }

  if (!selectedVideoPath) {
    showMessageModal('Error', 'Debes seleccionar un video antes de iniciar el servidor.');
    return;
  }

  const host = selectedHosts[0];
  const peso = (algoritmoBalanceoActual === 'weighted_round_robin')
    ? parseInt(document.getElementById('modal-server-weight').value) || 1
    : 1;

  await lanzarServidor({ hostName: host.name, videoPath: selectedVideoPath, peso });
}


document.getElementById('btn-iniciar-servidor')?.addEventListener('click', () => {
  if (selectedHosts.length !== 1) {
    showMessageModal('Error', 'Selecciona un host desde la topología.');
    return;
  }
  abrirModalSeleccionVideo();
});

document.getElementById('btn-modal-launch-server')?.addEventListener('click', iniciarServidorDesdeModal);
document.getElementById('btn-modal-cancel-server')?.addEventListener('click', cerrarModal);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') cerrarModal();
});

document.getElementById('modal-selector-servidor-overlay')?.addEventListener('click', (e) => {
  const modalContent = document.getElementById('modal-selector-servidor');
  if (!modalContent.contains(e.target)) cerrarModal();
});


document.addEventListener('DOMContentLoaded', () => {
  // 1. Carga inicial de datos
  loadActiveServers();
  verificarAlgoritmoBalanceo();

  // 2. Listeners de botones
  document.getElementById('btn-iniciar-servidor')?.addEventListener('click', () => {
    abrirModalSeleccionVideo();
  });

  document.getElementById('btn-modal-launch-server')?.addEventListener('click', async () => {
    await iniciarServidorDesdeModal();
  });

  document.getElementById('btn-iniciar-cliente')?.addEventListener('click', async () => {
    if (!selectedHosts || selectedHosts.length !== 1) {
      showMessageModal('Error', 'Selecciona un único host desde la topología.');
      return;
    }

    const host = selectedHosts[0];

    if (window.activeFFplayClients?.some(client => client.host === host.name)) {
      showMessageModal('Advertencia', `El host ${host.name} ya tiene un cliente FFplay activo.`);
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/client/get_multicast_stream_info`);
      const data = await response.json();

      if (response.ok && data.host_name && data.multicast_ip && data.multicast_port) {
        const streamInfo = {
          serverName: data.host_name,
          multicastIp: data.multicast_ip,
          multicastPort: data.multicast_port
        };
        await startFFmpegClient(host.name, streamInfo);
      } else {
        showMessageModal("Error", "No se pudo obtener información completa del servidor.");
        console.error("❌ Datos incompletos del backend:", data);
      }
    } catch (error) {
      console.error('Error solicitando información del stream:', error);
      showMessageModal('Error', 'Error de conexión al solicitar información del stream.');
    }
  });

  // 3. Cierre de modal con Escape o clic fuera
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') cerrarModal();
  });

  document.getElementById('modal-selector-servidor-overlay')?.addEventListener('click', (e) => {
    const modalContent = document.getElementById('modal-selector-servidor');
    if (!modalContent.contains(e.target)) cerrarModal();
  });

  // 4. Actualización continua del estado de botones
  setInterval(() => {
    const btnPing = document.getElementById('btn-ping');
    const btnSrv = document.getElementById('btn-iniciar-servidor');
    const btnCli = document.getElementById('btn-iniciar-cliente');

    if (!btnPing || !btnSrv || !btnCli || typeof selectedHosts === 'undefined') return;

    // Habilitar solo si hay 2 hosts seleccionados
    btnPing.disabled = selectedHosts.length !== 2;

    // Habilitar servidor/cliente solo si hay 1 host seleccionado
    const unHost = selectedHosts.length === 1;
    btnSrv.disabled = !unHost;
    btnCli.disabled = !unHost;
  }, 500);


  // 5. Refresco automático de lista de servidores
  setInterval(() => {
    loadActiveServers();
  }, 10000);
});
