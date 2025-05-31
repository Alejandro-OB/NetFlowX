// --- index.js ---
// Funciones que NO tienen que ver con la topología (dashboard, config, link management, stats, logs, etc.)

// ==============================
//  Constantes Globales
// ==============================
const API_BASE_URL      = 'http://192.168.18.151:5000';
const MININET_AGENT_URL = 'http://192.168.18.208:5002';

// ==============================
//  Función auxiliar para mostrar modales
//  (Se reutiliza la misma de topology.js si ambos archivos están cargados.)
// ==============================
function showMessageModal(title, message, isConfirm = false, onConfirm = null) {
  // Reutilizamos la misma implementación que en topology.js
  const modal       = document.getElementById('message-modal');
  const titleElem   = document.getElementById('message-modal-title');
  const contentElem = document.getElementById('message-modal-content');
  const confirmBtn  = document.getElementById('message-modal-confirm-btn');
  const cancelBtn   = document.getElementById('message-modal-cancel-btn');

  if (!modal || !titleElem || !contentElem || !confirmBtn || !cancelBtn) {
    console.warn('showMessageModal: No se encontraron elementos del modal en el DOM.');
    alert(`${title}\n\n${message}`);
    if (isConfirm && onConfirm) onConfirm();
    return;
  }

  titleElem.textContent   = title;
  contentElem.textContent = message;
  confirmBtn.onclick = null;
  cancelBtn.onclick  = null;

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

// =======================================
//  DASHBOARD: obtener datos y mostrarlos
// =======================================
async function updateDashboard() {
  try {
    // 1) Obtener cantidad de servidores activos
    const srvRes = await fetch(`${API_BASE_URL}/servers/active_servers`);
    if (!srvRes.ok) {
      const err = await srvRes.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${srvRes.status}: ${err.message || srvRes.statusText}`);
    }
    const srvData = await srvRes.json();
    document.getElementById('active-servers-count').textContent = srvData.length;

    // 2) Obtener algoritmo de balanceo y enrutamiento actual
    const cfgRes = await fetch(`${API_BASE_URL}/config/current`);
    if (!cfgRes.ok) {
      const err = await cfgRes.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${cfgRes.status}: ${err.message || cfgRes.statusText}`);
    }
    const cfgData = await cfgRes.json();
    document.getElementById('current-lb-algo').textContent      = cfgData.algoritmo_balanceo      || 'Not configured';
    document.getElementById('current-routing-algo').textContent = cfgData.algoritmo_enrutamiento || 'Not configured';

    // Mostrar/ocultar input de peso para WRR
    const weightGroup = document.getElementById('server-weight-input-group');
    if (weightGroup) {
      if (cfgData.algoritmo_balanceo === 'weighted_round_robin') {
        weightGroup.classList.remove('hidden');
      } else {
        weightGroup.classList.add('hidden');
      }
    }

    // 3) Actualizar estado del controlador (conexión con switches)
    await updateControllerStatus();

  } catch (err) {
    console.error('Error updateDashboard():', err);
    showMessageModal('Error', `No se pudo actualizar el dashboard: ${err.message}`);
  }
}

async function updateControllerStatus() {
  const statusElem = document.getElementById('controller-status');
  if (!statusElem) return;

  try {
    const topoRes = await fetch(`${API_BASE_URL}/topology/get`);
    if (!topoRes.ok) {
      const err = await topoRes.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${topoRes.status}: ${err.message || topoRes.statusText}`);
    }
    const topoData = await topoRes.json();
    const switches = Array.isArray(topoData.switches) ? topoData.switches : [];
    const connected = switches.some(s => s.status === 'conectado');

    statusElem.textContent = connected ? 'Conectado' : 'Desconectado';
    statusElem.className   = connected ? 'text-green-700' : 'text-red-700';

  } catch (err) {
    console.error('Error updateControllerStatus():', err);
    statusElem.textContent = 'Error de Conexión';
    statusElem.className   = 'text-red-700';
  }
}

// =======================================
//  Cargar historial de configuración
// =======================================
async function loadConfigHistory() {
  try {
    const res = await fetch(`${API_BASE_URL}/config/history`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${res.status}: ${err.message || res.statusText}`);
    }
    const historyData = await res.json();
    const histDiv = document.getElementById('config-history');
    if (!histDiv) return;
    histDiv.innerHTML = '';

    if (Array.isArray(historyData) && historyData.length > 0) {
      historyData.forEach(item => {
        const p = document.createElement('p');
        p.textContent = `Balanceo: ${item.algoritmo_balanceo || 'N/A'}, ` +
                        `Enrutamiento: ${item.algoritmo_enrutamiento || 'N/A'} ` +
                        `(Activado: ${new Date(item.fecha_activacion).toLocaleString()})`;
        histDiv.appendChild(p);
      });
    } else {
      histDiv.textContent = 'No hay historial de configuración.';
    }

  } catch (err) {
    console.error('Error loadConfigHistory():', err);
    showMessageModal('Error', `No se pudo cargar el historial de configuración: ${err.message}`);
  }
}

// =========================================
//  Guardar algoritmo de balanceo (POST)
// =========================================
document.getElementById('save-lb-algo')?.addEventListener('click', async () => {
  const algo = document.getElementById('lb-algo-select')?.value;
  const statusMsg = document.getElementById('lb-status-message');
  if (!algo) {
    statusMsg.textContent = 'Por favor selecciona un algoritmo.';
    statusMsg.className = 'mt-2 text-sm text-red-600';
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/config/balanceo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ algoritmo_balanceo: algo })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.message || 'Unknown error');

    statusMsg.textContent = data.message || 'Guardado exitosamente.';
    statusMsg.className   = 'mt-2 text-sm text-green-600';
    showMessageModal('Éxito', 'Algoritmo de balanceo guardado correctamente.');
    updateDashboard();
    loadConfigHistory();

  } catch (err) {
    console.error('Error al guardar LB:', err);
    statusMsg.textContent = err.message;
    statusMsg.className   = 'mt-2 text-sm text-red-600';
    showMessageModal('Error', `No se pudo guardar el algoritmo de balanceo: ${err.message}`);
  }
});

// =========================================
//  Guardar algoritmo de enrutamiento (POST)
// =========================================
document.getElementById('save-routing-algo')?.addEventListener('click', async () => {
  const algo = document.getElementById('routing-algo-select')?.value;
  const statusMsg = document.getElementById('routing-status-message');
  if (!algo) {
    statusMsg.textContent = 'Por favor selecciona un algoritmo de enrutamiento.';
    statusMsg.className = 'mt-2 text-sm text-red-600';
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/config/enrutamiento`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ algoritmo_enrutamiento: algo })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.message || 'Unknown error');

    statusMsg.textContent = data.message || 'Guardado exitosamente.';
    statusMsg.className   = 'mt-2 text-sm text-green-600';
    showMessageModal('Éxito', 'Algoritmo de enrutamiento guardado correctamente.');
    updateDashboard();
    loadConfigHistory();

  } catch (err) {
    console.error('Error al guardar Routing:', err);
    statusMsg.textContent = err.message;
    statusMsg.className   = 'mt-2 text-sm text-red-600';
    showMessageModal('Error', `No se pudo guardar el algoritmo de enrutamiento: ${err.message}`);
  }
});

// =======================================
//  Función auxiliar para color de enlace
//  (Repetida aquí solo si la necesitas
//   en secciones que no importen topology.js)
// =======================================
function colorPorAnchoBandaGlobal(bw) {
  if (bw >= 1000) return 'green';
  if (bw >= 100)  return 'yellow';
  if (bw >= 10)   return 'orange';
  return 'red';
}

// =======================================
//  Gestión de SWITCHES para formularios de enlaces
// =======================================
let allSwitches = [];

async function loadSwitchesForLinks() {
  try {
    const res = await fetch(`${API_BASE_URL}/topology/get`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${res.status}: ${err.message || res.statusText}`);
    }
    const topoData = await res.json();
    allSwitches = Array.isArray(topoData.switches) ? topoData.switches : [];
    populateLinkDropdowns(allSwitches);

  } catch (err) {
    console.error('Error loadSwitchesForLinks():', err);
    showMessageModal('Error', `No se pudieron cargar los switches para enlaces: ${err.message}`);
  }
}

function populateLinkDropdowns(switches) {
  const origenSelect  = document.getElementById('new-link-origen');
  const destinoSelect = document.getElementById('new-link-destino');
  if (!origenSelect || !destinoSelect) return;

  [origenSelect, destinoSelect].forEach(sel => {
    sel.innerHTML = `<option value="">Seleccionar</option>`;
    switches.forEach(sw => {
      const opt = document.createElement('option');
      opt.value = sw.id_switch;
      opt.textContent = sw.nombre;
      sel.appendChild(opt);
    });
  });
}

// =======================================
//  Cargar enlaces activos en tabla
// =======================================
async function loadActiveLinks() {
  try {
    const res = await fetch(`${API_BASE_URL}/topology/get`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${res.status}: ${err.message || res.statusText}`);
    }
    const topoData = await res.json();
    const enlaces = Array.isArray(topoData.enlaces) ? topoData.enlaces : [];
    const tblBody = document.getElementById('active-links-list');
    if (!tblBody) return;
    tblBody.innerHTML = '';

    if (enlaces.length === 0) {
      tblBody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center py-4 text-gray-500">
            No hay enlaces activos.
          </td>
        </tr>`;
      return;
    }

    enlaces.forEach(link => {
      const swOrigen = topoData.switches.find(sw => sw.id_switch === link.id_origen);
      const swDest   = topoData.switches.find(sw => sw.id_switch === link.id_destino);
      if (swOrigen && swDest) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="py-2 px-4 border-b border-gray-200">${swOrigen.nombre}</td>
          <td class="py-2 px-4 border-b border-gray-200">${swDest.nombre}</td>
          <td class="py-2 px-4 border-b border-gray-200">${link.ancho_banda}</td>
          <td class="py-2 px-4 border-b border-gray-200">
            <button class="px-3 py-1 bg-yellow-500 text-white rounded-md hover:bg-yellow-600 text-sm edit-link-btn"
              data-origen-id="${link.id_origen}"
              data-destino-id="${link.id_destino}"
              data-bw="${link.ancho_banda}"
              data-origen-name="${swOrigen.nombre}"
              data-destino-name="${swDest.nombre}">
              Editar
            </button>
            <button class="ml-2 px-3 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm delete-link-btn"
              data-origen-id="${link.id_origen}"
              data-destino-id="${link.id_destino}"
              data-origen-name="${swOrigen.nombre}"
              data-destino-name="${swDest.nombre}">
              Eliminar
            </button>
          </td>`;
        tblBody.appendChild(tr);
      }
    });

    // Agregar listeners a botones “Editar” y “Eliminar”
    document.querySelectorAll('.edit-link-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const oId = e.target.dataset.origenId;
        const dId = e.target.dataset.destinoId;
        const bw  = e.target.dataset.bw;
        const oName = e.target.dataset.origenName;
        const dName = e.target.dataset.destinoName;
        openEditLinkModal(oId, dId, bw, oName, dName);
      });
    });
    document.querySelectorAll('.delete-link-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const oId = e.target.dataset.origenId;
        const dId = e.target.dataset.destinoId;
        const oName = e.target.dataset.origenName;
        const dName = e.target.dataset.destinoName;
        deleteLink(oId, dId, oName, dName);
      });
    });

  } catch (err) {
    console.error('Error loadActiveLinks():', err);
    const tblBody = document.getElementById('active-links-list');
    if (tblBody) {
      tblBody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center py-4 text-red-500">
            Error al cargar enlaces activos.
          </td>
        </tr>`;
    }
    showMessageModal('Error', `No se pudieron cargar los enlaces activos: ${err.message}`);
  }
}

// =========================================
//  Crear un nuevo enlace (POST)
// =========================================
document.getElementById('create-link-btn')?.addEventListener('click', async () => {
  const origenId = document.getElementById('new-link-origen')?.value;
  const destinoId = document.getElementById('new-link-destino')?.value;
  const bw = document.getElementById('new-link-bw')?.value;
  const statusMsg = document.getElementById('create-link-status-message');

  if (!origenId || !destinoId || !bw) {
    statusMsg.textContent = 'Por favor completa todos los campos.';
    statusMsg.className = 'mt-2 text-sm text-red-600';
    return;
  }
  if (origenId === destinoId) {
    statusMsg.textContent = 'El origen y destino no pueden ser el mismo switch.';
    statusMsg.className = 'mt-2 text-sm text-red-600';
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/topology/enlace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id_origen:  parseInt(origenId, 10),
        id_destino: parseInt(destinoId, 10),
        ancho_banda: parseInt(bw, 10)
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.message || 'Unknown error');

    statusMsg.textContent = data.message || 'Enlace creado exitosamente.';
    statusMsg.className   = 'mt-2 text-sm text-green-600';
    showMessageModal('Éxito', data.message || 'Enlace creado exitosamente.');

    // Refrescar topología y lista de enlaces
    loadTopology();
    loadActiveLinks();

    // Limpiar formularios
    document.getElementById('new-link-origen').value  = '';
    document.getElementById('new-link-destino').value = '';
    document.getElementById('new-link-bw').value       = '';

  } catch (err) {
    console.error('Error create-link:', err);
    statusMsg.textContent = err.message;
    statusMsg.className   = 'mt-2 text-sm text-red-600';
    showMessageModal('Error', `No se pudo crear el enlace: ${err.message}`);
  }
});

// =========================================
//  Eliminar un enlace (DELETE)
// =========================================
async function deleteLink(origenId, destinoId, origenName, destinoName) {
  showMessageModal(
    'Confirmar Eliminación',
    `¿Seguro que deseas eliminar el enlace entre ${origenName} y ${destinoName}?`,
    true,
    async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/topology/enlace`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id_origen: parseInt(origenId, 10),
            id_destino: parseInt(destinoId, 10)
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || data.message || 'Unknown error');

        showMessageModal('Éxito', data.message || 'Enlace eliminado exitosamente.');
        loadTopology();
        loadActiveLinks();

      } catch (err) {
        console.error('Error deleteLink():', err);
        showMessageModal('Error', `No se pudo eliminar el enlace: ${err.message}`);
      }
    }
  );
}

// =========================================
//  Abrir modal para editar un enlace
// =========================================
function openEditLinkModal(origenId, destinoId, bw, origenName, destinoName) {
  document.getElementById('edit-link-origen-display').value  = origenName;
  document.getElementById('edit-link-destino-display').value = destinoName;
  document.getElementById('edit-link-bw-input').value       = bw;
  document.getElementById('edit-link-origen-id').value      = origenId;
  document.getElementById('edit-link-destino-id').value     = destinoId;
  document.getElementById('edit-link-modal').classList.remove('hidden');
}

// Cerrar modal de edición
document.getElementById('cancel-edit-link-btn')?.addEventListener('click', () => {
  document.getElementById('edit-link-modal')?.classList.add('hidden');
});

// =========================================
//  Guardar cambios de enlace (PUT)
// =========================================
document.getElementById('save-edited-link-btn')?.addEventListener('click', async () => {
  const origenId  = document.getElementById('edit-link-origen-id')?.value;
  const destinoId = document.getElementById('edit-link-destino-id')?.value;
  const newBw     = document.getElementById('edit-link-bw-input')?.value;

  if (!newBw || isNaN(newBw) || parseInt(newBw, 10) <= 0) {
    showMessageModal('Advertencia', 'El ancho de banda debe ser un número positivo.');
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/topology/enlace`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id_origen:  parseInt(origenId, 10),
        id_destino: parseInt(destinoId, 10),
        ancho_banda: parseInt(newBw, 10)
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.message || 'Unknown error');

    showMessageModal('Éxito', data.message || 'Enlace actualizado exitosamente.');
    document.getElementById('edit-link-modal')?.classList.add('hidden');
    loadTopology();
    loadActiveLinks();

  } catch (err) {
    console.error('Error save-edited-link:', err);
    showMessageModal('Error', `No se pudo actualizar el enlace: ${err.message}`);
  }
});

// =======================================
//  ESTADÍSTICAS: cargar y mostrar datos
// =======================================
async function cargarEstadisticas() {
  try {
    const res = await fetch(`${API_BASE_URL}/stats/resumen`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${res.status}: ${err.message || res.statusText}`);
    }
    const data = await res.json();
    const tbody = document.getElementById('tabla-estadisticas');
    if (!tbody) return;
    tbody.innerHTML = '';

    data.forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="p-2">${row.tipo}</td>
        <td class="p-2">${row.total}</td>`;
      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error('Error cargarEstadisticas():', err);
    // showMessageModal('Error', `No se pudieron cargar las estadísticas: ${err.message}`);
  }
}

// =======================================
//  LOGS: cargar y mostrar datos
// =======================================
async function cargarLogs() {
  try {
    const res = await fetch(`${API_BASE_URL}/stats/logs`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${res.status}: ${err.message || res.statusText}`);
    }
    const data = await res.json();
    const list = document.getElementById('lista-logs');
    if (!list) return;
    list.innerHTML = '';

    data.forEach(log => {
      const li = document.createElement('li');
      li.innerHTML = `<span class="font-semibold text-blue-600">${log.origen}</span> - ${log.tipo_evento} - ${log.fecha}`;
      list.appendChild(li);
    });

  } catch (err) {
    console.error('Error cargarLogs():', err);
    // showMessageModal('Error', `No se pudieron cargar los logs: ${err.message}`);
  }
}

// =======================================
//  Inicialización general al cargar la página
// =======================================
document.addEventListener('DOMContentLoaded', () => {
  // 1) Topología (se cargará automáticamente en topology.js)
  //    No es necesario llamarla aquí, pues topology.js ya lo hace en su DOMContentLoaded.

  // 2) DASHBOARD
  updateDashboard();
  setInterval(updateDashboard, 5000);

  // 3) Historial de configuración
  loadConfigHistory();

  // 4) Gestión de enlaces
  loadSwitchesForLinks();
  loadActiveLinks();
  setInterval(loadActiveLinks, 10000);

  // 5) Estadísticas y Logs (si tienes secciones en tu HTML para ellos)
  cargarEstadisticas();
  cargarLogs();
});
