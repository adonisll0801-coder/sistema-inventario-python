from google import genai
import os

# Tu clave API válida
client = genai.Client(api_key="AIzaSyBedd71jCaL09QmTJS7bIViy6Udh0ZT4rc")

print("📋 Modelos disponibles en tu cuenta Gemini:\n")

# Recorre directamente el pager
for model in client.models.list():
    print(f"- {model.name}")

