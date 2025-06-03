// --- topology.js ---



let map;                        // Mapa Leaflet
let markers    = {};            // { id_switch: L.marker }   (marcadores de switches)
let hostMarkers = {};           // { mac: L.marker }         (marcadores de hosts)
let polylines  = [];            // Líneas que representan enlaces
let selectedHosts = [];         // [{ mac, ip, name, id_switch }, ...] (máximo 2)
let rutaPolylines = [];         // Líneas rojas que marcan la ruta calculada


function colorPorAnchoBanda(ancho_banda) {
  if (ancho_banda >= 1000) return '#008000';
  else if (ancho_banda >= 100) return '#FFA500';
  else return '#FF0000';
}

function getHostIcon(host, seleccionado = false) {
  const esServidor = window.servidoresActivos?.includes(host.nombre);
  const esCliente = window.activeFFplayClients?.some(c => c.host === host.nombre);

  let iconUrl = 'static/icons/monitor.png';
  if (seleccionado) {
    iconUrl = 'static/icons/monitor_selected.png';
  }
  if (esServidor) {
    iconUrl = 'static/icons/server_host.png';
  } else if (esCliente) {
    iconUrl = 'static/icons/client_host.png';
  }

  return L.icon({
    iconUrl,
    iconSize: [13, 13],
    iconAnchor: [6.5, 6.5],
    popupAnchor: [0, -16]
  });
}

function deseleccionarHost(hostName) {
  if (!window.selectedHosts || !window.hostMarkers) return;

  const index = selectedHosts.findIndex(h => h.name === hostName);
  if (index !== -1) {
    const [removed] = selectedHosts.splice(index, 1);
    const marker = hostMarkers[removed.mac];
    if (marker) {
      marker.setIcon(getHostIcon(removed, false));
    }
  }
}

window.deseleccionarHost = deseleccionarHost;

function getSwitchIcon() {
  return L.icon({
    iconUrl: 'static/icons/switch.png',
    iconSize: [18, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16]
  });
}

function actualizarIconosDeHosts() {
  if (!window.hostMarkers) return;

  Object.entries(window.hostMarkers).forEach(([mac, marker]) => {
    const host = window.hostData?.find(h => h.mac === mac);
    if (!host) return;

    const seleccionado = selectedHosts.some(h => h.mac === mac);
    marker.setIcon(getHostIcon(host, seleccionado));
  });
}


function showMessageModal(title, message, isConfirm = false, onConfirm = null) {
  const modal = document.getElementById('message-modal');
  const titleElem = document.getElementById('message-modal-title');
  const contentElem = document.getElementById('message-modal-content');
  const confirmBtn = document.getElementById('message-modal-confirm-btn');
  const cancelBtn = document.getElementById('message-modal-cancel-btn');

  if (!modal || !titleElem || !contentElem || !confirmBtn || !cancelBtn) {
    alert(`${title}\n\n${message}`);
    if (isConfirm && onConfirm) onConfirm();
    return;
  }

  titleElem.textContent = title;
  contentElem.textContent = message;
  confirmBtn.onclick = null;
  cancelBtn.onclick = null;

  confirmBtn.onclick = () => {
    modal.classList.add('hidden');
    if (isConfirm && onConfirm) onConfirm();
  };

  if (isConfirm) {
    cancelBtn.classList.remove('hidden');
    cancelBtn.onclick = () => modal.classList.add('hidden');
  } else {
    cancelBtn.classList.add('hidden');
  }

  modal.classList.remove('hidden');
}

async function loadTopology() {
  try {
    const response = await fetch(`${API_BASE_URL}/topology/get`);
    if (!response.ok) throw new Error(`Error ${response.status}`);
    const data = await response.json();
    if (map) map.remove();

    const mapContainer = document.getElementById('mapa-topologia');
    if (!mapContainer) throw new Error("No se encontró el contenedor del mapa");

    map = L.map(mapContainer);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    Object.values(markers).forEach(m => m.remove());
    Object.values(hostMarkers).forEach(m => m.remove());
    polylines.forEach(p => p.remove());
    rutaPolylines.forEach(r => r.remove());

    markers = {};
    hostMarkers = {};
    polylines = [];
    rutaPolylines = [];
    selectedHosts = [];
    let allLatLngs = [];

    if (Array.isArray(data.switches)) {
      data.switches.forEach(sw => {
        if (typeof sw.latitud === 'number' && typeof sw.longitud === 'number') {
          const marker = L.marker([sw.latitud, sw.longitud], {
            icon: getSwitchIcon()
          }).addTo(map)
            .bindPopup(`<b>${sw.nombre}</b><br>DPID: ${sw.dpid_str}<br>id_switch: ${sw.id_switch}<br>Estado: ${sw.status}`);

          markers[sw.id_switch] = marker;
          allLatLngs.push([sw.latitud, sw.longitud]);
        }
      });
    }

    if (Array.isArray(data.enlaces)) {
      data.enlaces.forEach(enlace => {
        const sw1 = data.switches.find(sw => sw.id_switch === enlace.id_origen);
        const sw2 = data.switches.find(sw => sw.id_switch === enlace.id_destino);
        if (sw1 && sw2) {
          const polyline = L.polyline([
            [sw1.latitud, sw1.longitud],
            [sw2.latitud, sw2.longitud]
          ], {
            color: colorPorAnchoBanda(enlace.ancho_banda),
            weight: 3,
            opacity: 0.7
          }).addTo(map)
            .bindPopup(`<b>${sw1.nombre} ↔ ${sw2.nombre}</b><br>Ancho de Banda: ${enlace.ancho_banda} Mbps`);
          polylines.push(polyline);
          allLatLngs.push([sw1.latitud, sw1.longitud], [sw2.latitud, sw2.longitud]);
        }
      });
    }

    const hostsPorSwitch = {};
    data.hosts.forEach(host => {
      const idSw = parseInt(host.id_switch_conectado, 10);
      if (!hostsPorSwitch[idSw]) hostsPorSwitch[idSw] = [];
      hostsPorSwitch[idSw].push(host);
    });
    window.hostData = data.hosts;

    function getOffsetPosition(baseLat, baseLon, index, total) {
      const spacing = 1.4; // distancia horizontal entre hosts
      const offsetLon = baseLon + (index - (total - 1) / 2) * spacing;
      const offsetLat = baseLat - .93; // un poco más abajo del switch
      return [offsetLat, offsetLon];
    }


    Object.entries(hostsPorSwitch).forEach(([idSw, hosts]) => {
      const sw = data.switches.find(sw => sw.id_switch === parseInt(idSw));
      if (!sw) return;
      hosts.forEach((host, i) => {
        const [lat, lon] = getOffsetPosition(sw.latitud, sw.longitud, i, hosts.length);
        const marker = L.marker([lat, lon], { icon: getHostIcon(host, false) })
          .addTo(map)
          .bindPopup(`<b>${host.nombre}</b><br>IP: ${host.ip}<br>MAC: ${host.mac}<br>Switch: ${sw.nombre}`)
          .bindTooltip(`${host.nombre} (${host.ip})`, { direction: 'top' });

        hostMarkers[host.mac] = marker;
        allLatLngs.push([lat, lon]);

        marker.on('click', () => {
          const idx = selectedHosts.findIndex(h => h.mac === host.mac);

          if (idx !== -1) {
            selectedHosts.splice(idx, 1);
            marker.setIcon(getHostIcon(host, false));
          } else {
            if (selectedHosts.length === 2) {
              const removed = selectedHosts.pop();
              const removedMarker = hostMarkers[removed.mac];
              if (removedMarker) {
                removedMarker.setIcon(hostIcon(false));
              }
            }
            selectedHosts.push({
              mac: host.mac,
              ip: host.ip,
              name: host.nombre,
              id_switch: sw.id_switch
            });
            marker.setIcon(getHostIcon(host, true));
          }

          togglePingButton();
        });

        // Línea de conexión del host al switch
        const hostLine = L.polyline([
          [sw.latitud, sw.longitud],
          [lat, lon]
        ], {
          color: '#666',
          weight: 3,
          opacity: 0.8,
          dashArray: '4,6'
        }).addTo(map);
        polylines.push(hostLine);
      });
    });

    if (allLatLngs.length > 0) {
      const bounds = L.latLngBounds(allLatLngs);
      map.fitBounds(bounds.pad(0.1)); // Disminuido para mejor visibilidad
    }

    togglePingButton();
  } catch (err) {
    console.error("Error en loadTopology:", err);
    showMessageModal('Error', `No se pudo cargar la topología: ${err.message}`);
  }
}


function togglePingButton() {
  const pingButton = document.getElementById('btn-ping');
  if (pingButton) pingButton.disabled = (selectedHosts.length !== 2);
}


// ===========================================
//  Inicia el ping (SSE) y, al finalizar, calcula ruta
// ===========================================
function iniciarPing() {
  if (selectedHosts.length !== 2) {
    showMessageModal('Atención', 'Debes seleccionar exactamente 2 hosts para probar conectividad.');
    return;
  }

  const host1 = selectedHosts[0];
  const host2 = selectedHosts[1];

  const output = document.getElementById('ping-output');
  if (output) {
    output.textContent = `Iniciando ping de ${host1.name} (${host1.ip}) a ${host2.ip}...\n`;
  }

  mostrarPingStream(host1, host2);
}

function mostrarPingStream(hostOrigenObj, hostDestinoObj) {
  const origenName     = hostOrigenObj.name;
  const origenIp       = hostOrigenObj.ip;
  const destinoIp      = hostDestinoObj.ip;
  const origenMac      = hostOrigenObj.mac;
  const destinoMac     = hostDestinoObj.mac;
  const origenIdSwitch = hostOrigenObj.id_switch;
  const destinoIdSwitch= hostDestinoObj.id_switch;

  const output = document.getElementById('ping-output');
  output.textContent += `Conectando SSE para ping...\n`;

  // SSE: ping entre hosts en Mininet
  const url = `${MININET_AGENT_URL}/mininet/ping_between_hosts_stream?origen=${encodeURIComponent(origenName)}&destino=${encodeURIComponent(destinoIp)}`;
  const eventSource = new EventSource(url);

  eventSource.onopen = () => {
    output.textContent += 'Conexión SSE establecida. Esperando resultados del ping...\n';
  };

  eventSource.onmessage = (event) => {
    output.textContent += event.data + '\n';
    output.parentElement.scrollTop = output.parentElement.scrollHeight;

    if (event.data.includes('Fin del ping') || event.data.includes('error de conexión')) {
      eventSource.close();
      obtenerYMostrarRuta(origenMac, destinoMac, origenIdSwitch, destinoIdSwitch);
    }
  };

  eventSource.onerror = () => {
    output.textContent += '\n[Fin del ping o error de conexión]\n';
    eventSource.close();
    obtenerYMostrarRuta(origenMac, destinoMac, origenIdSwitch, destinoIdSwitch);
  };
}

// ===============================================
//  Llama a Dijkstra (Flask) y dibuja la ruta
// ===============================================
async function obtenerYMostrarRuta(origenMac, destinoMac, origenIdSwitch, destinoIdSwitch) {
  const output = document.getElementById('ping-output');
  output.textContent += '\nCalculando ruta con Dijkstra...\n';

  try {
    // 1) POST a /dijkstra/calculate_path
    const pathRes = await fetch(`${API_BASE_URL}/dijkstra/calculate_path`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        src_mac: origenMac,
        dst_mac: destinoMac
      })
    });
    if (!pathRes.ok) {
      const errData = await pathRes.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`Dijkstra error ${pathRes.status}: ${errData.message || pathRes.statusText}`);
    }

    const pathData = await pathRes.json();
    const pathArr = pathData.path; // [{ dpid: <int>, out_port: <int>, in_port: <int|null> }, ...]
    output.textContent += `Ruta recibida: ${JSON.stringify(pathArr)}\n`;
    console.log("Ruta calculada (pathArr):", pathArr);

    // 2) Obtener topología actual (solo para coordenadas)
    const topoRes = await fetch(`${API_BASE_URL}/topology/get`);
    if (!topoRes.ok) {
      throw new Error(`Error al obtener topología: ${topoRes.status}`);
    }
    const topoData = await topoRes.json();
    const allSwitchesData = Array.isArray(topoData.switches) ? topoData.switches : [];

    // 3) Dibujar ruta en el mapa
    dibujarRutaEnMapa(pathArr, allSwitchesData);

  } catch (err) {
    output.textContent += `Error: ${err.message}\n`;
    console.error("Error en obtenerYMostrarRuta:", err);
  }
}

// ==================================================
//  Dibuja la ruta en el mapa usando id_switch directo
// ==================================================
function dibujarRutaEnMapa(ruta, allSwitchesData) {
  // Eliminar trazados de ruta previos
  rutaPolylines.forEach(line => line.remove());
  rutaPolylines = [];

  if (!Array.isArray(ruta) || ruta.length < 2) {
    console.warn("dibujarRutaEnMapa: ruta inválida o muy corta:", ruta);
    return;
  }

  for (let i = 0; i < ruta.length - 1; i++) {
    const currentNode = ruta[i];       // { dpid: <int>, out_port, in_port }
    const nextNode    = ruta[i + 1];   // idem

    const currentId  = currentNode.dpid; // entero = id_switch
    const nextId     = nextNode.dpid;    // entero = id_switch

    const sourceSwitch = allSwitchesData.find(sw => sw.id_switch === currentId);
    const destSwitch   = allSwitchesData.find(sw => sw.id_switch === nextId);

    if (
      sourceSwitch &&
      destSwitch &&
      typeof sourceSwitch.latitud === 'number' &&
      typeof sourceSwitch.longitud === 'number' &&
      typeof destSwitch.latitud === 'number' &&
      typeof destSwitch.longitud === 'number'
    ) {
      const polyline = L.polyline([
        [sourceSwitch.latitud, sourceSwitch.longitud],
        [destSwitch.latitud,   destSwitch.longitud]
      ], {
        color:     'red',
        weight:    5,
        opacity:   0.9,
        dashArray: '6'
      }).addTo(map);

      rutaPolylines.push(polyline);
      console.log(`Segmento de ruta: ${sourceSwitch.nombre} (id_switch=${currentId}) → ${destSwitch.nombre} (id_switch=${nextId})`);
    } else {
      console.warn(`No se encontraron switches para id_switch=${currentId} o id_switch=${nextId} en topología.`);
    }
  }
}

// =======================================
//  Inicialización al cargar la página
// =======================================
document.addEventListener('DOMContentLoaded', () => {
  loadTopology();

  // Asociar el botón “Ping” (ya no hay checkboxes en HTML)
  const pingBtn = document.getElementById('btn-ping');
  if (pingBtn) {
    pingBtn.addEventListener('click', iniciarPing);
  }
});
