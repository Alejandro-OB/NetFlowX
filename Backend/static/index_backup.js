document.getElementById('menu-btn').addEventListener('click', () => {
    const nav = document.querySelector('nav');
    nav.classList.toggle('hidden');
  });
  
  const map = L.map('mapa-topologia').setView([54.5, 15.3], 4);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a> contributors'
  }).addTo(map);
  
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
          .bindPopup(`<strong>s${sw.id}</strong>`);  // Mostrar id con s
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
    }
  }

  function colorPorAnchoBanda(bw) {
    if (bw >= 1000) return 'green';    // Muy alto
    if (bw >= 100) return 'yellow';
    //if (bw >= 200) return 'yellow';
    if (bw >= 10) return 'orange';
    return 'red';                      // Bajo
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
  
    if (!origen || !destino || !bw) return alert("Completa todos los campos");
  
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
    alert(data.message || "Enlace creado");
    cargarTopologia();
  }
  
  async function eliminarEnlace(origen, destino) {
    if (!confirm(`¿Eliminar el enlace entre ${origen} y ${destino}?`)) return;
  
    const res = await fetch("http://localhost:5000/topology/enlace", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origen, destino })
    });
  
    const data = await res.json();
    alert(data.message || "Eliminado");
    cargarTopologia();
  }
  
  
  window.addEventListener('DOMContentLoaded', () => {
    cargarEstadisticas();
    cargarLogs();
    cargarTopologia();
  });
  
  