// --- Topology Functions ---
let map;
let markers = {}; // {id_switch: marker_obj} - Usaremos id_switch como clave para los marcadores de switches
let polylines = []; // Array of polyline objects

let selectedHosts = []; // Almacena objetos de host seleccionados

// Asegúrate de que estas URLs sean las correctas para tu Flask y Ryu
const RYU_API_BASE_URL = 'http://192.168.18.151:8080';

// Función auxiliar para colorear enlaces según el ancho de banda
function colorPorAnchoBanda(ancho_banda) {
    if (ancho_banda >= 1000) {
        return '#008000'; // Verde (alto ancho de banda)
    } else if (ancho_banda >= 100) {
        return '#FFA500'; // Naranja (ancho de banda medio)
    } else {
        return '#FF0000'; // Rojo (bajo ancho de banda)
    }
}

async function loadTopology() {
    try {
        const response = await fetch(`${API_BASE_URL}/topology/get`);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`HTTP error! status: ${response.status} - ${errorData.message || response.statusText}`);
        }

        const data = await response.json();
        console.log("Data received from backend:", data);

        // Verificar si el mapa ya existe y removerlo antes de inicializar uno nuevo
        if (map) {
            map.remove();
        }

        // Obtener el contenedor del mapa
        const mapContainer = document.getElementById('mapa-topologia');
        if (!mapContainer) {
            console.error("Error: Elemento HTML con ID 'mapa-topologia' no encontrado.");
            // No lanzar un error para permitir que el resto de la lógica continúe si es posible
            return;
        }

        map = L.map(mapContainer).setView([54.5, 15.3], 4);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);

        // Limpiar marcadores y polilíneas existentes antes de dibujar la nueva topología
        Object.values(markers).forEach(marker => marker.remove());
        polylines.forEach(polyline => polyline.remove());
        markers = {};
        polylines = [];
        let allLatLngs = [];

        // Switches
        if (data.switches && Array.isArray(data.switches)) {
            data.switches.forEach(sw => {
                if (typeof sw.latitud === 'number' && typeof sw.longitud === 'number') {
                    const marker = L.marker([sw.latitud, sw.longitud], {
                        icon: L.divIcon({
                            className: `custom-switch-icon ${sw.status}`, // Añadir clase de estado
                            html: `<div class="switch-marker">${sw.nombre}</div>`,
                            iconSize: [60, 20],
                            iconAnchor: [30, 10]
                        })
                    }).addTo(map);
                    markers[sw.id_switch] = marker; // Usar id_switch como clave
                    allLatLngs.push([sw.latitud, sw.longitud]);
                    marker.bindPopup(`<b>${sw.nombre}</b><br>DPID: ${sw.dpid_str}<br>Estado: ${sw.status}`);
                } else {
                    console.warn(`Switch ${sw.nombre} tiene latitud/longitud inválida.`);
                }
            });
        } else {
            console.warn("No switches data or not an array:", data.switches);
        }

        // Enlaces (Polylines)
        if (data.enlaces && Array.isArray(data.enlaces)) {
            data.enlaces.forEach(enlace => {
                const sourceSwitch = data.switches.find(sw => sw.id_switch === enlace.id_origen);
                const destSwitch = data.switches.find(sw => sw.id_switch === enlace.id_destino);

                if (sourceSwitch && destSwitch && typeof sourceSwitch.latitud === 'number' && typeof sourceSwitch.longitud === 'number' && typeof destSwitch.latitud === 'number' && typeof destSwitch.longitud === 'number') {
                    const polyline = L.polyline([
                        [sourceSwitch.latitud, sourceSwitch.longitud],
                        [destSwitch.latitud, destSwitch.longitud]
                    ], {
                        color: colorPorAnchoBanda(enlace.ancho_banda), // Usar la función de color
                        weight: 3,
                        opacity: 0.7
                    }).addTo(map);
                    polylines.push(polyline);
                    polyline.bindPopup(`<b>Enlace:</b> ${sourceSwitch.nombre} <-> ${destSwitch.nombre}<br>Ancho de Banda: ${enlace.ancho_banda}Mbps`);
                } else {
                    console.warn(`Enlace entre ${enlace.id_origen} y ${enlace.id_destino} tiene coordenadas de switch inválidas.`);
                }
            });
        } else {
            console.warn("No enlaces data or not an array:", data.enlaces);
        }

        // Hosts (manejar hosts seleccionados con checkboxes)
        const hostList = document.getElementById('host-selection-list');
        if (!hostList) { // **VERIFICACIÓN AÑADIDA**
            console.error("Error: Elemento HTML con ID 'host-selection-list' no encontrado.");
            return; // Salir si no se encuentra el elemento crítico
        }
        hostList.innerHTML = ''; // Limpiar lista existente
        selectedHosts = []; // Limpiar selección existente

        if (data.hosts && Array.isArray(data.hosts)) {
            data.hosts.forEach(host => {
                // MODIFICACIÓN: Convertir host.switch_asociado a número para la comparación
                const switchAsociado = data.switches.find(sw => sw.id_switch === parseInt(host.switch_asociado));
                if (switchAsociado) {
                    const listItem = document.createElement('li');
                    listItem.className = 'list-group-item'; // Puedes ajustar las clases Tailwind aquí
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.value = host.mac; // Usar MAC como valor
                    checkbox.id = `host-${host.mac}`;
                    checkbox.name = 'selectedHosts';
                    checkbox.dataset.ip = host.ip; // Almacenar IP para el ping
                    checkbox.dataset.name = host.nombre; // Almacenar nombre para referencia
                    // Almacenar el dpid_str del switch asociado para usarlo en la solicitud a Flask/Ryu
                    checkbox.dataset.dpid = switchAsociado.dpid_str;
                    checkbox.addEventListener('change', updateSelectedHosts);

                    const label = document.createElement('label');
                    label.htmlFor = `host-${host.mac}`;
                    label.textContent = `${host.nombre} (IP: ${host.ip}, MAC: ${host.mac}, Switch: ${switchAsociado.nombre})`;
                    listItem.appendChild(checkbox);
                    listItem.appendChild(label);
                    hostList.appendChild(listItem);
                } else {
                    console.warn(`Host ${host.nombre} no tiene switch asociado válido.`);
                }
            });
        } else {
            console.warn("No hosts data or not an array:", data.hosts);
        }

        // Ajustar el mapa para que muestre todos los elementos
        if (allLatLngs.length > 0) {
            const bounds = L.latLngBounds(allLatLngs);
            map.fitBounds(bounds.pad(0.5)); // Añadir un poco de padding
        }

        // Habilitar/deshabilitar el botón de ping al cargar la topología
        updateSelectedHosts();

    } catch (error) {
        console.error("Error loading topology:", error);
        // Usar un div de mensaje si existe, en lugar de alert
        const output = document.getElementById('ping-output');
        if (output) {
            output.textContent = `Error al cargar la topología: ${error.message}`;
        } else {
            console.error("Elemento 'ping-output' no encontrado para mostrar el error.");
            alert("Error al cargar la topología: " + error.message);
        }
    }
}

function updateSelectedHosts() {
    selectedHosts = [];
    document.querySelectorAll('#host-selection-list input[type="checkbox"]:checked').forEach(checkbox => {
        selectedHosts.push({
            mac: checkbox.value,
            ip: checkbox.dataset.ip,
            name: checkbox.dataset.name,
            dpid: checkbox.dataset.dpid // DPID del switch asociado (string)
        });
    });
    const pingButton = document.getElementById('ping-button');
    if (pingButton) { // **VERIFICACIÓN AÑADIDA**
        pingButton.disabled = selectedHosts.length !== 2; // Habilitar solo si hay 2 hosts seleccionados
    } else {
        console.warn("Elemento HTML con ID 'ping-button' no encontrado.");
    }
}

function iniciarPing() { // **FUNCIÓN RENOMBRADA Y VERIFICADA**
    if (selectedHosts.length !== 2) {
        // Usar un div de mensaje si existe, en lugar de alert
        const output = document.getElementById('ping-output');
        if (output) {
            output.textContent = "Por favor, selecciona exactamente dos hosts para iniciar el ping.";
        } else {
            console.error("Elemento 'ping-output' no encontrado para mostrar el mensaje de error.");
            alert("Por favor, selecciona exactamente dos hosts para iniciar el ping.");
        }
        return;
    }

    const host1 = selectedHosts[0];
    const host2 = selectedHosts[1];

    const output = document.getElementById('ping-output');
    if (!output) { // **VERIFICACIÓN AÑADIDA**
        console.error("Error: Elemento HTML con ID 'ping-output' no encontrado.");
        return;
    }
    output.textContent = 'Iniciando ping...\n';

    // Inicia el flujo de ping y luego cálculo/dibujo de ruta
    realizarPingYObtenerRuta(host1.ip, host2.ip, host1.mac, host2.mac, host1.dpid, host2.dpid);
}

function realizarPingYObtenerRuta(origenIp, destinoIp, origenMac, destinoMac, origenDpid, destinoDpid) {
  const output = document.getElementById('ping-output');
  if (!output) { // **VERIFICACIÓN AÑADIDA**
      console.error("Error: Elemento HTML con ID 'ping-output' no encontrado.");
      return;
  }
  output.textContent += 'Estableciendo conexión para ping...\n';

  // Iniciar la conexión SSE para el ping
  const eventSource = new EventSource(`${API_BASE_URL}/client/ping_stream?src_ip=${origenIp}&dst_ip=${destinoIp}`);

  eventSource.onopen = function() {
    output.textContent += 'Conexión SSE establecida. Esperando resultados del ping...\n';
  };

  eventSource.onmessage = function (event) {
    output.textContent += event.data + '\n';
    output.parentElement.scrollTop = output.parentElement.scrollHeight;

    // Detectar el final del ping para cerrar el stream y obtener la ruta
    if (event.data.includes('Fin del ping') || event.data.includes('error de conexión')) {
      eventSource.close();
      // Ahora, después del ping, calculamos y dibujamos la ruta
      obtenerYMostrarRuta(origenMac, destinoMac, origenDpid, destinoDpid);
    }
  };

  eventSource.onerror = function () {
    output.textContent += '\n[Fin del ping o error de conexión]\n';
    eventSource.close();
    // En caso de error de conexión SSE, aún intentamos obtener y mostrar la ruta
    obtenerYMostrarRuta(origenMac, destinoMac, origenDpid, destinoDpid);
  };
}

let rutaPolylines = [];

function dibujarRutaEnMapa(ruta, allSwitchesData) {
    // Elimina líneas anteriores de ruta
    rutaPolylines.forEach(line => line.remove());
    rutaPolylines = [];

    if (!Array.isArray(ruta) || ruta.length < 2) { // La ruta debe tener al menos 2 DPIDs para dibujar un enlace
        console.warn("Ruta inválida o demasiado corta para dibujar:", ruta);
        return;
    }

    for (let i = 0; i < ruta.length - 1; i++) {
        const currentPathNode = ruta[i];
        const nextPathNode = ruta[i + 1];

        const currentDpid = currentPathNode[0]; // Este es un entero (DPID)
        const nextDpid = nextPathNode[0];     // Este es un entero (DPID)

        // Buscar el switch por su DPID (entero) en los datos cargados.
        // Convertimos el dpid_str de los datos del switch a entero para la comparación
        const sourceSwitch = allSwitchesData.find(sw => parseInt(sw.dpid_str, 16) === currentDpid);
        const destSwitch = allSwitchesData.find(sw => parseInt(sw.dpid_str, 16) === nextDpid);


        if (sourceSwitch && destSwitch && typeof sourceSwitch.latitud === 'number' && typeof sourceSwitch.longitud === 'number' && typeof destSwitch.latitud === 'number' && typeof destSwitch.longitud === 'number') {
            const polyline = L.polyline([
                [sourceSwitch.latitud, sourceSwitch.longitud],
                [destSwitch.latitud, destSwitch.longitud]
            ], {
                color: 'red',
                weight: 5,
                opacity: 0.8
            }).addTo(map);
            rutaPolylines.push(polyline);
            console.log(`Dibujada línea de ruta entre ${sourceSwitch.nombre} (DPID: ${currentDpid}) y ${destSwitch.nombre} (DPID: ${nextDpid})`);
        } else {
            console.warn(`No se pudieron encontrar las coordenadas de los switches con DPID ${currentDpid} o ${nextDpid} para dibujar la ruta.`);
        }
    }
}

async function obtenerYMostrarRuta(origenMac, destinoMac, origenDpid, destinoDpid) {
    const output = document.getElementById('ping-output');
    if (!output) { // **VERIFICACIÓN AÑADIDA**
        console.error("Error: Elemento HTML con ID 'ping-output' no encontrado.");
        return;
    }
    output.textContent += '\nCalculando ruta...\n';

    try {
        // 1. Solicitar la ruta a tu backend Flask
        const pathResponse = await fetch(`${API_BASE_URL}/dijkstra/calculate_path`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                src_mac: origenMac,
                dst_mac: destinoMac,
                // Opcional: puedes enviar el algoritmo si quieres que el frontend lo elija
                // algorithm: 'shortest_path' // o 'dijkstra'
            }),
        });

        if (!pathResponse.ok) {
            const errorData = await pathResponse.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`Error al calcular la ruta: ${pathResponse.status} - ${errorData.message || pathResponse.statusText}`);
        }

        const pathData = await pathResponse.json();
        const path = pathData.path; // La ruta calculada
        const dstSwitchPortToHost = pathData.dst_switch_port_to_host; // Puerto al host de destino

        output.textContent += `Ruta calculada: ${JSON.stringify(path)}\n`;
        output.textContent += `Puerto final al host de destino: ${dstSwitchPortToHost}\n`;
        console.log("Ruta calculada:", path);
        console.log("Puerto final al host de destino:", dstSwitchPortToHost);


        // Obtener los datos de switches de la topología para dibujar
        // Es importante obtener la topología más reciente para asegurar que los DPIDs y coordenadas sean correctos
        const topologyResponse = await fetch(`${API_BASE_URL}/topology/get`);
        if (!topologyResponse.ok) {
            throw new Error(`Error al obtener datos de topología para dibujar la ruta: ${topologyResponse.status}`);
        }
        const topologyData = await topologyResponse.json();
        const allSwitchesData = topologyData.switches;

        // 2. Dibujar la ruta en el mapa
        dibujarRutaEnMapa(path, allSwitchesData);


        // 3. Enviar la ruta al controlador Ryu
        output.textContent += 'Enviando ruta al controlador Ryu...\n';
        // Convertir los DPIDs de string hexadecimal (del frontend) a entero para la API de Ryu
        // El path ya contiene DPIDs como enteros si viene de Flask
        const ryuPathData = {
            src_dpid: parseInt(origenDpid, 16), // Convertir DPID de string hexadecimal a entero
            dst_dpid: parseInt(destinoDpid, 16), // Convertir DPID de string hexadecimal a entero
            path: path // La ruta en el formato [(dpid, port_out, port_in), ...]
        };

        const ryuResponse = await fetch(`${RYU_API_BASE_URL}/add_path`, { // Este endpoint lo definimos en Ryu
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(ryuPathData),
        });

        if (!ryuResponse.ok) {
            const errorData = await ryuResponse.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(`Error al enviar ruta a Ryu: ${ryuResponse.status} - ${errorData.message || ryuResponse.statusText}`);
        }

        output.textContent += 'Ruta enviada a Ryu exitosamente.\n';
        console.log("Ruta enviada a Ryu:", ryuPathData);

    } catch (error) {
        output.textContent += `Error: ${error.message}\n`;
        console.error("Error en obtenerYMostrarRuta:", error);
    }
}

// Cargar la topología al iniciar
document.addEventListener('DOMContentLoaded', loadTopology);
