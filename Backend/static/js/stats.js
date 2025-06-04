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

    const maxClientes = Math.max(...stats.clientes_por_servidor.map(s => s.total_clientes), 1);

    stats.clientes_por_servidor.forEach(item => {
      const contenedor = document.createElement("div");
      contenedor.className = "barra-contenedor";

      const barra = document.createElement("div");
      barra.className = "barra-servidor";
      barra.style.width = `${(item.total_clientes / maxClientes) * 100}%`;
      barra.textContent = `${item.servidor} (${item.total_clientes})`;

      contenedor.appendChild(barra);
      grafico.appendChild(contenedor);
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

document.addEventListener("DOMContentLoaded", cargarEstadisticas);
