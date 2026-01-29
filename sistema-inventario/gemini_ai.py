import json
import requests
import time

# La clave API se deja vacía. El entorno de Canvas la proporcionará en tiempo de ejecución.
API_KEY = "AIzaSyBedd71jCaL09QmTJS7bIViy6Udh0ZT4rc"
MODEL_NAME = "gemini-2.5-flash-preview-09-2025"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"

# =========================================
# FUNCIÓN DE ANÁLISIS DEL INVENTARIO (CORREGIDA)
# =========================================
def analizar_inventario(contexto_json, prompt_usuario):
    """
    Recibe el contexto de la BD en JSON y el prompt del usuario.
    Llama a la API de Gemini para un análisis narrativo.
    """
    print("Iniciando análisis de inventario con Gemini...")

    # 1. Definir el rol y las instrucciones para la IA (System Instruction)
    # Basado en tu inventario_db.sql
    system_instruction = """
    Eres un Director de Operaciones (COO) experto en análisis de inventario y ventas para una empresa minorista.
    Tu trabajo es analizar un contexto de datos en formato JSON que te proporcionaré y responder a la pregunta del usuario.

    ESTRUCTURA DEL CONTEXTO JSON QUE RECIBIRÁS (BASADO EN inventario_db.sql):
    - 'productos': La lista maestra de productos. 'productos.precio' es el PRECIO DE VENTA final. 'productos.cantidad' es el STOCK GLOBAL TOTAL.
    - 'locales': La lista de locales y bodegas (tipo='bodega' o tipo='local').
    - 'inventario_por_local': El stock detallado ('cantidad') de cada producto en cada local.
    - 'ventas_recientes': Las últimas 100 transacciones. 'detalle_ventas.precio_venta' es el precio real al que se vendió.
    - 'compras_recientes': Las últimas 100 compras a proveedores. 'compras.precio_compra' es el COSTO de adquisición del producto.
    - 'transferencias_recientes': Movimientos de stock entre locales.

    REGLAS PARA TU RESPUESTA:
    1.  Responde SIEMPRE en formato narrativo, amigable y profesional.
    2.  NUNCA devuelvas solo una tabla o datos JSON. Interpreta los datos.
    3.  Usa los datos de 'ventas_recientes' y 'compras_recientes' para inferir rentabilidad (precio_venta vs precio_compra) si el usuario lo pregunta.
    4.  Usa 'inventario_por_local' y 'ventas_recientes' para identificar 'stock crítico' (productos que se venden rápido y tienen poco stock).
    5.  Basa TODAS tus conclusiones únicamente en el contexto de datos proporcionado.
    """

    # 2. Construir el Payload para la API
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"Contexto de la Base de Datos (en JSON):\n{contexto_json}\n\nPregunta del Usuario:\n{prompt_usuario}"}
                ]
            }
        ],
        "systemInstruction": {
            "parts": [
                {"text": system_instruction}
            ]
        },
        "generationConfig": {
            "temperature": 0.5,
            "topK": 1,
            "topP": 1,
            "maxOutputTokens": 2048,
        }
    }

    # 3. Llamar a la API de Gemini con reintentos (Exponential Backoff)
    max_retries = 3
    delay = 1
    for attempt in range(max_retries):
        try:
            # Enviamos la solicitud a la API de Gemini
            response = requests.post(API_URL, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
            
            # Si la respuesta fue exitosa (código 200)
            if response.status_code == 200:
                response_data = response.json()
                
                # Extraer el texto de la respuesta (la respuesta)
                if (response_data.get('candidates') and 
                    response_data['candidates'][0].get('content') and 
                    response_data['candidates'][0]['content'].get('parts')):
                    
                    # Aquí se obtiene el texto final
                    text_response = response_data['candidates'][0]['content']['parts'][0]['text']
                    print("Análisis de Gemini recibido exitosamente.")
                    return text_response
                else:
                    # Caso donde Gemini bloquea la respuesta o está vacía
                    print("Respuesta de Gemini bloqueada o vacía:", response_data)
                    return f"El modelo no pudo generar una respuesta. Razón: {response_data.get('promptFeedback', {}).get('blockReason', 'Desconocida')}"

            else:
                # Si la API devuelve error (por ejemplo, 429 o 503)
                print(f"Error en la API de Gemini (Intento {attempt + 1}): {response.status_code} - {response.text}")
                if response.status_code in [429, 500, 503]:
                    # Error de servidor o límite de tasa, reintentar
                    time.sleep(delay)
                    delay *= 2
                else:
                    # Error de cliente (ej. 400), no reintentar
                    return f"Error en la solicitud a la API: {response.text}"
        
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión (Intento {attempt + 1}): {e}")
            time.sleep(delay)
            delay *= 2

    print("Error: Se superaron los reintentos para contactar a la API de Gemini.")
    return "Error: No se pudo contactar al servicio de análisis después de varios intentos."