document.getElementById('menu-btn').addEventListener('click', () => {
  const nav = document.querySelector('nav');
  nav.classList.toggle('hidden');
});

const map = L.map('mapa-topologia').setView([54.5, 15.3], 4);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a> contributors'
}).addTo(map);

// --- Funciones para el Modal de Mensajes (reemplazando alert y confirm) ---
let resolveModalPromise;

/**
 * Muestra un modal de mensaje con un contenido dado.
 * @param {string} message - El mensaje a mostrar.
 * @param {boolean} isConfirm - Si es un modal de confirmación (true) o solo informativo (false).
 * @returns {Promise<boolean>} - Resuelve a true si se confirma, false si se cierra/cancela.
 */
function showMessageModal(message, isConfirm = false) {
  const modal = document.getElementById('message-modal');
  const modalTitle = document.getElementById('message-modal-title');
  const modalContent = document.getElementById('message-modal-content');
  const confirmBtn = document.getElementById('message-modal-confirm-btn');
  const closeBtn = document.getElementById('message-modal-close-btn');

  modalContent.textContent = message;
  modalTitle.textContent = isConfirm ? 'Confirmación' : 'Mensaje';

  if (isConfirm) {
    confirmBtn.classList.remove('hidden');
    closeBtn.textContent = 'Cancelar';
  } else {
    confirmBtn.classList.add('hidden');
    closeBtn.textContent = 'Cerrar';
  }

  modal.classList.remove('hidden');
  modal.classList.add('flex'); // Asegura que se muestre como flex

  return new Promise(resolve => {
    resolveModalPromise = resolve;

    confirmBtn.onclick = () => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      resolveModalPromise(true);
    };

    closeBtn.onclick = () => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      resolveModalPromise(false);
    };
  });
}

// --- Funciones existentes, actualizadas para usar el modal ---

async function cargarEstadisticas() {
  try {
    const res = await fetch('http://localhost:5000/stats/resumen');
    const data = await res.json();
    const tbody = document.getElementById('tabla-estadisticas');
    tbody.innerHTML = '';

    data.forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="p-2">${row.tipo}</td><td class="p-2">${row.total}</td>`;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Error al cargar estadísticas:', err);
    showMessageModal('Error al cargar estadísticas: ' + err.message);
  }
}

async function cargarLogs() {
  try {
    const res = await fetch('http://localhost:5000/stats/logs');
    const data = await res.json();
    const lista = document.getElementById('lista-logs');
    lista.innerHTML = '';

    data.forEach(log => {
      const li = document.createElement('li');
      li.innerHTML = `<span class="font-semibold text-blue-600">${log.origen}</span> - ${log.tipo_evento} - ${log.fecha}`;
      lista.appendChild(li);
    });
  } catch (err) {
    console.error('Error al cargar logs:', err);
    showMessageModal('Error al cargar logs: ' + err.message);
  }
}

let switchesGlobal = [];

async function cargarTopologia() {
  try {
    const res = await fetch('http://localhost:5000/topology');
    const data = await res.json();
    switchesGlobal = data.switches;

    map.eachLayer(layer => {
      if (layer instanceof L.Marker || layer instanceof L.Polyline) {
        map.removeLayer(layer);
      }
    });

    data.switches.forEach(sw => {
      L.marker([sw.latitud, sw.longitud])
        .addTo(map)
        .bindPopup(`<strong>s${sw.id}</strong>`); // Mostrar id con s
    });

    data.enlaces.forEach(enlace => {
      const origen = data.switches.find(sw => sw.nombre === enlace.origen);
      const destino = data.switches.find(sw => sw.nombre === enlace.destino);

      if (origen && destino) {
        L.polyline(
          [[origen.latitud, origen.longitud], [destino.latitud, destino.longitud]],
          { color: colorPorAnchoBanda(enlace.ancho_banda), weight: 4 }
        ).addTo(map);
      }
    });

    poblarSelects(data.switches);

    const tabla = document.getElementById("tabla-enlaces");
    tabla.innerHTML = "";
    data.enlaces.forEach(enlace => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="p-2">${enlace.origen}</td>
        <td class="p-2">${enlace.destino}</td>
        <td class="p-2">${enlace.ancho_banda}</td>
        <td class="p-2">
          <button class="bg-red-500 hover:bg-red-600 text-white px-3 py-1 rounded text-xs"
            onclick="eliminarEnlace('${enlace.origen}', '${enlace.destino}')">
            Eliminar
          </button>
        </td>
      `;
      tabla.appendChild(tr);
    });

  } catch (err) {
    console.error('Error al cargar topología:', err);
    showMessageModal('Error al cargar topología: ' + err.message);
  }
}

function colorPorAnchoBanda(bw) {
  if (bw >= 1000) return 'green'; // Muy alto
  if (bw >= 100) return 'yellow';
  if (bw >= 10) return 'orange';
  return 'red'; // Bajo
}

function poblarSelects(lista) {
  const origen = document.getElementById("select-origen");
  const destino = document.getElementById("select-destino");

  origen.innerHTML = `<option disabled selected>Switch origen</option>`;
  destino.innerHTML = `<option disabled selected>Switch destino</option>`;

  lista.forEach(sw => {
    const opt1 = document.createElement("option");
    opt1.value = sw.id;
    opt1.textContent = sw.nombre;

    const opt2 = opt1.cloneNode(true);
    origen.appendChild(opt1);
    destino.appendChild(opt2);
  });
}

async function crearEnlace() {
  const origen = document.getElementById("select-origen").value;
  const destino = document.getElementById("select-destino").value;
  const bw = document.getElementById("input-bw").value;

  if (!origen || !destino || !bw) {
    return showMessageModal("Completa todos los campos");
  }

  try {
    const res = await fetch("http://localhost:5000/topology/enlace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id_origen: parseInt(origen),
        id_destino: parseInt(destino),
        ancho_banda: parseInt(bw)
      })
    });

    const data = await res.json();
    showMessageModal(data.message || "Enlace creado");
    cargarTopologia();
  } catch (err) {
    console.error('Error al crear enlace:', err);
    showMessageModal('Error al crear enlace: ' + err.message);
  }
}

async function eliminarEnlace(origen, destino) {
  const confirmed = await showMessageModal(`¿Eliminar el enlace entre ${origen} y ${destino}?`, true);
  if (!confirmed) return;

  try {
    const res = await fetch("http://localhost:5000/topology/enlace", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origen, destino })
    });

    const data = await res.json();
    showMessageModal(data.message || "Enlace eliminado");
    cargarTopologia();
  } catch (err) {
    console.error('Error al eliminar enlace:', err);
    showMessageModal('Error al eliminar enlace: ' + err.message);
  }
}

// --- Nuevas funciones para guardar configuración ---

/**
 * Guarda el algoritmo de balanceo de carga seleccionado en la base de datos.
 */
async function saveLoadBalancingAlgorithm() {
  const selectElement = document.getElementById('load-balancing-algo');
  const selectedAlgorithm = selectElement.value;

  console.log('Guardando Algoritmo de Balanceo de Carga:', selectedAlgorithm);

  try {
    const res = await fetch('http://localhost:5000/config/balanceo', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ algoritmo_balanceo: selectedAlgorithm }),
    });

    const data = await res.json();
    showMessageModal(data.message || 'Algoritmo de Balanceo de Carga guardado con éxito!');
    loadConfigHistory(); // Recargar el historial de configuraciones
    updateDashboardAlgorithms(); // Actualizar el dashboard
  } catch (error) {
    console.error('Error al guardar el algoritmo de balanceo de carga:', error);
    showMessageModal('Error al guardar el algoritmo de Balanceo de Carga: ' + error.message);
  }
}

/**
 * Guarda el algoritmo de enrutamiento seleccionado en la base de datos.
 */
async function saveRoutingAlgorithm() {
  const selectElement = document.getElementById('routing-algo');
  const selectedAlgorithm = selectElement.value;

  console.log('Guardando Algoritmo de Enrutamiento:', selectedAlgorithm);

  try {
    const res = await fetch('http://localhost:5000/config/enrutamiento', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ algoritmo_enrutamiento: selectedAlgorithm }),
    });

    const data = await res.json();
    showMessageModal(data.message || 'Algoritmo de Enrutamiento guardado con éxito!');
    loadConfigHistory(); // Recargar el historial de configuraciones
    updateDashboardAlgorithms(); // Actualizar el dashboard
  } catch (error) {
    console.error('Error al guardar el algoritmo de enrutamiento:', error);
    showMessageModal('Error al guardar el algoritmo de Enrutamiento: ' + error.message);
  }
}

/**
 * Guarda los pesos de los servidores para Weighted Round-Robin en la base de datos.
 * Asume que hay un endpoint en el backend para manejar esto.
 */
async function saveWeightedRoundRobinWeights() {
  const weightInputs = document.querySelectorAll('#config input[type="number"][data-server]');
  const weights = {};
  weightInputs.forEach(input => {
    const serverName = input.dataset.server;
    const weight = parseInt(input.value, 10);
    weights[serverName] = weight;
  });

  console.log('Guardando Pesos de Weighted Round-Robin:', weights);

  try {
    // Este endpoint es un ejemplo. Debes implementarlo en tu backend.
    const res = await fetch('http://localhost:5000/config/weights', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ weights: weights }),
    });

    const data = await res.json();
    showMessageModal(data.message || 'Pesos de Weighted Round-Robin guardados con éxito!');
  } catch (error) {
    console.error('Error al guardar los pesos:', error);
    showMessageModal('Error al guardar los pesos: ' + error.message);
  }
}

/**
 * Carga el historial de configuraciones desde el backend y lo muestra en la lista.
 */
async function loadConfigHistory() {
  try {
    const res = await fetch('http://localhost:5000/config/history'); // Asume un endpoint para el historial
    const data = await res.json();
    const historyList = document.getElementById('config-history-list');
    historyList.innerHTML = '';

    if (data && data.length > 0) {
      data.forEach(config => {
        const li = document.createElement('li');
        const date = new Date(config.fecha_activacion).toLocaleString();
        li.textContent = `${date}: ${config.algoritmo_balanceo || 'N/A'} / ${config.algoritmo_enrutamiento || 'N/A'}`;
        historyList.appendChild(li);
      });
    } else {
      historyList.innerHTML = '<li>No hay historial de configuraciones.</li>';
    }
  } catch (error) {
    console.error('Error al cargar el historial de configuraciones:', error);
    showMessageModal('Error al cargar el historial de configuraciones: ' + error.message);
  }
}

/**
 * Carga la configuración actual desde el backend y actualiza los selectores.
 */
async function loadCurrentConfigurations() {
  try {
    const res = await fetch('http://localhost:5000/config/current'); // Asume un endpoint para la configuración actual
    const data = await res.json();

    if (data) {
      const loadBalancingSelect = document.getElementById('load-balancing-algo');
      const routingSelect = document.getElementById('routing-algo');

      if (data.algoritmo_balanceo) {
        loadBalancingSelect.value = data.algoritmo_balanceo;
      }
      if (data.algoritmo_enrutamiento) {
        routingSelect.value = data.algoritmo_enrutamiento;
      }
      // Si tienes pesos guardados, también podrías cargarlos aquí
    }
  } catch (error) {
    console.error('Error al cargar las configuraciones actuales:', error);
    showMessageModal('Error al cargar las configuraciones actuales: ' + error.message);
  }
}

/**
 * Actualiza los algoritmos mostrados en el dashboard.
 * Debería ser llamada después de guardar una nueva configuración.
 */
async function updateDashboardAlgorithms() {
  try {
    const res = await fetch('http://localhost:5000/config/current'); // Obtener la configuración más reciente
    const data = await res.json();

    const dashboardBalanceo = document.querySelector('#dashboard p:nth-child(2) span:nth-child(1)');
    const dashboardEnrutamiento = document.querySelector('#dashboard p:nth-child(2) span:nth-child(2)');

    if (data.algoritmo_balanceo) {
      // Formatear para mostrar en el dashboard si es necesario (ej. 'round_robin' -> 'Round-Robin')
      dashboardBalanceo.textContent = data.algoritmo_balanceo.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase());
    }
    if (data.algoritmo_enrutamiento) {
      dashboardEnrutamiento.textContent = data.algoritmo_enrutamiento.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase());
      if (data.algoritmo_enrutamiento === 'dijkstra') {
        dashboardEnrutamiento.textContent += ' (ancho de banda)';
      }
    }

  } catch (error) {
    console.error('Error al actualizar algoritmos del dashboard:', error);
  }
}


window.addEventListener('DOMContentLoaded', () => {
  cargarEstadisticas();
  cargarLogs();
  cargarTopologia();
  loadCurrentConfigurations(); // Carga la configuración actual al iniciar
  loadConfigHistory(); // Carga el historial de configuraciones
  updateDashboardAlgorithms(); // Actualiza los algoritmos en el dashboard al cargar
});