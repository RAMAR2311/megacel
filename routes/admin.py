from flask import Blueprint, render_template, abort, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Sale, User, Maneo, Cliente, SaleDetail, SalePayment, StockAdjustment, Expense, ArqueoCaja, ProviderPayment, FacturaBodega, AbonoBodega, PriceApproval, obtener_hora_bogota
from sqlalchemy.sql import func
from werkzeug.security import generate_password_hash
from decorators import admin_required
from decimal import Decimal
from datetime import datetime, timedelta
import calendar

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/vendedores', methods=['GET', 'POST'])
@login_required
@admin_required
def vendedores():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        password = request.form.get('password')
        rol = request.form.get('rol', 'vendedor')
        
        # Validar que el rol sea uno de los permitidos por el sistema
        roles_permitidos = ['admin', 'vendedor']
        if rol not in roles_permitidos:
            rol = 'vendedor'
        
        # Se previene registrar usuarios con un mismo email para preservar la unicidad de las credenciales de acceso
        if User.query.filter_by(email=email.strip()).first():
            flash('Acción Denegada: Ese correo ya le pertenece a otro usuario.', 'danger')
        else:
            try:
                # Se aplica un hash a la contraseña para evitar guardar texto plano, previniendo exposición en caso de brechas
                nuevo_usuario = User(
                    nombre=nombre.strip(),
                    email=email.strip(),
                    telefono=telefono.strip() if telefono else None,
                    password_hash=generate_password_hash(password),
                    rol=rol
                )
                db.session.add(nuevo_usuario)
                db.session.commit()
                rol_label = 'Administrador' if rol == 'admin' else ('Vendedor' if rol == 'vendedor' else ('Encargado de Bodega' if rol == 'bodega' else 'Vendedor de Bodega'))
                flash(f"¡Usuario '{nombre}' registrado como '{rol_label}' exitosamente!", "success")
            except Exception as e:
                db.session.rollback()
                flash('Ocurrió un error en la base de datos al intentar registrar al usuario.', 'danger')
            
        return redirect(url_for('admin_bp.vendedores'))
        
    # Se pasa la lista para poblar la tabla HTML de gestión de personal
    # Mostramos todos los usuarios activos del sistema (excluyendo solo registros eliminados)
    lista_vendedores = User.query.filter(User.rol != 'eliminado').order_by(User.rol == 'admin', User.nombre).all()
    return render_template('admin/vendedores.html', vendedores=lista_vendedores)

@admin_bp.route('/vendedores/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_vendedor(id):
    usuario = User.query.get_or_404(id)
    if usuario.id == current_user.id:
        flash("Acción Denegada: No puedes eliminar tu propia cuenta de usuario.", "danger")
        return redirect(url_for('admin_bp.vendedores'))
        
    try:
        # En lugar de hacer un delete() duro que rompe las llaves foráneas (ventas, facturas), hacemos un soft delete
        usuario.rol = 'eliminado'
        usuario.email = f"eliminado_{usuario.id}_{usuario.email}"
        db.session.commit()
        flash(f"¡Usuario '{usuario.nombre}' eliminado exitosamente!", "success")
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error al intentar eliminar el usuario.", "danger")
        
    return redirect(url_for('admin_bp.vendedores'))

@admin_bp.route('/vendedores/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_vendedor(id):
    usuario = User.query.get_or_404(id)
    nombre = request.form.get('nombre', '').strip()
    email = request.form.get('email', '').strip()
    telefono = request.form.get('telefono', '').strip()
    rol = request.form.get('rol', '').strip()
    nueva_password = request.form.get('password', '').strip()

    if not nombre or not email:
        flash("El nombre y el correo empresarial son obligatorios.", "danger")
        return redirect(url_for('admin_bp.vendedores'))

    # Validar duplicados de correo en usuarios activos
    usuario_existente = User.query.filter(User.email == email, User.id != id, User.rol != 'eliminado').first()
    if usuario_existente:
        flash(f"El correo '{email}' ya se encuentra registrado por otro usuario en el sistema.", "danger")
        return redirect(url_for('admin_bp.vendedores'))

    roles_permitidos = ['admin', 'vendedor']
    if rol in roles_permitidos:
        # Si el admin actual se edita a sí mismo, no permitir quitarse el rol de admin
        if usuario.id == current_user.id and rol != 'admin':
            flash("No puedes retirar tu propio rol de Administrador.", "warning")
        else:
            usuario.rol = rol

    usuario.nombre = nombre
    usuario.email = email
    usuario.telefono = telefono

    if nueva_password:
        usuario.password_hash = generate_password_hash(nueva_password)

    try:
        db.session.commit()
        flash(f"¡Credenciales y perfil de '{usuario.nombre}' actualizados exitosamente!", "success")
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error al actualizar la información del usuario.", "danger")

    return redirect(url_for('admin_bp.vendedores'))

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    hoy = obtener_hora_bogota()

    meses_nombres = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }

    # Determinar el tipo de filtro
    filtro_tipo = request.args.get('filtro_tipo')
    if not filtro_tipo:
        if 'fecha_dia' in request.args:
            filtro_tipo = 'dia'
        elif 'fecha_semana' in request.args:
            filtro_tipo = 'semana'
        elif 'quincena_num' in request.args:
            filtro_tipo = 'quincena'
        else:
            filtro_tipo = 'mes'

    fecha_dia_str = request.args.get('fecha_dia', hoy.strftime('%Y-%m-%d'))
    fecha_semana_str = request.args.get('fecha_semana', hoy.strftime('%Y-%m-%d'))

    try:
        mes = int(request.args.get('mes', hoy.month))
        if not (1 <= mes <= 12):
            mes = hoy.month
    except (ValueError, TypeError):
        mes = hoy.month

    try:
        anio = int(request.args.get('anio', hoy.year))
        if anio < 2020 or anio > 2035:
            anio = hoy.year
    except (ValueError, TypeError):
        anio = hoy.year

    try:
        quincena_num = int(request.args.get('quincena_num', 1 if hoy.day <= 15 else 2))
        if quincena_num not in [1, 2]:
            quincena_num = 1 if hoy.day <= 15 else 2
    except (ValueError, TypeError):
        quincena_num = 1 if hoy.day <= 15 else 2

    # Cálculo de fechas según filtro
    if filtro_tipo == 'dia':
        try:
            dt_dia = datetime.strptime(fecha_dia_str, '%Y-%m-%d')
        except ValueError:
            dt_dia = hoy
            fecha_dia_str = hoy.strftime('%Y-%m-%d')
        inicio_filtro = datetime(dt_dia.year, dt_dia.month, dt_dia.day, 0, 0, 0)
        fin_filtro = datetime(dt_dia.year, dt_dia.month, dt_dia.day, 23, 59, 59, 999999)
        es_hoy = (dt_dia.date() == hoy.date())
        label_periodo = f"{'Hoy, ' if es_hoy else ''}{dt_dia.day} de {meses_nombres.get(dt_dia.month)} {dt_dia.year}"
        badge_periodo = "Hoy" if es_hoy else dt_dia.strftime('%d/%m/%Y')
        tipo_periodo_nombre = "Día"

    elif filtro_tipo == 'semana':
        try:
            dt_sem = datetime.strptime(fecha_semana_str, '%Y-%m-%d')
        except ValueError:
            dt_sem = hoy
            fecha_semana_str = hoy.strftime('%Y-%m-%d')
        lunes = dt_sem.date() - timedelta(days=dt_sem.weekday())
        domingo = lunes + timedelta(days=6)
        inicio_filtro = datetime(lunes.year, lunes.month, lunes.day, 0, 0, 0)
        fin_filtro = datetime(domingo.year, domingo.month, domingo.day, 23, 59, 59, 999999)
        label_periodo = f"Semana del {lunes.day} {meses_nombres.get(lunes.month)[:3]} al {domingo.day} {meses_nombres.get(domingo.month)[:3]} {domingo.year}"
        badge_periodo = f"{lunes.strftime('%d/%m')} - {domingo.strftime('%d/%m')}"
        tipo_periodo_nombre = "Semana"

    elif filtro_tipo == 'quincena':
        ultimo_dia_mes = calendar.monthrange(anio, mes)[1]
        if quincena_num == 1:
            inicio_filtro = datetime(anio, mes, 1, 0, 0, 0)
            fin_filtro = datetime(anio, mes, 15, 23, 59, 59, 999999)
            label_periodo = f"1ª Quincena de {meses_nombres.get(mes)} {anio} (1 al 15)"
            badge_periodo = f"1ª Q. {meses_nombres.get(mes)[:3]}"
        else:
            inicio_filtro = datetime(anio, mes, 16, 0, 0, 0)
            fin_filtro = datetime(anio, mes, ultimo_dia_mes, 23, 59, 59, 999999)
            label_periodo = f"2ª Quincena de {meses_nombres.get(mes)} {anio} (16 al {ultimo_dia_mes})"
            badge_periodo = f"2ª Q. {meses_nombres.get(mes)[:3]}"
        tipo_periodo_nombre = "Quincena"

    else: # mes
        filtro_tipo = 'mes'
        ultimo_dia_mes = calendar.monthrange(anio, mes)[1]
        inicio_filtro = datetime(anio, mes, 1, 0, 0, 0)
        fin_filtro = datetime(anio, mes, ultimo_dia_mes, 23, 59, 59, 999999)
        label_periodo = f"{meses_nombres.get(mes)} {anio}"
        badge_periodo = f"{meses_nombres.get(mes)} {anio}"
        tipo_periodo_nombre = "Mes"

    # 1. Ventas e Ingresos del Periodo
    ventas_en_rango = Sale.query.filter(Sale.fecha_venta >= inicio_filtro, Sale.fecha_venta <= fin_filtro).all()
    total_ventas = sum((v.monto_total or 0) for v in ventas_en_rango)
    conteo_ventas = len(ventas_en_rango)

    # Desglose financiero por método de pago (híbrido: sale_payments con fallback a venta.metodo_pago)
    ventas_efectivo = Decimal('0.00')
    ventas_nequi = Decimal('0.00')
    ventas_bancolombia = Decimal('0.00')
    ventas_daviplata = Decimal('0.00')
    ventas_bolt = Decimal('0.00')
    ventas_otros_digital = Decimal('0.00')

    for v in ventas_en_rango:
        if v.pagos and len(v.pagos) > 0:
            for p in v.pagos:
                monto_p = Decimal(str(p.monto or 0))
                m = (p.metodo_pago or '').lower().strip()
                if m == 'efectivo':
                    ventas_efectivo += monto_p
                elif m == 'nequi':
                    ventas_nequi += monto_p
                elif m == 'bancolombia':
                    ventas_bancolombia += monto_p
                elif m == 'daviplata':
                    ventas_daviplata += monto_p
                elif m in ['bolt', 'bold']:
                    ventas_bolt += monto_p
                else:
                    ventas_otros_digital += monto_p
        else:
            monto_v = Decimal(str(v.monto_total or 0))
            m = (v.metodo_pago or '').lower().strip()
            if m == 'efectivo':
                ventas_efectivo += monto_v
            elif m == 'nequi':
                ventas_nequi += monto_v
            elif m == 'bancolombia':
                ventas_bancolombia += monto_v
            elif m == 'daviplata':
                ventas_daviplata += monto_v
            elif m in ['bolt', 'bold']:
                ventas_bolt += monto_v
            else:
                ventas_otros_digital += monto_v

    ventas_transferencia = ventas_nequi + ventas_bancolombia + ventas_daviplata + ventas_bolt + ventas_otros_digital
    ticket_promedio = (float(total_ventas) / conteo_ventas) if conteo_ventas > 0 else 0.0

    # 2. Unidades y Mercancía Vendida en el Periodo
    detalles_en_rango = SaleDetail.query.join(Sale).filter(
        Sale.fecha_venta >= inicio_filtro,
        Sale.fecha_venta <= fin_filtro
    ).all()
    unidades_vendidas = sum(d.cantidad_vendida for d in detalles_en_rango)
    referencias_vendidas = len(set(d.product_id for d in detalles_en_rango if d.product_id))
    total_productos = Product.query.filter(Product.activo == True).count()

    # 3. Gastos Operativos del Periodo
    gastos_en_rango = Expense.query.filter(
        Expense.fecha_gasto >= inicio_filtro,
        Expense.fecha_gasto <= fin_filtro
    ).all()
    total_gastos = sum((g.monto or 0) for g in gastos_en_rango)
    conteo_gastos = len(gastos_en_rango)
    gastos_diarios = sum((g.monto or 0) for g in gastos_en_rango if g.tipo_gasto == 'Gasto Diario')
    costos_indirectos = sum((g.monto or 0) for g in gastos_en_rango if g.tipo_gasto == 'Costo Indirecto')

    # 4. Utilidad / Ganancia Estimada del Periodo (COGS)
    costos_directos = Decimal('0.00')
    for d in detalles_en_rango:
        if d.nombre_manual:
            costos_directos += Decimal(str(d.precio_costo_manual or 0)) * d.cantidad_vendida
        elif d.variant_id:
            v = d.variante
            p = d.producto
            if v and p:
                costo_u = v.precio_costo if v.precio_costo is not None else (p.precio_costo or 0)
                costos_directos += Decimal(str(costo_u)) * d.cantidad_vendida
        elif d.product_id:
            p = d.producto
            if p:
                costos_directos += Decimal(str(p.precio_costo or 0)) * d.cantidad_vendida
    utilidad_neta = float(total_ventas) - float(costos_directos) - float(total_gastos)

    # 5. Maneos (Préstamos) del Periodo y Estado Global
    maneos_en_rango = Maneo.query.filter(
        Maneo.fecha_prestamo >= inicio_filtro,
        Maneo.fecha_prestamo <= fin_filtro
    ).all()
    maneos_periodo_count = len(maneos_en_rango)
    maneos_periodo_monto = sum(m.subtotal_calculado for m in maneos_en_rango)
    maneos_activos = Maneo.query.filter_by(estado='PENDIENTE').count()

    # 6. Alertas de Stock y Ajustes del Periodo
    productos_bajo_stock = Product.query.filter(Product.activo == True, Product.cantidad_stock <= 10).count()
    ajustes_periodo = StockAdjustment.query.filter(
        StockAdjustment.fecha_ajuste >= inicio_filtro,
        StockAdjustment.fecha_ajuste <= fin_filtro
    ).count()

    # 7. Proveedores del Periodo
    pagos_prov_en_rango = ProviderPayment.query.filter(
        ProviderPayment.fecha_pago >= inicio_filtro,
        ProviderPayment.fecha_pago <= fin_filtro
    ).all()
    pagos_proveedores_periodo = sum((p.monto_abonado or 0) for p in pagos_prov_en_rango)
    conteo_pagos_prov = len(pagos_prov_en_rango)

    # 8. Aprobaciones de Precios del Periodo y Estado Global
    aprobaciones_en_rango = PriceApproval.query.filter(
        PriceApproval.fecha_solicitud >= inicio_filtro,
        PriceApproval.fecha_solicitud <= fin_filtro
    ).all()
    total_aprobaciones_periodo = len(aprobaciones_en_rango)
    aprobadas_periodo = sum(1 for a in aprobaciones_en_rango if a.estado in ('aprobado', 'utilizada'))
    rechazadas_periodo = sum(1 for a in aprobaciones_en_rango if a.estado == 'rechazado')
    pendientes_activas = PriceApproval.query.filter_by(estado='pendiente').count()

    return render_template('admin/dashboard.html',
                           filtro_tipo=filtro_tipo,
                           fecha_dia=fecha_dia_str,
                           fecha_semana=fecha_semana_str,
                           quincena_num=quincena_num,
                           mes=mes,
                           anio=anio,
                           label_periodo=label_periodo,
                           badge_periodo=badge_periodo,
                           tipo_periodo_nombre=tipo_periodo_nombre,
                           inicio_filtro=inicio_filtro,
                           fin_filtro=fin_filtro,
                           # Tarjeta 1: Ingresos
                           total_ventas=total_ventas,
                           conteo_ventas=conteo_ventas,
                           ventas_efectivo=ventas_efectivo,
                           ventas_transferencia=ventas_transferencia,
                           ventas_nequi=ventas_nequi,
                           ventas_bancolombia=ventas_bancolombia,
                           ventas_daviplata=ventas_daviplata,
                           ventas_bolt=ventas_bolt,
                           ticket_promedio=ticket_promedio,
                           # Tarjeta 2: Unidades vendidas y catálogo
                           unidades_vendidas=unidades_vendidas,
                           referencias_vendidas=referencias_vendidas,
                           total_productos=total_productos,
                           # Tarjeta 3: Gastos
                           total_gastos=total_gastos,
                           conteo_gastos=conteo_gastos,
                           gastos_diarios=gastos_diarios,
                           costos_indirectos=costos_indirectos,
                           # Tarjeta 4: Utilidad
                           utilidad_neta=utilidad_neta,
                           costos_directos=float(costos_directos),
                           # Tarjeta 5: Maneos
                           maneos_periodo_count=maneos_periodo_count,
                           maneos_periodo_monto=maneos_periodo_monto,
                           maneos_activos=maneos_activos,
                           # Tarjeta 6: Alertas de Stock
                           productos_bajo_stock=productos_bajo_stock,
                           ajustes_periodo=ajustes_periodo,
                           # Tarjeta 7: Proveedores
                           pagos_proveedores_periodo=pagos_proveedores_periodo,
                           conteo_pagos_prov=conteo_pagos_prov,
                           # Tarjeta 8: Aprobaciones de Precios
                           total_aprobaciones_periodo=total_aprobaciones_periodo,
                           aprobadas_periodo=aprobadas_periodo,
                           rechazadas_periodo=rechazadas_periodo,
                           pendientes_activas=pendientes_activas,
                           # Retrocompatibilidad
                           nombre_mes=meses_nombres.get(mes, 'Mes Actual'))

@admin_bp.route('/aprobaciones')
@login_required
@admin_required
def aprobaciones():
    """Vista completa de Historial y Auditoría de Aprobaciones de Precios."""
    # Por requerimiento, por defecto solo se muestran las aprobaciones donde se realizó la venta ('utilizada')
    estado_filtro = request.args.get('estado', 'utilizada')
    vendedor_id = request.args.get('vendedor_id', type=int)
    buscar = request.args.get('buscar', '').strip()
    fecha_inicio_str = request.args.get('fecha_inicio', '')
    fecha_fin_str = request.args.get('fecha_fin', '')

    query = PriceApproval.query

    if estado_filtro and estado_filtro != 'todos':
        query = query.filter(PriceApproval.estado == estado_filtro)

    if vendedor_id:
        query = query.filter(PriceApproval.vendedor_id == vendedor_id)

    if buscar:
        query = query.filter(
            db.or_(
                PriceApproval.nombre_producto.ilike(f'%{buscar}%'),
                PriceApproval.motivo.ilike(f'%{buscar}%'),
                PriceApproval.vendedor.has(User.nombre.ilike(f'%{buscar}%'))
            )
        )

    if fecha_inicio_str:
        try:
            f_ini = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
            query = query.filter(PriceApproval.fecha_solicitud >= f_ini)
        except ValueError:
            pass

    if fecha_fin_str:
        try:
            f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(PriceApproval.fecha_solicitud <= f_fin)
        except ValueError:
            pass

    solicitudes = query.order_by(PriceApproval.fecha_solicitud.desc()).all()

    # Métricas globales para los KPIs
    total_solicitudes = PriceApproval.query.count()
    total_aprobadas = PriceApproval.query.filter(PriceApproval.estado.in_(['aprobado', 'utilizada'])).count()
    total_rechazadas = PriceApproval.query.filter_by(estado='rechazado').count()
    total_pendientes = PriceApproval.query.filter_by(estado='pendiente').count()

    vendedores = User.query.filter(User.rol != 'eliminado').order_by(User.nombre).all()

    return render_template(
        'admin/aprobaciones_historial.html',
        solicitudes=solicitudes,
        total_solicitudes=total_solicitudes,
        total_aprobadas=total_aprobadas,
        total_rechazadas=total_rechazadas,
        total_pendientes=total_pendientes,
        vendedores=vendedores,
        estado_filtro=estado_filtro,
        vendedor_id=vendedor_id,
        buscar=buscar,
        fecha_inicio=fecha_inicio_str,
        fecha_fin=fecha_fin_str
    )

@admin_bp.route('/balance-financiero', methods=['GET', 'POST'])
@login_required
@admin_required
def balance_financiero():
    if request.method == 'POST':
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
    else:
        fecha_inicio_str = request.args.get('fecha_inicio')
        fecha_fin_str = request.args.get('fecha_fin')

    hoy = obtener_hora_bogota()
    import calendar
    if not fecha_inicio_str or not fecha_fin_str:
        # Por defecto, el mes actual
        primer_dia = hoy.replace(day=1)
        ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
        ultimo_dia = hoy.replace(day=ultimo_dia_mes)
        
        fecha_inicio_str = primer_dia.strftime('%Y-%m-%d')
        fecha_fin_str = ultimo_dia.strftime('%Y-%m-%d')

    from datetime import datetime, timedelta
    try:
        inicio_dt = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
        fin_dt = datetime.strptime(fecha_fin_str, '%Y-%m-%d')
        # Avanzamos límite al inicio del siguiente día matemáticamente
        fin_dt_query = fin_dt + timedelta(days=1)
    except ValueError:
        flash("Formato de fecha inválido.", "danger")
        return redirect(url_for('admin_bp.dashboard'))

    # 1. Ventas Totales
    ventas_query = Sale.query.filter(Sale.fecha_venta >= inicio_dt, Sale.fecha_venta < fin_dt_query).all()
    
    ventas_efectivo = Decimal('0.00')
    ventas_transferencia = Decimal('0.00')
    for v in ventas_query:
        if v.pagos and len(v.pagos) > 0:
            for p in v.pagos:
                m = (p.metodo_pago or '').lower().strip()
                monto_p = Decimal(str(p.monto or 0))
                if m == 'efectivo':
                    ventas_efectivo += monto_p
                else:
                    ventas_transferencia += monto_p
        else:
            m = (v.metodo_pago or '').lower().strip()
            monto_v = Decimal(str(v.monto_total or 0))
            if m == 'efectivo':
                ventas_efectivo += monto_v
            else:
                ventas_transferencia += monto_v

    total_ingresos = ventas_efectivo + ventas_transferencia

    # 2. Costo de Mercancía Vendida (COGS)
    detalles_query = SaleDetail.query.join(Sale).filter(
        Sale.fecha_venta >= inicio_dt,
        Sale.fecha_venta < fin_dt_query
    ).all()
    
    costos_directos = Decimal('0.00')
    for d in detalles_query:
        if d.nombre_manual:
            # Producto manual prestado
            costos_directos += (d.precio_costo_manual or 0) * d.cantidad_vendida
        elif d.variant_id:
            # Producto con variante: Priorizar costo de variante, luego producto
            v = d.variante
            p = d.producto
            if v and p:
                costo_u = v.precio_costo if v.precio_costo is not None else (p.precio_costo or 0)
                costos_directos += Decimal(str(costo_u)) * d.cantidad_vendida
        elif d.product_id:
            # Producto base sin variante
            p = d.producto
            if p:
                costos_directos += (p.precio_costo or 0) * d.cantidad_vendida

    # 3. Costos Indirectos y Gastos Operativos
    gastos_query = Expense.query.filter(Expense.fecha_gasto >= inicio_dt, Expense.fecha_gasto < fin_dt_query).all()
    
    costos_indirectos = sum(g.monto for g in gastos_query if g.tipo_gasto == 'Costo Indirecto')
    gastos_operacionales = sum(g.monto for g in gastos_query if g.tipo_gasto == 'Gasto Diario')
    
    total_salidas = float(costos_directos) + float(costos_indirectos) + float(gastos_operacionales)
    balance_neto = float(total_ingresos) - total_salidas

    # 4. Desglose de Bodega y Cartera Mayorista (B2B)
    facturas_bodega_periodo = FacturaBodega.query.filter(
        FacturaBodega.fecha_subida >= inicio_dt,
        FacturaBodega.fecha_subida < fin_dt_query
    ).all()
    bodega_contado = sum((f.monto_total for f in facturas_bodega_periodo if f.modalidad == 'contado'), Decimal('0'))
    bodega_credito = sum((f.monto_total for f in facturas_bodega_periodo if f.modalidad == 'credito'), Decimal('0'))

    abonos_bodega_periodo = AbonoBodega.query.filter(
        AbonoBodega.fecha_abono >= inicio_dt,
        AbonoBodega.fecha_abono < fin_dt_query
    ).all()
    bodega_abonos = sum((a.monto for a in abonos_bodega_periodo), Decimal('0'))

    clientes_todos = Cliente.query.all()
    bodega_cartera_pendiente = sum((c.deuda_total for c in clientes_todos if c.deuda_total > 0), Decimal('0'))

    datos_financieros = {
        'ventas_efectivo': float(ventas_efectivo),
        'ventas_transferencia': float(ventas_transferencia),
        'total_ingresos': float(total_ingresos),
        'costos_directos': float(costos_directos),
        'costos_indirectos': float(costos_indirectos),
        'gastos_operacionales': float(gastos_operacionales),
        'total_salidas': total_salidas,
        'balance_neto': balance_neto,
        'bodega_contado': float(bodega_contado),
        'bodega_credito': float(bodega_credito),
        'bodega_abonos': float(bodega_abonos),
        'bodega_cartera_pendiente': float(bodega_cartera_pendiente)
    }

    return render_template(
        'admin/balance_reporte.html',
        fecha_inicio=fecha_inicio_str,
        fecha_fin=fecha_fin_str,
        fecha_generacion=hoy.strftime('%Y-%m-%d %H:%M'),
        datos=datos_financieros
    )

@admin_bp.route('/arqueo', methods=['GET'])
@login_required
@admin_required
def arqueo_caja():
    return redirect(url_for('arqueo_bp.nuevo'))

@admin_bp.route('/arqueo/cerrar', methods=['POST'])
@login_required
@admin_required
def cierre_caja():
    hoy = obtener_hora_bogota().date()
    
    # Prevent double closing
    if ArqueoCaja.query.filter(db.func.date(ArqueoCaja.fecha_arqueo) == hoy).first():
        flash('La caja ya fue cerrada el día de hoy.', 'warning')
        return redirect(url_for('admin_bp.arqueo_caja'))

    base_inicial = request.form.get('base_inicial', 0)
    gastos_dia = request.form.get('gastos_dia', 0)
    efectivo_fisico = request.form.get('efectivo_fisico', 0)
    observaciones_diferencia = request.form.get('observaciones_diferencia', '')

    # Re-calculate totals
    inicio_dia = datetime.combine(hoy, datetime.min.time())
    fin_dia = inicio_dia + timedelta(days=1)
    
    ventas = Sale.query.filter(Sale.fecha_venta >= inicio_dia, Sale.fecha_venta < fin_dia).all()
    total_efectivo = 0.0
    total_digital = 0.0
    for venta in ventas:
        for pago in venta.pagos:
            if pago.metodo_pago.lower() == 'efectivo':
                total_efectivo += float(pago.monto)
            else:
                total_digital += float(pago.monto)

    # Save to DB
    nuevo_arqueo = ArqueoCaja(
        vendedor_id=current_user.id,
        fecha_arqueo=hoy,
        base_inicial=float(base_inicial),
        gastos_del_dia=float(gastos_dia),
        total_efectivo_sistema=total_efectivo,
        total_transferencia_sistema=total_digital,
        efectivo_fisico_contado=float(efectivo_fisico),
        observaciones_diferencia=observaciones_diferencia.strip()
    )
    
    try:
        db.session.add(nuevo_arqueo)
        db.session.commit()
        flash('Caja cerrada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cerrar la caja: {str(e)}', 'danger')

    return redirect(url_for('admin_bp.arqueo_caja'))
