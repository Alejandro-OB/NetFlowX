async function cargarEstadisticas() {
  try {
    const res = await fetch("/stats/dashboard");
    const stats = await res.json();

    // Tarjetas resumen
    document.getElementById("total-clientes").textContent = stats.total_clientes;
    document.getElementById("total-transmisiones").textContent = stats.transmisiones_activas;
    document.getElementById("total-grupos").textContent = stats.flujos_multicast.length;

    // Gráfico de barras - Clientes por servidor
    const grafico = document.getElementById("grafico-clientes");
    grafico.innerHTML = ""; 

    // Preparar los datos para el gráfico
    const labels = stats.clientes_por_servidor.map(item => item.servidor);
    const clientesData = stats.clientes_por_servidor.map(item => item.total_clientes);

    // Verificar si ya existe un gráfico y destruirlo antes de crear uno nuevo
    if (window.myChart) {
      window.myChart.destroy(); 
    }

    // Crear el gráfico
    const ctx = grafico.getContext("2d");
    window.myChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Clientes Asociados',
            data: clientesData,
            backgroundColor: 'rgba(54, 162, 235, 0.5)',
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 1
          }
        ]
      },
      options: {
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              stepSize: 1
            }
          }
        },
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: 'Clientes Asociados a Servidores Activos'
          },
          legend: {
            display: false
          }
        }
      }
    });

    // Tabla carga vs peso 
    const tablaCarga = document.getElementById("tabla-carga");
    tablaCarga.innerHTML = "";
    stats.carga_vs_peso.forEach(item => {
      const row = `<tr>
        <td>${item.servidor}</td>
        <td>${item.clientes_asignados}</td>
        <td>${item.peso_configurado}</td>
      </tr>`;
      tablaCarga.innerHTML += row;
    });

    // Lista de eventos
    const listaEventos = document.getElementById("lista-eventos");
    listaEventos.innerHTML = "";
    stats.ultimos_eventos.forEach(ev => {
      const item = document.createElement("li");
      const fecha = new Date(ev.timestamp).toLocaleString();
      item.textContent = `${ev.host}: ${ev.tipo_evento} (${fecha})`;
      listaEventos.appendChild(item);
    });
  } catch (err) {
    console.error("Error cargando estadísticas:", err);
  }
}


async function cargarEstadisticasConRutas() {
  try {
    const res = await fetch("/stats/combined_stats");
    const stats = await res.json();

    // Tabla para mostrar las estadísticas combinadas
    const tablaEstadisticas = document.getElementById("tabla-estadisticas");
    tablaEstadisticas.innerHTML = "";  

    // Encabezados de la tabla
    tablaEstadisticas.innerHTML = `
      <thead>
        <tr>
          <th class="py-2 px-4 border-b bg-gray-50 text-left text-xs font-semibold text-gray-600 uppercase">Host Origen</th>
          <th class="py-2 px-4 border-b bg-gray-50 text-left text-xs font-semibold text-gray-600 uppercase">Host Destino</th>
          <th class="py-2 px-4 border-b bg-gray-50 text-left text-xs font-semibold text-gray-600 uppercase">Ruta</th>
          <th class="py-2 px-4 border-b bg-gray-50 text-left text-xs font-semibold text-gray-600 uppercase">Algoritmo</th>
          <th class="py-2 px-4 border-b bg-gray-50 text-left text-xs font-semibold text-gray-600 uppercase">RTT (ms)</th>
          <th class="py-2 px-4 border-b bg-gray-50 text-left text-xs font-semibold text-gray-600 uppercase">Jitter (ms)</th>
        </tr>
      </thead>
      <tbody>
    `;

    // Filas de la tabla
    stats.forEach(item => {
      const row = `
        <tr>
          <td class="py-2 px-4">${item.host_origen}</td>
          <td class="py-2 px-4">${item.host_destino}</td>
          <td class="py-2 px-4">${item.ruta}</td>
          <td class="py-2 px-4">${item.algoritmo_enrutamiento}</td>
          <td class="py-2 px-4">${item.rtt}</td>
          <td class="py-2 px-4">${item.jitter || "N/A"}</td>
        </tr>
      `;
      tablaEstadisticas.innerHTML += row;
    });

    tablaEstadisticas.innerHTML += "</tbody>";

  } catch (err) {
    console.error("Error cargando estadísticas combinadas:", err);
  }
}

async function cargarComparacionAlgoritmos() {
  try {
    const res = await fetch("/stats/comparar_algoritmos");
    const data = await res.json();

    // Obtener los datos para el gráfico
    const labels = ['RTT (ms)', 'Jitter (ms)'];
    const dijkstraData = [data.dijkstra.avg_rtt, data.dijkstra.avg_jitter];
    const shortestPathData = [data.shortest_path.avg_rtt, data.shortest_path.avg_jitter];

    // Crear el gráfico
    const ctx = document.getElementById("comparacionAlgoritmosChart").getContext("2d");
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Dijkstra',
            data: dijkstraData,
            backgroundColor: 'rgba(54, 162, 235, 0.5)',
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 1
          },
          {
            label: 'Shortest Path',
            data: shortestPathData,
            backgroundColor: 'rgba(255, 99, 132, 0.5)',
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 1
          }
        ]
      },
      options: {
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              stepSize: 1
            }
          }
        },
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: 'Comparación de Algoritmos (RTT y Jitter)'
          },
          legend: {
            position: 'top'
          }
        }
      }
    });
  } catch (err) {
    console.error("Error al cargar la comparación de algoritmos:", err);
  }
}

document.addEventListener("DOMContentLoaded", cargarComparacionAlgoritmos);
document.getElementById("tabla-estadisticas").innerHTML = "<p>Cargando estadísticas...</p>";
cargarEstadisticasConRutas();


document.addEventListener("DOMContentLoaded", cargarEstadisticas);
