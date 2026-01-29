import mysql.connector
from mysql.connector import Error
import os

def get_connection():
    """
    Crea y devuelve una conexión a la base de datos MySQL.
    """
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", "123456"), 
            database=os.getenv("DB_NAME", "inventario_db")
        )

        if connection.is_connected():
            print("✅ Conexión a MySQL establecida correctamente.")
            return connection

    except Error as e:
        print("❌ Error al conectar a MySQL:", e)
        return None
