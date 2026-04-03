Para implementar la arquitectura segura que describe tu documento y crear una imagen de Docker reutilizable que sirva como puente entre **Google Antigravity** y la infraestructura de  **Dokploy** , dividiremos el proyecto en 5 pasos fundamentales.

Utilizaremos **Python** y el SDK de MCP (`FastMCP`), ya que ofrece un excelente soporte para interacciones nativas con bases de datos y la API del socket de Docker, además de manejar el transporte **Server-Sent Events (SSE)** de forma eficiente.

A continuación, te presento la guía paso a paso, la estructura de directorios y el código necesario.

### Estructura General del Proyecto

Para que tu proyecto sea fácil de empaquetar, mantener y distribuir (por ejemplo, en Docker Hub o GitHub Container Registry), te sugiero esta estructura:

**Plaintext**

```
mcp-dokploy-bridge/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── src/
│   └── server.py           # Servidor MCP y herramientas (Tools)
└── bridge/
    └── local_bridge.sh     # Script para el patrón alternativo "Local Bridge"
```

---

### Paso 1: Definir las Dependencias (`requirements.txt`)

Necesitaremos el SDK de MCP, los clientes para Docker y PostgreSQL, y el servidor web para soportar el flujo HTTP/SSE.

**Plaintext**

```
mcp[cli]
fastapi
uvicorn
docker
psycopg2-binary
```

---

### Paso 2: Desarrollar el Servidor MCP (`src/server.py`)

Este código define las herramientas (Tools) que la IA podrá usar. Aplica estrictamente los **Server-Side Guardrails** mencionados en tu documento: fuerza consultas de solo lectura y expone únicamente las operaciones pasivas (observabilidad) para el socket de Docker.

**Python**

```
import os
import re
import argparse
import docker
import psycopg2
from psycopg2.extras import RealDictCursor
from mcp.server.fastmcp import FastMCP

# Parsear argumentos de línea de comandos requeridos por la arquitectura
parser = argparse.ArgumentParser()
parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"])
parser.add_argument("--access-mode", default="restricted", choices=["restricted", "admin"])
args = parser.parse_args()

# Inicializar el servidor
mcp = FastMCP("Dokploy-Mission-Control", host="0.0.0.0", port=8000)

# Cargar clientes de infraestructura
DB_URI = os.getenv("DATABASE_URI")
try:
    docker_client = docker.from_env()
except Exception as e:
    docker_client = None

# --- 1. HERRAMIENTAS DE BASE DE DATOS ---
@mcp.tool()
def query_database(query: str) -> str:
    """Ejecuta una consulta SQL a la base de datos interna de Dokploy."""
    if not DB_URI: return "Error: DATABASE_URI no configurada."
  
    # GUARDRAIL: Bloqueo de operaciones destructivas en modo restringido
    if args.access_mode == "restricted":
        forbidden_sql = re.compile(r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE)\b', re.IGNORECASE)
        if forbidden_sql.search(query):
            return "ERROR DE SEGURIDAD: Operación bloqueada. Solo se permiten consultas SELECT (Access-Mode: Restricted)."
  
    try:
        # Refuerzo a nivel de conexión a la BD
        with psycopg2.connect(DB_URI) as conn:
            conn.set_session(readonly=True) 
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                # Límite de resultados para no saturar la ventana de contexto del LLM
                return str(cur.fetchmany(100))
    except Exception as e:
        return f"Error en base de datos: {str(e)}"

# --- 2. HERRAMIENTAS DE TELEMETRÍA (DOCKER SOCKET) ---
@mcp.tool()
def docker_list_containers() -> str:
    """Descubre y enumera todos los contenedores en la red asilada de Dokploy."""
    if not docker_client: return "API de Docker no disponible."
    try:
        containers = docker_client.containers.list()
        return "\n".join([f"ID: {c.short_id} | Name: {c.name} | Status: {c.status}" for c in containers])
    except Exception as e:
        return f"Docker Error: {str(e)}"

@mcp.tool()
def docker_get_logs(container_name: str, tail: int = 200) -> str:
    """Obtiene el flujo de logs de un contenedor específico para debuggear caídas."""
    if not docker_client: return "API de Docker no disponible."
    try:
        container = docker_client.containers.get(container_name)
        logs = container.logs(tail=tail, stdout=True, stderr=True)
        return logs.decode('utf-8', errors='replace')
    except Exception as e:
         return f"Error leyendo logs: {str(e)}"

if __name__ == "__main__":
    if args.transport == "sse":
        print("Iniciando MCP Server en modo Streamable HTTP (SSE) por el puerto 8000...")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
```

---

### Paso 3: Construcción de la Imagen (`Dockerfile`)

Empaquetamos el servidor en una imagen ligera basada en Debian/Python. De acuerdo con las buenas prácticas, eliminaremos privilegios usando `cap_drop` más adelante en el entorno de Compose, pero aquí preparamos la ejecución estándar.

**Dockerfile**

```
FROM python:3.11-slim

# Evitar escritura de bytecode y forzar logs sin buffer
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema para compilar psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Exponer el puerto para las conexiones remotas SSE
EXPOSE 8000

# Punto de entrada y paso de los flags descritos en el documento
ENTRYPOINT ["python", "src/server.py"]
CMD ["--transport=sse", "--access-mode=restricted"]
```

*(Para hacerla pública, simplemente compila y sube: `docker build -t tuusuario/dokploy-mcp:latest .` y luego `docker push tuusuario/dokploy-mcp:latest`)*

---

### Paso 4: Arquitectura de Despliegue en Dokploy (`docker-compose.yml`)

Este es el archivo que se usará en Dokploy para instanciar tu imagen dentro de los "Isolated Deployments". Aquí se aplica el perímetro de seguridad mediante **Traefik** (BasicAuth con escape `$$`), credenciales internas y el  **socket montado en solo lectura (`:ro`)** .

**YAML**

```
version: '3.8'

services:
  # Base de datos aislada (sin exponer "ports:" al exterior)
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: supersecretpassword
      POSTGRES_DB: appdb

  # Tu contenedor puente MCP
  mcp-server:
    image: tuusuario/dokploy-mcp:latest # Tu imagen publicada
    environment:
      # Conecta usando la resolución DNS interna de Docker Compose
      - DATABASE_URI=postgresql://admin:supersecretpassword@db:5432/appdb
    volumes:
      # CRÍTICO: Montaje del control plane en modo estricto SOLO LECTURA
      - /var/run/docker.sock:/var/run/docker.sock:ro
    cap_drop:
      # Elimina todas las "Linux Capabilities" para prevenir escapes
      - ALL
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.mcp-router.rule=Host(`mcp.tudominio.com`)"
      - "traefik.http.routers.mcp-router.entrypoints=websecure"
      - "traefik.http.routers.mcp-router.tls.certresolver=letsencrypt"
    
      # PERÍMETRO DE SEGURIDAD: Middleware de autenticación básica
      - "traefik.http.routers.mcp-router.middlewares=mcp-auth"
      # IMPORTANTE: En Docker Compose, los hashes ($) deben escaparse con dobles signos ($$)
      # Ejemplo para usuario 'antigravity' y contraseña generada con htpasswd:
      - "traefik.http.middlewares.mcp-auth.basicauth.users=antigravity:$$apr1$$xY1zZ...$$/HashEscapadoAqui"
```

---

### Paso 5: Integración y Client-Side Governance (Google Antigravity)

Una vez desplegada, quien vaya a utilizar tu imagen tiene dos rutas de integración descritas en tu documento para el archivo `~/.gemini/antigravity/mcp_config.json`.

#### Opción A: Configuración SSE Directa

Si la inyección de encabezados de Antigravity es estable:

**JSON**

```
{
  "mcpServers": {
    "DokployRemote": {
      "transport": "sse",
      "serverUrl": "https://mcp.tudominio.com/sse",
      "headers": {
        "Authorization": "Basic YW50aWdyYXZpdHk6bWlfcGFzc3dvcmQ=" 
      },
      "executionPolicy": "Request review"
    }
  }
}
```

*(Nota: El string en Base64 corresponde a `antigravity:mi_password`. La política "Request review" restringe la autonomía del agente).*

#### Opción B: The Local Bridge Pattern (Recomendado como fallback)

Si existen problemas de CORS o limitantes nativas del IDE al inyectar headers en la conexión SSE, el usuario puede descargar tu script puente (`bridge/local_bridge.sh`) en su máquina.

**`local_bridge.sh`** (Se ejecuta en la PC local del usuario)

**Bash**

```
#!/bin/bash
# Traduce la comunicación remota SSE hacia un flujo de entrada local (stdio)
# Utiliza una CLI de conexión puente (ej. mcp-remote)
mcp-remote \
  --url "https://mcp.tudominio.com/sse" \
  --auth "Basic YW50aWdyYXZpdHk6bWlfcGFzc3dvcmQ="
```

En Antigravity, la configuración local pasa a ser puramente `stdio`, ignorando la complejidad de la red:

**JSON**

```
{
  "mcpServers": {
    "DokployBridge": {
      "command": "/bin/bash",
      "args": ["/ruta/absoluta/al/local_bridge.sh"],
      "executionPolicy": "Auto"
    }
  }
}
```

### Síntesis

Con esta imagen disponible, si un contenedor de una aplicación se cae, el arquitecto solo debe decirle a Antigravity: *"El servicio web está fallando en Dokploy. Revisa los logs y comprueba si hay conflictos en la BD."*

De forma autónoma, el Agente atravesará de forma segura el perímetro de Traefik (vía SSE), accederá a la telemetría usando el daemon local de Docker, ejecutará `SELECT` autorizados, y finalmente generará un *Artifact* con el diagnóstico en el IDE, completando la visión **Agent-First** del documento de manera 100% segura.
