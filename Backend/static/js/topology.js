// --- topology.js ---
// Gestión completa de topología (switches, hosts en mapa),
// ping entre hosts (SSE) y trazado de ruta (Dijkstra),
// **sin generar ningún checkbox en HTML**.

// ==============================
//  Constantes y Variables Globales
// ==============================


let map;                        // Mapa Leaflet
let markers    = {};            // { id_switch: L.marker }   (marcadores de switches)
let hostMarkers = {};           // { mac: L.marker }         (marcadores de hosts)
let polylines  = [];            // Líneas que representan enlaces
let selectedHosts = [];         // [{ mac, ip, name, id_switch }, ...] (máximo 2)
let rutaPolylines = [];         // Líneas rojas que marcan la ruta calculada

// URL del controlador Ryu (opcional; si no lo usas, déjalo comentado)
// const RYU_API_BASE_URL = 'http://192.168.18.161:8080';

// =======================================
//  Función auxiliar para color de enlaces
// =======================================
function colorPorAnchoBanda(ancho_banda) {
  if (ancho_banda >= 1000)      return '#008000'; // verde
  else if (ancho_banda >= 100)  return '#FFA500'; // naranja
  else                           return '#FF0000'; // rojo
}

// ==========================================
//  Función para mostrar mensajes/modales
// ==========================================
function showMessageModal(title, message, isConfirm = false, onConfirm = null) {
  const modal       = document.getElementById('message-modal');
  const titleElem   = document.getElementById('message-modal-title');
  const contentElem = document.getElementById('message-modal-content');
  const confirmBtn  = document.getElementById('message-modal-confirm-btn');
  const cancelBtn   = document.getElementById('message-modal-cancel-btn');

  if (!modal || !titleElem || !contentElem || !confirmBtn || !cancelBtn) {
    // Si no existe el modal en el DOM, caemos a un alert simple
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
//  Carga y dibuja toda la topología
// =======================================
async function loadTopology() {
  try {
    const response = await fetch(`${API_BASE_URL}/topology/get`);
    if (!response.ok) {
      const errData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`HTTP ${response.status}: ${errData.message || response.statusText}`);
    }

    const data = await response.json();
    console.log("loadTopology → data:", data);

    // Si el mapa ya existía, lo removemos para recrearlo
    if (map) {
      map.remove();
    }

    // Inicializar Leaflet en el contenedor con ID 'mapa-topologia'
    const mapContainer = document.getElementById('mapa-topologia');
    if (!mapContainer) {
      throw new Error("Elemento HTML con id='mapa-topologia' no encontrado.");
    }
    map = L.map(mapContainer).setView([54.5, 15.3], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    // Limpiar marcadores/enlaces previos
    Object.values(markers).forEach(marker => marker.remove());
    Object.values(hostMarkers).forEach(marker => marker.remove());
    polylines.forEach(poly => poly.remove());
    markers     = {};
    hostMarkers = {};
    polylines   = [];
    selectedHosts = [];
    let allLatLngs = [];

    // -----------------------
    //  Dibujar SWITCHES
    // -----------------------
    if (Array.isArray(data.switches)) {
      data.switches.forEach(sw => {
        if (typeof sw.latitud === 'number' && typeof sw.longitud === 'number') {
          const marker = L.marker([sw.latitud, sw.longitud], {
            icon: L.divIcon({
              className: `custom-switch-icon ${sw.status}`,
              html: `<div class="switch-marker">${sw.nombre}</div>`,
              iconSize: [60, 20],
              iconAnchor: [30, 10]
            })
          })
          .addTo(map)
          .bindPopup(`<b>${sw.nombre}</b><br>DPID (hex): ${sw.dpid_str}<br>id_switch: ${sw.id_switch}<br>Estado: ${sw.status}`);

          markers[sw.id_switch] = marker;
          allLatLngs.push([sw.latitud, sw.longitud]);
        } else {
          console.warn(`Switch '${sw.nombre}' tiene coordenadas inválidas.`);
        }
      });
    } else {
      console.warn("loadTopology: 'switches' no es un arreglo válido.", data.switches);
    }

    // -----------------------
    //  Dibujar ENLACES
    // -----------------------
    if (Array.isArray(data.enlaces)) {
      data.enlaces.forEach(enlace => {
        const sourceSwitch = data.switches.find(sw => sw.id_switch === enlace.id_origen);
        const destSwitch   = data.switches.find(sw => sw.id_switch === enlace.id_destino);

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
            color: colorPorAnchoBanda(enlace.ancho_banda),
            weight: 3,
            opacity: 0.7
          }).addTo(map)
            .bindPopup(`
              <b>Enlace:</b> ${sourceSwitch.nombre} ↔ ${destSwitch.nombre}<br>
              Ancho de Banda: ${enlace.ancho_banda} Mbps
            `);

          polylines.push(polyline);
          allLatLngs.push([sourceSwitch.latitud, sourceSwitch.longitud]);
          allLatLngs.push([destSwitch.latitud,   destSwitch.longitud]);
        } else {
          console.warn(`Enlace inválido entre id_origen=${enlace.id_origen} y id_destino=${enlace.id_destino}.`);
        }
      });
    } else {
      console.warn("loadTopology: 'enlaces' no es un arreglo válido.", data.enlaces);
    }

    // -----------------------
    //  Dibujar HOSTS como marcadores “H” y permitir selección con clic
    // -----------------------
    if (Array.isArray(data.hosts)) {
      data.hosts.forEach(host => {
        // Se asume que el JSON trae host.id_switch_conectado (string o número)
        const switchAsociado = data.switches.find(sw => sw.id_switch === parseInt(host.id_switch_conectado, 10));
        if (switchAsociado) {
          // Calculamos un pequeño offset para no solapar el marcador con el switch
          const latOffset = switchAsociado.latitud + (Math.random() - 0.5) * 0.01;
          const lonOffset = switchAsociado.longitud + (Math.random() - 0.5) * 0.01;

          // Creamos el icono circular “H” (verde por defecto)
          const hostIcon = (color = '#4CAF50') => L.divIcon({
            className: 'custom-host-icon',
            html: `<div style="
              background-color: ${color};
              color: white;
              border-radius: 50%;
              width: 24px;
              height: 24px;
              display: flex;
              align-items: center;
              justify-content: center;
              font-size: 12px;
              font-weight: bold;
            ">H</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12]
          });

          // Colocamos el marcador en Leaflet
          const hostMarker = L.marker([latOffset, lonOffset], { icon: hostIcon() })
            .addTo(map)
            .bindPopup(`<b>${host.nombre}</b><br>IP: ${host.ip}<br>MAC: ${host.mac}<br>Switch: ${switchAsociado.nombre}`);

          // Guardamos el marcador para referenciarlo luego (por su MAC)
          hostMarkers[host.mac] = hostMarker;

          // Al hacer clic, alternamos selección (verde <-> naranja)
          hostMarker.on('click', () => {
            const idx = selectedHosts.findIndex(h => h.mac === host.mac);
            if (idx !== -1) {
              // Si ya estaba seleccionado, lo deseleccionamos
              selectedHosts.splice(idx, 1);
              hostMarker.setIcon(hostIcon()); // Volver a verde
            } else {
              // Si no estaba seleccionado, solo podemos tener hasta 2
              if (selectedHosts.length < 2) {
                selectedHosts.push({
                  mac: host.mac,
                  ip: host.ip,
                  name: host.nombre,
                  id_switch: switchAsociado.id_switch
                });
                hostMarker.setIcon(hostIcon('#FF9800')); // Color naranja para marcado
              } else {
                showMessageModal('Atención', 'Solo puedes seleccionar 2 hosts para el ping.');
              }
            }
            togglePingButton();
          });

          allLatLngs.push([latOffset, lonOffset]);
        } else {
          console.warn(`Host '${host.nombre}' no tiene un switch asociado válido.`);
        }
      });
    } else {
      console.warn("loadTopology: 'hosts' no es un arreglo válido.", data.hosts);
    }

    // Ajuste del zoom para que quede toda la topología en pantalla
    if (allLatLngs.length > 0) {
      const bounds = L.latLngBounds(allLatLngs);
      map.fitBounds(bounds.pad(0.5));
    }

    // Al final de la carga, aseguramos que el botón de ping esté correctamente habilitado/deshabilitado
    togglePingButton();

  } catch (err) {
    console.error("Error en loadTopology:", err);
    showMessageModal('Error', `No se pudo cargar la topología: ${err.message}`);
  }
}

// =======================================
//  Activa/Desactiva el botón de ping
// =======================================
function togglePingButton() {
  const pingButton = document.getElementById('btn-ping');
  if (!pingButton) return;
  pingButton.disabled = (selectedHosts.length !== 2);
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

    // 4) (Opcional) Enviar ruta a Ryu si necesitas configurar flujos
    /*
    const ryuPayload = {
      src_dpid: origenIdSwitch,
      dst_dpid: destinoIdSwitch,
      path: pathArr
    };
    const ryuRes = await fetch(`${RYU_API_BASE_URL}/add_path`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ryuPayload)
    });
    if (!ryuRes.ok) {
      const errRyu = await ryuRes.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(`Ryu error ${ryuRes.status}: ${errRyu.message || ryuRes.statusText}`);
    }
    output.textContent += 'Ruta enviada a Ryu exitosamente.\n';
    console.log("Ruta enviada a Ryu:", ryuPayload);
    */

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
