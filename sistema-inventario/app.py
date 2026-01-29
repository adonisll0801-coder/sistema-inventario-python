from flask import Flask, render_template, request, redirect, url_for, flash, session
from db import get_connection
from gemini_ai import analizar_inventario
import json

app = Flask(__name__)

app.secret_key = 'clave123456789'


# ======================================================
#  INICIO 
# ======================================================
@app.route('/')
@app.route('/inicio')
def inicio():
    return render_template('inicio.html')


# ======================================================
#  COMPRAS 
# ======================================================
@app.route('/compras')
def compras():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    #  Traer todas las compras con producto y proveedor
    cursor.execute("""
        SELECT co.id AS id_compra, p.nombre AS producto, p.descripcion,
               co.cantidad, co.precio_compra, co.fecha,
               c.nombre AS categoria, pr.nombre AS proveedor
        FROM compras co
        JOIN productos p ON co.id_producto = p.id
        LEFT JOIN categorias c ON p.id_categoria = c.id
        LEFT JOIN proveedores pr ON co.id_proveedor = pr.id
        ORDER BY co.id DESC
    """)
    compras = cursor.fetchall()

    #  Traer todas las categorías
    cursor.execute("SELECT id, nombre FROM categorias")
    categorias = cursor.fetchall()

    #  Traer todos los proveedores
    cursor.execute("SELECT id, nombre, telefono, email, direccion FROM proveedores")
    proveedores = cursor.fetchall()

    conn.close()
    return render_template(
        'compras/compras.html',
        compras=compras,
        categorias=categorias,
        proveedores=proveedores
    )


# ======================================================
#  AGREGAR PRODUCTO (COMPRAS)
# ======================================================
@app.route('/agregar', methods=['POST'])
def agregar():
    nombre = request.form['nombre']
    precio_compra = float(request.form['precio'])
    descripcion = request.form['descripcion']
    id_categoria = request.form['id_categoria']
    id_proveedor = request.form['id_proveedor']
    cantidad = int(request.form['cantidad'])

    conn = get_connection()
    cursor = conn.cursor()

    # Insertar producto
    cursor.execute("""
        INSERT INTO productos (nombre, precio, descripcion, id_categoria, cantidad)
        VALUES (%s, %s, %s, %s, %s)
    """, (nombre, precio_compra, descripcion, id_categoria, cantidad))
    producto_id = cursor.lastrowid

    # Insertar cantidad inicial en compras
    cursor.execute("""
        INSERT INTO compras (fecha, id_proveedor, id_producto, cantidad, precio_compra)
        VALUES (NOW(), %s, %s, %s, %s)
    """, (id_proveedor, producto_id, cantidad, precio_compra))

    # Obtener ID de la bodega automáticamente
    cursor.execute("SELECT id FROM locales WHERE tipo = 'bodega' LIMIT 1")
    bodega = cursor.fetchone()
    id_bodega = bodega[0] if bodega else None

    # Insertar o actualizar inventario de la bodega
    if id_bodega:
     cursor.execute("""
        INSERT INTO inventario_local (id_local, id_producto, cantidad)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE cantidad = cantidad + VALUES(cantidad)
    """, (id_bodega, producto_id, cantidad))


    
    conn.commit()
    conn.close()
    return redirect(url_for('compras'))


# ======================================================
#  EDITAR PRODUCTO (COMPRAS)
# ======================================================
@app.route('/editar_compra/<int:id>', methods=['GET', 'POST'])
def editar_compra(id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        id_producto = request.form['id_producto']
        id_proveedor = request.form['id_proveedor']
        cantidad = int(request.form['cantidad'])
        precio_compra = float(request.form['precio'])

        #  Actualizar datos en la tabla compras
        cursor.execute("""
            UPDATE compras
            SET id_producto=%s, id_proveedor=%s, cantidad=%s, precio_compra=%s
            WHERE id=%s
        """, (id_producto, id_proveedor, cantidad, precio_compra, id))

        #  Actualizar también en productos (mantener sincronizados)
        cursor.execute("""
            UPDATE productos
            SET cantidad=%s, precio=%s
            WHERE id=%s
        """, (cantidad, precio_compra, id_producto))

        #  Actualizar inventario de la bodega al modificar una compra
        cursor.execute("SELECT id FROM locales WHERE tipo = 'bodega' LIMIT 1")
        bodega = cursor.fetchone()
        id_bodega = bodega['id'] if bodega else None

        registro = None  # 🧩 se inicializa para evitar el error

        if id_bodega:
            # Primero obtenemos la cantidad actual registrada
            cursor.execute("""
                SELECT cantidad FROM inventario_local
                WHERE id_local = %s AND id_producto = %s
            """, (id_bodega, id_producto))
            registro = cursor.fetchone()

            if registro:
                # Si ya existe, actualizamos la cantidad
                cursor.execute("""
                    UPDATE inventario_local
                    SET cantidad = %s
                    WHERE id_local = %s AND id_producto = %s
                """, (cantidad, id_bodega, id_producto))
            else:
                # Si no existe, lo insertamos
                cursor.execute("""
                    INSERT INTO inventario_local (id_local, id_producto, cantidad)
                    VALUES (%s, %s, %s)
                """, (id_bodega, id_producto, cantidad))

        conn.commit()
        conn.close()
        return redirect(url_for('compras'))

    # Obtener la información de la compra, datos cargados
    cursor.execute("""
        SELECT 
            c.id AS id_compra,
            c.id_producto,
            c.id_proveedor,
            c.cantidad,
            c.precio_compra,
            p.nombre AS producto_nombre,
            p.descripcion
        FROM compras c
        LEFT JOIN productos p ON c.id_producto = p.id
        WHERE c.id = %s
    """, (id,))
    compra = cursor.fetchone()

    # Traer opciones para selects
    cursor.execute("SELECT id, nombre FROM productos")
    productos = cursor.fetchall()

    cursor.execute("SELECT id, nombre FROM proveedores")
    proveedores = cursor.fetchall()

    conn.close()
    return render_template(
        'compras/editar.html',
        compra=compra,
        productos=productos,
        proveedores=proveedores
    )


# ======================================================
#  ELIMINAR COMPRA Y PRODUCTO ASOCIADO
# ======================================================
@app.route('/eliminar/<int:id>')
def eliminar(id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        #  Verificar qué producto está asociado a esta compra
        cursor.execute("SELECT id_producto FROM compras WHERE id = %s", (id,))
        compra = cursor.fetchone()

        if not compra:
            conn.close()
            print("⚠️ No se encontró la compra con ese ID.")
            return redirect(url_for('compras'))

        id_producto = compra[0]

        #  Eliminar la compra
        cursor.execute("DELETE FROM compras WHERE id = %s", (id,))


        # Actualizar inventario al eliminar una compra
        cursor.execute("SELECT id FROM locales WHERE tipo = 'bodega' LIMIT 1")
        bodega = cursor.fetchone()
        id_bodega = bodega[0] if bodega else None

        if id_bodega:
         # Restar del inventario de la bodega la cantidad eliminada
         cursor.execute("SELECT cantidad, id_producto FROM compras WHERE id = %s", (id,))
         compra_info = cursor.fetchone()
         if compra_info:
             cantidad_eliminada = compra_info[0]
             id_producto = compra_info[1]
             cursor.execute("""
                 UPDATE inventario_local
                 SET cantidad = GREATEST(cantidad - %s, 0)
                 WHERE id_local = %s AND id_producto = %s
             """, (cantidad_eliminada, id_bodega, id_producto))


        #  Eliminar inventario asociado al producto
        cursor.execute("DELETE FROM inventario_local WHERE id_producto = %s", (id_producto,))

        #  Ahora sí eliminar el producto
        cursor.execute("DELETE FROM productos WHERE id = %s", (id_producto,))


        conn.commit()
        print(f"✅ Compra {id} y producto {id_producto} eliminados correctamente.")

    except Exception as e:
        print(f"❌ Error al eliminar: {e}")
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for('compras'))


# ======================================================
#  CATEGORÍAS
# ======================================================
@app.route('/categorias', methods=['GET', 'POST'])
def categorias():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nombre = request.form['nombre']
        cursor.execute("INSERT INTO categorias (nombre) VALUES (%s)", (nombre,))
        conn.commit()

    cursor.execute("SELECT * FROM categorias")
    categorias = cursor.fetchall()
    conn.close()
    return redirect(url_for('compras'))

@app.route('/editar_categoria/<int:id>', methods=['POST'])
def editar_categoria(id):
    nuevo_nombre = request.form.get('nombre')
    if not nuevo_nombre:
        return redirect(url_for('compras'))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE categorias SET nombre = %s WHERE id = %s", (nuevo_nombre, id))
    conn.commit()
    conn.close()

    print(f"✅ Categoría actualizada correctamente: ID {id}")
    return redirect(url_for('compras'))

@app.route('/eliminar_categoria/<int:id>')
def eliminar_categoria(id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categorias WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('compras'))


# ======================================================
#  PROVEEDORES
# ======================================================
@app.route('/proveedores', methods=['POST'])
def agregar_proveedor():
    nombre = request.form['nombre']
    telefono = request.form['telefono']
    email = request.form['email']
    direccion = request.form['direccion']

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO proveedores (nombre, telefono, email, direccion)
        VALUES (%s, %s, %s, %s)
    """, (nombre, telefono, email, direccion))
    conn.commit()
    conn.close()
    return redirect(url_for('compras'))

@app.route('/editar_proveedor/<int:id>', methods=['POST'])
def editar_proveedor(id):
    nuevo_nombre = request.form.get('nombre')
    nuevo_telefono = request.form.get('telefono')
    nuevo_email = request.form.get('email')
    nueva_direccion = request.form.get('direccion')

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE proveedores 
        SET nombre = %s, telefono = %s, email = %s, direccion = %s 
        WHERE id = %s
    """, (nuevo_nombre, nuevo_telefono, nuevo_email, nueva_direccion, id))
    conn.commit()
    conn.close()

    print(f"✅ Proveedor actualizado correctamente: ID {id}")
    return redirect(url_for('compras'))

@app.route('/eliminar_proveedor/<int:id>')
def eliminar_proveedor(id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM proveedores WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('compras'))


# ======================================================
#  SECCIÓN DE LOCALES
# ======================================================
@app.route('/locales', methods=['GET', 'POST'])
def locales():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Si se envía el formulario, añadimos un nuevo local
    if request.method == 'POST':
        nombre = request.form['nombre']
        direccion = request.form['direccion']
        telefono = request.form['telefono']
        tipo = 'local'  # por defecto siempre será un local
        cursor.execute("""
            INSERT INTO locales (nombre, direccion, telefono, tipo)
            VALUES (%s, %s, %s, %s)
        """, (nombre, direccion, telefono, tipo))
        conn.commit()

    # Traer todos los locales existentes (excepto bodega)
    cursor.execute("SELECT * FROM locales WHERE tipo = 'local'")
    locales = cursor.fetchall()

    # Diccionarios para inventarios y totales individuales
    inventarios = {}
    totales_local = {}

    # Traer inventario de cada local (agrupado por producto y precio)
    for local in locales:
        cursor.execute("""
            SELECT 
                p.id AS id_producto,
                p.nombre AS producto,
                p.precio AS precio_venta,
                SUM(il.cantidad) AS cantidad_total,
                (SUM(il.cantidad) * p.precio) AS valor_total
            FROM inventario_local il
            LEFT JOIN productos p ON il.id_producto = p.id
            WHERE il.id_local = %s
            GROUP BY p.id, p.nombre, p.precio
            ORDER BY p.nombre
        """, (local['id'],))
        inventario_local = cursor.fetchall()
        inventarios[local['id']] = inventario_local

        # Calcular total individual de cada local
        total_local = sum(item['valor_total'] or 0 for item in inventario_local)
        totales_local[local['id']] = total_local

    conn.close()
    return render_template(
        'locales/locales.html',
        locales=locales,
        inventarios=inventarios,
        totales_local=totales_local
    )


# ======================================================
#  BODEGA 
# ======================================================
@app.route('/bodegas')
def bodegas():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Obtener el ID de la bodega
    cursor.execute("SELECT id FROM locales WHERE tipo = 'bodega' LIMIT 1")
    bodega = cursor.fetchone()
    id_bodega = bodega['id'] if bodega else None

    if not id_bodega:
        conn.close()
        return "⚠️ No se encontró la bodega registrada en la base de datos."

    inventario = []
    total_valor = 0
    # Traer inventario con precios actual y de compra
    cursor.execute("""
        SELECT 
            p.id AS id_producto,
            p.nombre,
            p.descripcion,
            p.precio AS precio_producto,
            COALESCE(MAX(c.precio_compra), 0) AS precio_compra,
            il.cantidad
        FROM inventario_local il
        JOIN productos p ON il.id_producto = p.id
        LEFT JOIN compras c ON c.id_producto = p.id
        WHERE il.id_local = %s
        GROUP BY p.id, p.nombre, p.descripcion, p.precio, il.cantidad
    """, (id_bodega,))

    inventario = cursor.fetchall()

    for item in inventario:
            total_valor += item['precio_producto'] * item['cantidad']

    conn.close()

    return render_template('bodegas/bodegas.html', inventario=inventario, total_valor=total_valor)

@app.route('/bodegas/editar_precio/<int:id_producto>', methods=['POST'])
def editar_precio_bodega(id_producto):
    nuevo_precio = request.form['nuevo_precio']

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE productos
            SET precio = %s
            WHERE id = %s
        """, (nuevo_precio, id_producto))

        conn.commit()
        print(f"✅ Precio actualizado correctamente para producto {id_producto}")

    except Exception as e:
        print(f"❌ Error al actualizar precio: {e}")
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for('bodegas'))


# ======================================================
#  TRANSFERENCIAS (HISTORIAL)
# ======================================================
@app.route('/transferencias')
def transferencias():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Consulta corregida: usa los nombres REALES de las columnas
    cursor.execute("""
        SELECT 
            t.id,
            t.fecha,
            t.observaciones,
            lo.nombre AS origen,
            ld.nombre AS destino,
            COUNT(dt.id_producto) AS total_productos,
            SUM(dt.cantidad) AS total_cantidad
        FROM transferencias t
        LEFT JOIN locales lo ON t.id_origen = lo.id
        LEFT JOIN locales ld ON t.id_destino = ld.id
        LEFT JOIN detalle_transferencias dt ON t.id = dt.id_transferencia
        GROUP BY t.id, t.fecha, t.observaciones, lo.nombre, ld.nombre
        ORDER BY t.fecha DESC
    """)

    transferencias = cursor.fetchall()

    conn.close()
    return render_template('transferencias/transferencias.html', transferencias=transferencias)

@app.route('/eliminar_transferencia/<int:id>', methods=['POST'])
def eliminar_transferencia(id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Obtener detalles de la transferencia
    cursor.execute("""
        SELECT dt.id_producto, dt.cantidad, t.id_destino
        FROM detalle_transferencias dt
        JOIN transferencias t ON dt.id_transferencia = t.id
        WHERE t.id = %s
    """, (id,))
    detalles = cursor.fetchall()

    # Buscar la bodega
    cursor.execute("SELECT id FROM locales WHERE tipo = 'bodega' LIMIT 1")
    bodega = cursor.fetchone()
    id_bodega = bodega['id'] if bodega else None

    if id_bodega and detalles:
        for d in detalles:
            id_producto = d['id_producto']
            cantidad = d['cantidad']
            id_local_destino = d['id_destino']

            # Revertir inventario del local (restar)
            cursor.execute("""
                UPDATE inventario_local
                SET cantidad = GREATEST(cantidad - %s, 0)
                WHERE id_local = %s AND id_producto = %s
            """, (cantidad, id_local_destino, id_producto))

            # Revertir inventario de bodega (sumar)
            cursor.execute("""
                UPDATE inventario_local
                SET cantidad = cantidad + %s
                WHERE id_local = %s AND id_producto = %s
            """, (cantidad, id_bodega, id_producto))

    # Eliminar registros de detalle y transferencia
    cursor.execute("DELETE FROM detalle_transferencias WHERE id_transferencia = %s", (id,))
    cursor.execute("DELETE FROM transferencias WHERE id = %s", (id,))

    # 🧹 Eliminar filas vacías (cantidad 0) del inventario
    cursor.execute("DELETE FROM inventario_local WHERE cantidad = 0")

    conn.commit()
    conn.close()

    print(f"✅ Transferencia {id} eliminada y revertida correctamente (limpieza aplicada).")
    return redirect(url_for('transferencias'))


# ======================================================
#  TRANSFERIR
# ======================================================
@app.route('/transferir')
def transferir():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Obtener la bodega (id y nombre)
    cursor.execute("SELECT id, nombre FROM locales WHERE tipo = 'bodega' LIMIT 1")
    bodega = cursor.fetchone()

    # Obtener todos los locales destino (solo tipo local)
    cursor.execute("SELECT id, nombre FROM locales WHERE tipo = 'local'")
    locales = cursor.fetchall()

    # Obtener los productos disponibles en bodega
    cursor.execute("""
        SELECT p.id, p.nombre, il.cantidad
        FROM inventario_local il
        JOIN productos p ON il.id_producto = p.id
        JOIN locales l ON il.id_local = l.id
        WHERE l.tipo = 'bodega'
    """)
    productos = cursor.fetchall()

    conn.close()

    return render_template('bodegas/transferir.html', bodega=bodega, locales=locales, productos=productos)

@app.route('/bodega/transferir', methods=['GET', 'POST'])
def realizar_transferencia():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        id_destino = request.form['id_destino']
        productos = request.form.getlist('productos[]')
        cantidades = request.form.getlist('cantidades[]')
        observaciones = request.form.get('observaciones', '')

        # Obtener id de la bodega
        cursor.execute("SELECT id FROM locales WHERE tipo = 'bodega' LIMIT 1")
        bodega = cursor.fetchone()
        id_bodega = bodega['id'] if bodega else None

        # Insertar transferencia
        cursor.execute("""
            INSERT INTO transferencias (id_origen, id_destino, observaciones)
            VALUES (%s, %s, %s)
        """, (id_bodega, id_destino, observaciones))
        id_transferencia = cursor.lastrowid

        # Recorrer los productos y actualizar inventarios
        for i in range(len(productos)):
            id_producto = productos[i]
            cantidad = int(cantidades[i])

            # Insertar en detalle_transferencias
            cursor.execute("""
                INSERT INTO detalle_transferencias (id_transferencia, id_producto, cantidad)
                VALUES (%s, %s, %s)
            """, (id_transferencia, id_producto, cantidad))

            # Actualizar inventario de la bodega (restar)
            cursor.execute("""
                UPDATE inventario_local
                SET cantidad = cantidad - %s
                WHERE id_local = %s AND id_producto = %s
            """, (cantidad, id_bodega, id_producto))

            # Actualizar inventario del local destino (sumar)
            cursor.execute("""
                INSERT INTO inventario_local (id_local, id_producto, cantidad)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE cantidad = cantidad + VALUES(cantidad)
            """, (id_destino, id_producto, cantidad))

        conn.commit()
        conn.close()
        flash('✅ Transferencia realizada exitosamente.', 'success')
        return redirect(url_for('transferencias'))

    # Cargar datos
    cursor.execute("SELECT id, nombre FROM locales WHERE tipo = 'local'")
    locales = cursor.fetchall()

    cursor.execute("""
        SELECT p.id, p.nombre, il.cantidad
        FROM inventario_local il
        JOIN productos p ON il.id_producto = p.id
        JOIN locales l ON il.id_local = l.id
        WHERE l.tipo = 'bodega'
    """)
    productos = cursor.fetchall()

    conn.close()
    return render_template('bodegas/transferir.html', locales=locales, productos=productos)


# ======================================================
#  CAJA (Registrar venta)
# ======================================================
@app.route('/caja', methods=['GET'])
def caja():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Traer todos los locales (solo tipo 'local')
    cursor.execute("SELECT id, nombre FROM locales WHERE tipo = 'local'")
    locales = cursor.fetchall()

    # Traer inventario agrupado de todos los locales
    inventarios = {}
    for local in locales:
        cursor.execute("""
            SELECT 
                p.id AS id_producto,
                p.nombre AS producto,
                p.precio AS precio_venta,
                SUM(il.cantidad) AS cantidad_total
            FROM inventario_local il
            LEFT JOIN productos p ON il.id_producto = p.id
            WHERE il.id_local = %s
            GROUP BY p.id, p.nombre, p.precio
            ORDER BY p.nombre
        """, (local['id'],))
        inventarios[local['id']] = cursor.fetchall()

    # Si el usuario selecciona un local, preparar productos para el HTML
    id_local = request.args.get('id_local')
    productos = []
    if id_local and id_local in [str(l['id']) for l in locales]:
        productos = [
            {
                'id': p['id_producto'],
                'nombre': p['producto'],
                'precio': p['precio_venta'],
                'stock': p['cantidad_total']
            }
            for p in inventarios[int(id_local)]
        ]

    conn.close()
    return render_template(
        'caja/caja.html',
        locales=locales,
        inventarios=inventarios,
        productos=productos,
        id_local=id_local
    )

# ======================================================
#  ACTUALIZAR PRODUCTOS SEGÚN LOCAL 
# ======================================================
@app.route('/caja/<int:id_local>', methods=['GET'])
def caja_por_local(id_local):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Traer locales
    cursor.execute("SELECT id, nombre FROM locales WHERE tipo = 'local'")
    locales = cursor.fetchall()

    # Traer productos del inventario del local seleccionado
    # [CORRECCIÓN CLAVE]: Usamos SUM(il.cantidad) y GROUP BY p.id para agrupar el stock.
    cursor.execute("""
        SELECT 
            p.id,
            p.nombre,
            p.precio,
            COALESCE(SUM(il.cantidad), 0) AS stock 
        FROM productos p
        LEFT JOIN inventario_local il 
        ON p.id = il.id_producto AND il.id_local = %s
        GROUP BY p.id, p.nombre, p.precio
        HAVING COALESCE(SUM(il.cantidad), 0) > 0 -- Opcional: solo productos con stock > 0
        ORDER BY p.nombre
    """, (id_local,))
    productos = cursor.fetchall()

    conn.close()
    return render_template('caja/caja.html', locales=locales, productos=productos, id_local=id_local)


# ======================================================
#  REGISTRAR VENTA
# ======================================================
@app.route('/registrar_venta', methods=['POST'])
def registrar_venta():
    detalle_venta_data_str = request.form.get('detalle_venta_data')
    
    # Intenta obtener el id_local desde el formulario o la sesión para la redirección de error
    id_local_form = request.form.get('id_local', session.get('local_activo_id'))

    if not detalle_venta_data_str:
        flash('⚠️ No se seleccionaron productos válidos para la venta.', 'warning')
        return redirect(url_for('caja', id_local=id_local_form))

    try:
        detalle_venta_data = json.loads(detalle_venta_data_str)
        total_venta = float(request.form.get('total_venta', 0.0))
        id_local = int(request.form.get('id_local'))
    except (ValueError, TypeError, json.JSONDecodeError):
        flash('Error: Datos de venta o local inválidos.', 'danger')
        return redirect(url_for('caja', id_local=id_local_form))

    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Insertar la venta principal (Esto estaba correcto)
        cursor.execute("""
            INSERT INTO ventas (fecha, id_local, total) 
            VALUES (NOW(), %s, %s)
        """, (id_local, total_venta)) 
        
        id_venta = cursor.lastrowid

        # 2. Procesar e insertar los detalles de la venta (Esto estaba correcto)
        for item in detalle_venta_data:
            id_producto = item.get('id')
            cantidad = int(item.get('cantidad'))
            precio = float(item.get('precio')) 
            
            # (Corregido basado en tu DB: la columna es 'precio_venta')
            cursor.execute("""
                INSERT INTO detalle_ventas (id_venta, id_producto, cantidad, precio_venta) 
                VALUES (%s, %s, %s, %s)
            """, (id_venta, id_producto, cantidad, precio)) 
            
            # --- INICIO DE CORRECCIONES ---

            # 3. Descontar stock global
            # [CORRECCIÓN 1]: La columna es 'cantidad', no 'stock'
            cursor.execute("""
                UPDATE productos 
                SET cantidad = GREATEST(cantidad - %s, 0) 
                WHERE id = %s
            """, (cantidad, id_producto))
            
            # 4. Descontar stock local
            # [CORRECCIÓN 2]: La tabla es 'inventario_local', no 'stock_local'
            # [CORRECCIÓN 3]: La columna es 'cantidad', no 'stock'
            cursor.execute("""
                UPDATE inventario_local 
                SET cantidad = GREATEST(cantidad - %s, 0)
                WHERE id_producto = %s AND id_local = %s
            """, (cantidad, id_producto, id_local))
            
            # --- FIN DE CORRECCIONES ---

        conn.commit()
        flash(f'Venta ID {id_venta} registrada correctamente.', 'success')
        
    except Exception as e:
        conn.rollback()
        # Imprime el error real en la consola de Flask para depurar
        print(f"Error en la base de datos al registrar venta: {e}") 
        flash(f'❌ Error al registrar la venta. La transacción fue revertida. Detalle: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('caja', id_local=id_local))


# ======================================================
#  VENTAS
# ======================================================

@app.route('/ventas')
def ventas():
    """Muestra todas las ventas registradas."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Consulta principal para obtener las ventas
    cursor.execute("""
        SELECT v.id, v.fecha, l.nombre AS local_nombre, v.total
        FROM ventas v
        JOIN locales l ON v.id_local = l.id
        ORDER BY v.fecha DESC
    """)
    ventas = cursor.fetchall()
    conn.close()
    
    return render_template('ventas/ventas.html', ventas=ventas)

@app.route('/ventas/detalle/<int:id_venta>', methods=['GET'])
def obtener_detalle_venta(id_venta):
    """
    Renderiza el contenido HTML del detalle de una venta específica (mini-plantilla).
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # [CORRECCIÓN CLAVE CONSULTA]: Se usa dv.precio_venta y se lo aliasa para consistencia
    cursor.execute("""
        SELECT 
            dv.cantidad, 
            dv.precio_venta AS precio_unitario,  
            (dv.cantidad * dv.precio_venta) AS subtotal,
            p.nombre AS producto_nombre
        FROM detalle_ventas dv
        JOIN productos p ON dv.id_producto = p.id
        WHERE dv.id_venta = %s
    """, (id_venta,))

    detalles = cursor.fetchall()

    # 2. Obtener la información de la venta (id, local, fecha, total)
    cursor.execute("""
        SELECT v.id, l.nombre AS local_nombre, v.fecha, v.total
        FROM ventas v
        JOIN locales l ON v.id_local = l.id
        WHERE v.id = %s
    """, (id_venta,))
    venta_info = cursor.fetchone()
    
    conn.close()
    
    if not detalles or not venta_info:
        return "<p class='p-3 text-center text-danger'>Error: Venta no encontrada o sin detalles.</p>"

    # 3. Retornar la mini-plantilla renderizada.
    # modal_content_only=True le dice a detalle_modal.html que renderice solo el contenido.
    return render_template(
        'ventas/detalle_modal.html', 
        detalles=detalles, 
        venta_info=venta_info,
        modal_content_only=True
    )

@app.route('/ventas/eliminar/<int:id_venta>', methods=['POST'])
def eliminar_venta(id_venta):
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Obtener detalles de la venta antes de eliminar
        # Esto nos da la cantidad a revertir, el producto y el local.
        cursor.execute("""
            SELECT dv.cantidad, dv.id_producto, v.id_local 
            FROM detalle_ventas dv
            JOIN ventas v ON dv.id_venta = v.id
            WHERE dv.id_venta = %s
        """, (id_venta,))
        detalles = cursor.fetchall()
        
        if not detalles:
            conn.close()
            flash('Error: No se encontraron detalles para la venta a eliminar.', 'danger')
            return redirect(url_for('ventas'))

        # 2. Revertir el stock (Global y Local)
        for cantidad, id_producto, id_local in detalles:
            
            # 2a. Revertir stock global en la tabla productos
            cursor.execute("UPDATE productos SET cantidad = cantidad + %s WHERE id = %s", (cantidad, id_producto))
            
            # 2b. Revertir stock local en la tabla INVENTARIO_LOCAL
            # Se corrige el nombre de la tabla (de stock_local a inventario_local) y la columna a 'cantidad'
            cursor.execute("""
                INSERT INTO inventario_local (id_local, id_producto, cantidad)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE cantidad = cantidad + VALUES(cantidad)
            """, (id_local, id_producto, cantidad))


        # 3. Eliminar los detalles de la venta
        cursor.execute("DELETE FROM detalle_ventas WHERE id_venta = %s", (id_venta,))

        # 4. Eliminar la venta principal
        cursor.execute("DELETE FROM ventas WHERE id = %s", (id_venta,))

        conn.commit()
        flash(f'Venta ID {id_venta} eliminada y stock revertido correctamente.', 'success')

    except Exception as e:
        conn.rollback()
        print(f"Ocurrió un error al eliminar la venta: {e}")
        flash(f"Ocurrió un error al eliminar la venta: {e}", 'danger')

    finally:
        conn.close()
    
    return redirect(url_for('ventas'))


# ======================================================
#  VISOR DE PRODUCTOS (SOLO LECTURA)
# ======================================================
@app.route('/productos/visor')
def productos_visor():
    conn = get_connection()
    productos = []
    try:
        cursor = conn.cursor(dictionary=True)
        
        # CONSULTA CORREGIDA: Usando p.precio en lugar de p.precio_venta
        cursor.execute("""
            SELECT p.id, p.nombre, p.descripcion, p.precio AS precio_venta, 
                   p.cantidad AS stock_global,
                   c.nombre AS categoria_nombre
            FROM productos p
            JOIN categorias c ON p.id_categoria = c.id
            ORDER BY p.nombre
        """)
        productos = cursor.fetchall()
        
    except Exception as e:
        print(f"Error al cargar productos para el visor: {e}")
        # En caso de error, la lista de productos será vacía, mostrando el mensaje de "no hay productos".
    finally:
        conn.close()

    # Nota: Aquí usamos 'precio_venta' como key en el diccionario, 
    # pero el valor viene de la columna 'precio' de la DB.
    return render_template('productos/productos.html', productos=productos)


# ======================================================
#  FUNCIÓN DE EXTRACCIÓN DE CONTEXTO PARA IA
# ======================================================
def obtener_contexto_completo(conn):
    """
    Extrae un resumen completo de todas las tablas clave de la base de datos
    para enviarlo como contexto a Gemini. Usa el esquema de inventario_db.sql.
    """
    cursor = conn.cursor(dictionary=True)
    contexto = {}

    try:
        # 1. Productos (Maestro) y Categorías
        # SQL: usa p.precio (precio de venta) y p.cantidad (stock global)
        cursor.execute("""
            SELECT p.id, p.nombre, p.descripcion, p.precio, p.cantidad AS stock_global, c.nombre AS categoria
            FROM productos p
            LEFT JOIN categorias c ON p.id_categoria = c.id
        """)
        contexto['productos'] = cursor.fetchall()

        # 2. Locales (Dónde está el stock)
        cursor.execute("SELECT id, nombre, tipo FROM locales")
        contexto['locales'] = cursor.fetchall()

        # 3. Inventario por Local (Stock detallado)
        # SQL: usa inventario_local y cantidad
        cursor.execute("""
            SELECT il.id_producto, l.nombre AS local, il.cantidad
            FROM inventario_local il
            JOIN locales l ON il.id_local = l.id
            WHERE il.cantidad > 0
        """)
        contexto['inventario_por_local'] = cursor.fetchall()

        # 4. Ventas Recientes (Últimas 100)
        # SQL: usa detalle_ventas y precio_venta
        cursor.execute("""
            SELECT dv.id_producto, p.nombre AS producto_nombre, v.fecha, dv.cantidad, dv.precio_venta, l.nombre AS local
            FROM detalle_ventas dv
            JOIN ventas v ON dv.id_venta = v.id
            JOIN locales l ON v.id_local = l.id
            JOIN productos p ON dv.id_producto = p.id
            ORDER BY v.fecha DESC
            LIMIT 100
        """)
        contexto['ventas_recientes'] = cursor.fetchall()

        # 5. Compras Recientes (Últimas 100)
        # SQL: usa compras y precio_compra
        cursor.execute("""
            SELECT c.id_producto, p.nombre AS producto_nombre, c.fecha, c.cantidad, c.precio_compra, pr.nombre AS proveedor
            FROM compras c
            JOIN proveedores pr ON c.id_proveedor = pr.id
            JOIN productos p ON c.id_producto = p.id
            ORDER BY c.fecha DESC
            LIMIT 100
        """)
        contexto['compras_recientes'] = cursor.fetchall()

        # 6. Transferencias Recientes (Últimas 100)
        # SQL: usa detalle_transferencias
        cursor.execute("""
            SELECT dt.id_producto, p.nombre AS producto_nombre, t.fecha, dt.cantidad, lo.nombre AS origen, ld.nombre AS destino
            FROM detalle_transferencias dt
            JOIN transferencias t ON dt.id_transferencia = t.id
            JOIN locales lo ON t.id_origen = lo.id
            JOIN locales ld ON t.id_destino = ld.id
            JOIN productos p ON dt.id_producto = p.id
            ORDER BY t.fecha DESC
            LIMIT 100
        """)
        contexto['transferencias_recientes'] = cursor.fetchall()

    except Exception as e:
        print(f"Error al obtener contexto para IA: {e}")
        return None
    finally:
        cursor.close()
        
    return contexto

# ======================================================
#  RUTA DE ANÁLISIS CON GEMINI 
# ======================================================
@app.route('/analizar', methods=['GET', 'POST'])
def analizar():
    """
    Muestra la página de análisis y maneja la solicitud de análisis a Gemini.
    """
    
    if request.method == 'POST':
        try:
            prompt_usuario = request.form['prompt']
            if not prompt_usuario:
                flash('Por favor, ingresa una pregunta para analizar.', 'warning')
                return render_template('analisis.html')

            # 1. Obtener conexión a la BD
            conn = get_connection()
            if not conn:
                flash('Error de conexión a la base de datos.', 'danger')
                return render_template('analisis.html')

            # 2. Obtener el contexto completo
            contexto_bd = obtener_contexto_completo(conn)
            conn.close()
            
            if not contexto_bd:
                flash('Error al extraer datos de la base de datos.', 'danger')
                return render_template('analisis.html')

            # 3. Convertir a JSON
            # default=str es importante para manejar fechas (datetime)
            contexto_json = json.dumps(contexto_bd, default=str, indent=2)

            # 4. Enviamos el contexto y la pregunta del usuario a Gemini para su análisis (2 argumentos)
            resultado_analisis = analizar_inventario(contexto_json, prompt_usuario)
            
            # 5. Devolver la vista con el resultado
            return render_template('analisis.html', resultado=resultado_analisis, prompt_actual=prompt_usuario)

        except Exception as e:
            print(f"Error en la ruta /analizar: {e}")
            flash(f'Ocurrió un error inesperado: {e}', 'danger')
            return render_template('analisis.html')

    # Método GET: Simplemente muestra la página
    return render_template('analisis.html')

if __name__ == '__main__':
    app.run(debug=True)
