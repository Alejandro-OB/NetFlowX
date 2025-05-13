let chartInstance;

// Función para alternar entre pestañas
function mostrarPestaña(pestañaId, tabElement) {
  document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active-content'));
  document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
  document.getElementById(pestañaId).classList.add('active-content');
  tabElement.classList.add('active');
}


function toggleDarkMode() {
  document.body.classList.toggle("dark-mode");
  document.querySelectorAll('.card, .btn, .form-control, .table').forEach(element => {
      element.classList.toggle("dark-mode");
  });
}

async function obtenerLogs() {
  try {
      const respuesta = await fetch(`http://localhost:5000/reglas/logs`);
      if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);
      const data = await respuesta.json();

      const tabla = $('#tablaLogs').DataTable();
      tabla.clear();

      data.forEach(log => {
          tabla.row.add([
              `<span>${log.id}</span>`,
              `<span>${log.timestamp}</span>`,
              `<span>${log.dpid}</span>`,
              `<span>${log.rule_id}</span>`,
              `<span>${log.action}</span>`,
              `<span>Priority: ${log.priority}, IP Src: ${log.ipv4_src}, IP Dst: ${log.ipv4_dst}</span>`
          ]);
      });

      tabla.draw();
  } catch (error) {
      console.error("Error al obtener los registros:", error);
  }
}




async function obtenerMaxRuleID() {
  const apiUrl = `http://localhost:5000/reglas/max_rule_id`;
  try {
      const respuesta = await fetch(apiUrl);
      if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);
      const data = await respuesta.json();
      return data.next_rule_id || Date.now();  // ✅ Si falla, usa un ID basado en el tiempo
  } catch (error) {
      console.error("Error al obtener max_rule_id:", error);
      return Date.now();  // ✅ Nunca devuelve `null`, evitando fallos en agregarRegla()
  }
}
async function cargarReglaParaModificar() {
    const rule_id = document.getElementById("mod_rule_id").value.trim();
    if (!rule_id) {
        alert("Ingrese un Rule ID para cargar los datos.");
        return;
    }

    try {
        const respuesta = await fetch(`http://localhost:5000/reglas/buscar/${rule_id}`);
        if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);
        const regla = await respuesta.json();

        // ✅ Llenar los campos del formulario con los datos actuales
        document.getElementById("mod_priority").value = regla.priority || "";
        document.getElementById("mod_eth_type").value = regla.eth_type || "";
        document.getElementById("mod_ip_proto").value = regla.ip_proto || "";
        document.getElementById("mod_ipv4_src").value = regla.ipv4_src || "";
        document.getElementById("mod_ipv4_dst").value = regla.ipv4_dst || "";
        document.getElementById("mod_tcp_src").value = regla.tcp_src || "";
        document.getElementById("mod_tcp_dst").value = regla.tcp_dst || "";
        document.getElementById("mod_in_port").value = regla.in_port || "";

        // ✅ Manejo de acciones
        if (regla.actions && regla.actions.length > 0) {
            const primeraAccion = regla.actions[0];
            document.getElementById("mod_actions").value = primeraAccion.type || "";
            if (primeraAccion.type === "OUTPUT" && primeraAccion.port) {
                document.getElementById("mod_out_port").value = primeraAccion.port;
                document.getElementById("mod_out_port").disabled = false;
            } else {
                document.getElementById("mod_out_port").value = "";
                document.getElementById("mod_out_port").disabled = true;
            }
        } else {
            document.getElementById("mod_actions").value = "";
            document.getElementById("mod_out_port").value = "";
            document.getElementById("mod_out_port").disabled = true;
        }

        alert("Datos cargados correctamente. Ahora puede modificar los campos necesarios.");
    } catch (error) {
        console.error("Error al cargar la regla:", error);
        alert("No se encontró la regla o ocurrió un error.");
    }
}


function validarAccionModificar() {
    const action = document.getElementById("mod_actions").value;
    const outPort = document.getElementById("mod_out_port");

    if (action === "OUTPUT") {
        outPort.disabled = false;
        outPort.placeholder = "Ingrese el puerto de salida";
    } else {
        outPort.disabled = true;
        outPort.value = ""; // Se limpia el campo si no es OUTPUT
        outPort.placeholder = "No requerido";
    }
}

function validarAccionAgregar() {
    const action = document.getElementById("actions").value;
    const outPort = document.getElementById("out_port");

    outPort.disabled = action !== "OUTPUT";
    outPort.placeholder = outPort.disabled ? "No requerido" : "Ingrese el puerto de salida";
}

const validarNumero = (valor, min, max, mensajeError) => {
    if (valor !== undefined) {
        const numero = parseInt(valor, 10);
        if (isNaN(numero) || numero < min || (max !== undefined && numero > max)) {
            alert(mensajeError);
            return null;
        }
        return numero;
    }
    return undefined;
};

function validarIP(ip) {
    const regex = /^(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3}$/;
    return regex.test(ip);
}

async function obtenerReglas() {
  try {
      const respuesta = await fetch(`http://localhost:5000/reglas`);
      if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);

      const data = await respuesta.json();
      const tabla = $('#tablaReglas').DataTable();
      tabla.clear();
      console.log("Datos recibidos:", data);
      if (data.switches && Array.isArray(data.switches)) {
          const tabla = $('#tablaReglas').DataTable();
          tabla.clear();
      
          data.switches.forEach(regla => {
              let acciones;
              try {
                  if (typeof regla.actions === "string") {
                      if (regla.actions.startsWith("{") || regla.actions.startsWith("[")) {
                          acciones = JSON.parse(regla.actions);
                      } else {
                          console.warn("Formato no válido en actions:", regla.actions);
                          acciones = [];
                      }
                  } else {
                      acciones = regla.actions;
                  }
              } catch (error) {
                  console.error("Error al parsear actions:", error, "Valor recibido:", regla.actions);
                  acciones = [];
              }
      
              let accionesFormateadas = acciones.map(a => {
                  if (a.type === "OUTPUT") {
                      return `OUTPUT → Puerto ${a.port}`;
                  } else if (a.type === "DROP") {
                      return "DROP";
                  } else if (a.type === "NORMAL") {
                      return "NORMAL";
                  }
                  return JSON.stringify(a);
              }).join(", ");
      
              tabla.row.add([
                  regla.id || "-",
                  regla.dpid,
                  regla.rule_id,
                  accionesFormateadas,
                  regla.priority || "N/A",
                  `${regla.ipv4_src || "-"} → ${regla.ipv4_dst || "-"}`,
                  new Date().toLocaleString()
              ]);
          });
      
          tabla.draw();
      } else {
          // Si no hay reglas o no se encuentran switches, muestra un mensaje adecuado
          console.log("No se encontraron reglas o switches");
          //alert("No hay reglas registradas.");
      }

      tabla.draw();
  } catch (error) {
      console.error("Error al obtener reglas:", error);
  }
}



async function agregarRegla() {
  const getInputValue = (id) => {
      const element = document.getElementById(id);
      return element && element.value.trim() !== "" ? element.value : undefined;
  };

  const dpid = getInputValue('dpid');
  if (!dpid) {
      Swal.fire("⚠️ Error", "Debe ingresar un DPID.", "warning");
      return;
  }

  let rule_id = getInputValue('rule_id') || await obtenerMaxRuleID();
  const ipv4_src = getInputValue('ipv4_src');
  const ipv4_dst = getInputValue('ipv4_dst');

  if (ipv4_src && !validarIP(ipv4_src)) {
      Swal.fire("⚠️ Error", "La dirección IP de origen no es válida.", "warning");
      return;
  }
  if (ipv4_dst && !validarIP(ipv4_dst)) {
      Swal.fire("⚠️ Error", "La dirección IP de destino no es válida.", "warning");
      return;
  }

  // 🔹 Validar números (evitar valores inválidos o negativos)
  const priority = validarNumero(getInputValue('priority'), 0, undefined, "La prioridad debe ser un número positivo.");
  const in_port = validarNumero(getInputValue('in_port'), 0, undefined, "El puerto de entrada debe ser un número positivo.");

  const eth_type = validarNumero(getInputValue('eth_type'), 0, 65535, "El tipo de protocolo Ethernet debe estar entre 0 y 65535.");
  const ip_proto = validarNumero(getInputValue('ip_proto'), 0, 255, "El protocolo de red debe estar entre 0 y 255.");

  const tcp_src = validarNumero(getInputValue('tcp_src'), 0, 65535, "El puerto TCP de origen debe estar entre 0 y 65535.");
  const tcp_dst = validarNumero(getInputValue('tcp_dst'), 0, 65535, "El puerto TCP de destino debe estar entre 0 y 65535.");

  const actionType = getInputValue('actions');
  let out_port = getInputValue('out_port');

  if (!actionType) {
      Swal.fire("⚠️ Error", "Debe seleccionar una acción.", "warning");
      return;
  }

  let actions = [];
  if (actionType === "OUTPUT") {
      if (!out_port || isNaN(out_port) || parseInt(out_port, 10) < 0) {
          Swal.fire("⚠️ Error", "Debe ingresar un puerto de salida válido para OUTPUT.", "warning");
          return;
      }
      actions.push({ type: "OUTPUT", port: parseInt(out_port, 10) });
  } else {
      actions.push({ type: actionType });
  }

  // 🔹 Construir la regla sin valores vacíos
  let regla = {
      rule_id,
      priority,
      eth_type,
      ip_proto,
      ipv4_src,
      ipv4_dst,
      in_port,
      tcp_src,
      tcp_dst,
      actions: actions.length > 0 ? actions : undefined  // No incluir si está vacío
  };

  // 🔹 Eliminar valores `undefined` antes de enviarlos
  regla = Object.fromEntries(Object.entries(regla).filter(([_, v]) => v !== undefined));

  try {
      Swal.fire({ title: "Procesando...", allowOutsideClick: false, didOpen: () => Swal.showLoading() });

      const respuesta = await fetch(`http://localhost:5000/reglas/${dpid}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(regla)
      });

      if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);

      Swal.fire("✅ Éxito", "Regla añadida con éxito.", "success");
      obtenerReglas(); // Refrescar tabla
  } catch (error) {
      console.error("Error al agregar la regla:", error);
      Swal.fire("❌ Error", `Error al agregar la regla: ${error.message}`, "error");
  }
}


async function modificarRegla() {
  const getInputValue = (id) => {
      const element = document.getElementById(id);
      return element && element.value.trim() !== "" ? element.value : undefined;
  };

  const validarNumero = (valor, min, max, mensajeError) => {
      if (valor !== undefined) {
          const numero = parseInt(valor, 10);
          if (isNaN(numero) || numero < min || (max !== undefined && numero > max)) {
              Swal.fire("⚠️ Error", mensajeError, "warning");
              return null;
          }
          return numero;
      }
      return undefined;
  };

  const rule_id = getInputValue('mod_rule_id');
  if (!rule_id) {
      Swal.fire("⚠️ Error", "Debe ingresar un ID de regla para modificarla.", "warning");
      return;
  }

  // ✅ **Consultar la regla existente antes de modificarla**
  let reglaExistente;
  try {
      const consulta = await fetch(`http://localhost:5000/reglas/buscar/${rule_id}`);
      if (!consulta.ok) throw new Error(`Error HTTP: ${consulta.status}`);
      reglaExistente = await consulta.json();
  } catch (error) {
      console.error("Error al obtener la regla:", error);
      Swal.fire("❌ Error", `No se encontró la regla para modificar: ${error.message}`, "error");
      return;
  }

  // ✅ **Solo modificar los campos proporcionados**
  let reglaModificada = {
      priority: validarNumero(getInputValue('mod_priority'), 0, undefined, "La prioridad debe ser un número entero positivo."),
      eth_type: validarNumero(getInputValue('mod_eth_type'), 0, 65535, "El tipo de protocolo Ethernet debe estar entre 0 y 65535."),
      ip_proto: validarNumero(getInputValue('mod_ip_proto'), 0, 255, "El protocolo de red debe estar entre 0 y 255."),
      ipv4_src: getInputValue('mod_ipv4_src'),
      ipv4_dst: getInputValue('mod_ipv4_dst'),
      tcp_src: validarNumero(getInputValue('mod_tcp_src'), 0, 65535, "El puerto TCP de origen debe estar entre 0 y 65535."),
      tcp_dst: validarNumero(getInputValue('mod_tcp_dst'), 0, 65535, "El puerto TCP de destino debe estar entre 0 y 65535."),
      in_port: validarNumero(getInputValue('mod_in_port'), 0, undefined, "El puerto de entrada debe ser un número positivo."),
  };

  // ✅ **Eliminar valores `undefined`, `null` o `""` antes de enviar**
  reglaModificada = Object.fromEntries(Object.entries(reglaModificada).filter(([_, v]) => v !== undefined));

  // ✅ **Manejo de acciones**
  const actionType = getInputValue('mod_actions');
  let actions = reglaExistente.actions ? (Array.isArray(reglaExistente.actions) ? reglaExistente.actions : JSON.parse(reglaExistente.actions)) : [];

  if (actionType) {
      actions = []; // Vaciar las acciones si se selecciona una nueva
      switch (actionType) {
          case "NORMAL":
              actions.push({ type: "NORMAL" });
              break;
          case "OUTPUT":
              const out_port = validarNumero(getInputValue('mod_out_port'), 0, undefined, "El puerto de salida debe ser un número positivo.");
              if (out_port === null) return;
              actions.push({ type: "OUTPUT", port: out_port });
              break;
          case "DROP":
              actions.push({ type: "DROP" });
              break;
          default:
              const confirmacion = await Swal.fire({
      title: "¿Eliminar Regla?",
      text: `¿Está seguro de que desea eliminar la regla con ID ${rule_id}?`,
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#d33",
      cancelButtonColor: "#3085d6",
      confirmButtonText: "Sí, eliminar",
      cancelButtonText: "Cancelar"
  });al.fire("⚠️ Error", "Acción no válida.", "warning");
              return;
      }
  }

  if (actions.length > 0) {
      reglaModificada.actions = actions;  // ✅ Ya es un array, no se usa JSON.stringify aquí
  }

  // ✅ **Verificar si hay cambios antes de enviar**
  if (Object.keys(reglaModificada).length === 0) {
      Swal.fire("⚠️ Advertencia", "No ha modificado ningún campo.", "warning");
      return;
  }

  try {
      Swal.fire({ title: "Procesando...", allowOutsideClick: false, didOpen: () => Swal.showLoading() });

      const apiUrl = `http://localhost:5000/reglas/modificar`;
      console.log(`📌 Enviando PUT a: ${apiUrl}/${rule_id}`);

      const respuesta = await fetch(`${apiUrl}/${parseInt(rule_id, 10)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reglaModificada)
      });

      if (!respuesta.ok) {
          const errorMsg = await respuesta.text();
          throw new Error(`Error HTTP: ${respuesta.status} - ${errorMsg}`);
      }

      const data = await respuesta.json();  // ✅ Esto procesará correctamente la respuesta del servidor
      Swal.fire("✅ Éxito", "Regla modificada con éxito.", "success");
      obtenerReglas(); // ✅ Refrescar la tabla automáticamente
  } catch (error) {
      console.error("Error al modificar la regla:", error);
      Swal.fire("❌ Error", `Error al modificar la regla: ${error.message}`, "error");
  }
}

async function eliminarRegla() {
  const rule_id = document.getElementById('del_rule_id').value.trim();
  if (!rule_id) {
      Swal.fire("⚠️ Error", "Debe ingresar un Rule ID.", "warning");
      return;
  }

  const confirmacion = await Swal.fire({
      title: "¿Eliminar Regla?",
      text: `¿Está seguro de que desea eliminar la regla con ID ${rule_id}?`,
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#d33",
      cancelButtonColor: "#3085d6",
      confirmButtonText: "Sí, eliminar",
      cancelButtonText: "Cancelar"
  });

  if (!confirmacion.isConfirmed) return;

  try {
      Swal.fire({ title: "Procesando...", allowOutsideClick: false, didOpen: () => Swal.showLoading() });

      const respuesta = await fetch(`http://localhost:5000/reglas/eliminar/${rule_id}`, { method: 'DELETE' });
      if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);

      Swal.fire("✅ Eliminado", "Regla eliminada con éxito.", "success");
      obtenerReglas(); // Refrescar la tabla automáticamente
  } catch (error) {
      console.error("Error al eliminar la regla:", error);
      Swal.fire("❌ Error", `Error al eliminar la regla: ${error.message}`, "error");
  }
}

async function buscarRegla() {
  const rule_id = document.getElementById('search_rule_id').value.trim();
  if (!rule_id) {
      Swal.fire("⚠️ Error", "Debe ingresar un Rule ID para buscar.", "warning");
      return;
  }

  const apiUrl = `http://localhost:5000/reglas/buscar/${rule_id}`;

  try {
      Swal.fire({ title: "Buscando...", allowOutsideClick: false, didOpen: () => Swal.showLoading() });

      const respuesta = await fetch(apiUrl);
      if (!respuesta.ok) throw new Error(`Error HTTP: ${respuesta.status}`);

      const data = await respuesta.json();
      Swal.fire("✅ Regla Encontrada", `<pre style="text-align:left">${JSON.stringify(data, null, 4)}</pre>`, "info");

      document.getElementById('resultadoBusqueda').innerText = JSON.stringify(data, null, 4);
  } catch (error) {
      console.error("Error al buscar la regla:", error);
      Swal.fire("❌ Error", "No se encontró la regla o hubo un error.", "error");
  }
}

async function generarGrafico() {
  try {
      const respuesta = await fetch(`http://localhost:5000/reglas`);
      const data = await respuesta.json();

      // Verificar si existen reglas
      if (!data.switches || data.switches.length === 0) {
          console.log("No se encontraron reglas para generar el gráfico.");
          //alert("No hay reglas registradas para generar el gráfico.");
          return; // No proceder si no hay reglas
      }

      // Contar reglas por switch
      const switches = {};
      data.switches.forEach(regla => {
          switches[regla.dpid] = (switches[regla.dpid] || 0) + 1;
      });

      // Si ya existe un gráfico, destruirlo antes de crear uno nuevo
      if (chartInstance) {
          chartInstance.destroy();
      }

      // Crear nuevo gráfico
      chartInstance = new Chart(document.getElementById("graficoReglas"), {
          type: "bar",
          data: {
              labels: Object.keys(switches),
              datasets: [{
                  label: "Reglas por Switch",
                  data: Object.values(switches),
                  backgroundColor: "blue"
              }]
          }
      });
  } catch (error) {
      console.error("Error al generar el gráfico:", error);
  }
}


$(document).ready(function () {
  $('#tablaReglas').DataTable();
  $('#tablaLogs').DataTable({
          paging: true,
          searching: true,
          ordering: true,
          responsive: true,
          language: {
              url: "https://raw.githubusercontent.com/DataTables/Plugins/master/i18n/es-ES.json"
          }
      });
  obtenerReglas();
  generarGrafico();
  obtenerLogs();
});