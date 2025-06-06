from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
CORS(app, origins=['http://localhost:3000', 'http://localhost:5173'])

# Configuración de la base de datos
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'tu_password_aqui')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'sistema_educativo')

# Crear conexión a la base de datos
engine = create_engine(f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}')

@app.route('/api/analytics/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'analytics'})

@app.route('/api/analytics/asistencia/general', methods=['GET'])
def analisis_asistencia_general():
    """Análisis general de asistencias"""
    try:
        # Query para obtener datos de asistencias
        query = """
        SELECT 
            a.fecha,
            a.estado,
            g.codigo as grupo_codigo,
            g.materia,
            g.semestre,
            u.nombre_usuario as estudiante,
            p.nombre_usuario as profesor
        FROM asistencias a
        JOIN usuarios u ON a.estudiante_id = u.id
        JOIN grupos g ON a.grupo_id = g.id
        LEFT JOIN profesores_grupos pg ON g.id = pg.grupo_id
        LEFT JOIN usuarios p ON pg.profesor_id = p.id
        WHERE a.fecha >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """
        
        df = pd.read_sql(query, engine)
        
        # Análisis por estado
        estado_counts = df['estado'].value_counts().to_dict()
        
        # Tendencia diaria
        tendencia = df.groupby(['fecha', 'estado']).size().unstack(fill_value=0)
        tendencia_dict = {
            'fechas': tendencia.index.strftime('%Y-%m-%d').tolist(),
            'presente': tendencia.get('PRESENTE', pd.Series()).tolist(),
            'ausente': tendencia.get('AUSENTE', pd.Series()).tolist(),
            'tardanza': tendencia.get('TARDANZA', pd.Series()).tolist(),
            'justificado': tendencia.get('JUSTIFICADO', pd.Series()).tolist()
        }
        
        # Porcentaje de asistencia por materia
        asistencia_materia = df.groupby('materia').apply(
            lambda x: (x['estado'].isin(['PRESENTE', 'TARDANZA']).sum() / len(x) * 100)
        ).round(2).to_dict()
        
        return jsonify({
            'estado_general': estado_counts,
            'tendencia_diaria': tendencia_dict,
            'asistencia_por_materia': asistencia_materia
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/asistencia/grupo/<int:grupo_id>', methods=['GET'])
def analisis_asistencia_grupo(grupo_id):
    """Análisis de asistencias por grupo"""
    try:
        query = f"""
        SELECT 
            a.fecha,
            a.estado,
            u.nombre_usuario as estudiante,
            u.email
        FROM asistencias a
        JOIN usuarios u ON a.estudiante_id = u.id
        WHERE a.grupo_id = {grupo_id}
        ORDER BY a.fecha DESC
        """
        
        df = pd.read_sql(query, engine)
        
        if df.empty:
            return jsonify({'mensaje': 'No hay datos de asistencia para este grupo'})
        
        # Análisis por estudiante
        estudiante_stats = df.groupby('estudiante').agg({
            'estado': lambda x: {
                'total_clases': len(x),
                'presentes': (x == 'PRESENTE').sum(),
                'ausentes': (x == 'AUSENTE').sum(),
                'tardanzas': (x == 'TARDANZA').sum(),
                'justificados': (x == 'JUSTIFICADO').sum(),
                'porcentaje_asistencia': round((x.isin(['PRESENTE', 'TARDANZA']).sum() / len(x) * 100), 2)
            }
        }).to_dict()['estado']
        
        # Tendencia semanal
        df['semana'] = pd.to_datetime(df['fecha']).dt.isocalendar().week
        tendencia_semanal = df.groupby(['semana', 'estado']).size().unstack(fill_value=0).to_dict('index')
        
        return jsonify({
            'estadisticas_estudiantes': estudiante_stats,
            'tendencia_semanal': tendencia_semanal
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/asistencia/estudiante/<int:estudiante_id>', methods=['GET'])
def analisis_asistencia_estudiante(estudiante_id):
    """Análisis de asistencias de un estudiante específico"""
    try:
        query = f"""
        SELECT 
            a.fecha,
            a.estado,
            g.codigo as grupo_codigo,
            g.materia
        FROM asistencias a
        JOIN grupos g ON a.grupo_id = g.id
        WHERE a.estudiante_id = {estudiante_id}
        ORDER BY a.fecha DESC
        """
        
        df = pd.read_sql(query, engine)
        
        if df.empty:
            return jsonify({'mensaje': 'No hay datos de asistencia para este estudiante'})
        
        # Estadísticas generales
        stats = {
            'total_clases': len(df),
            'presentes': (df['estado'] == 'PRESENTE').sum(),
            'ausentes': (df['estado'] == 'AUSENTE').sum(),
            'tardanzas': (df['estado'] == 'TARDANZA').sum(),
            'justificados': (df['estado'] == 'JUSTIFICADO').sum(),
            'porcentaje_asistencia': round((df['estado'].isin(['PRESENTE', 'TARDANZA']).sum() / len(df) * 100), 2)
        }
        
        # Por materia
        por_materia = df.groupby('materia').apply(
            lambda x: {
                'total': len(x),
                'asistencias': (x['estado'].isin(['PRESENTE', 'TARDANZA'])).sum(),
                'porcentaje': round((x['estado'].isin(['PRESENTE', 'TARDANZA']).sum() / len(x) * 100), 2)
            }
        ).to_dict()
        
        return jsonify({
            'estadisticas_generales': stats,
            'por_materia': por_materia
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/reporte/profesor/<int:profesor_id>', methods=['GET'])
def reporte_profesor(profesor_id):
    """Reporte completo para un profesor"""
    try:
        # Obtener grupos del profesor
        query_grupos = f"""
        SELECT DISTINCT
            g.id,
            g.codigo,
            g.materia,
            COUNT(DISTINCT eg.estudiante_id) as total_estudiantes
        FROM grupos g
        JOIN profesores_grupos pg ON g.id = pg.grupo_id
        LEFT JOIN estudiantes_grupos eg ON g.id = eg.grupo_id AND eg.activo = 1
        WHERE pg.profesor_id = {profesor_id} AND pg.activo = 1
        GROUP BY g.id, g.codigo, g.materia
        """
        
        df_grupos = pd.read_sql(query_grupos, engine)
        
        resultados = []
        
        for _, grupo in df_grupos.iterrows():
            # Análisis de asistencia por grupo
            query_asistencia = f"""
            SELECT 
                a.estado,
                COUNT(*) as cantidad
            FROM asistencias a
            WHERE a.grupo_id = {grupo['id']}
            GROUP BY a.estado
            """
            
            df_asistencia = pd.read_sql(query_asistencia, engine)
            
            if not df_asistencia.empty:
                total = df_asistencia['cantidad'].sum()
                asistencia_data = df_asistencia.set_index('estado')['cantidad'].to_dict()
                
                porcentaje_asistencia = 0
                if total > 0:
                    presentes = asistencia_data.get('PRESENTE', 0) + asistencia_data.get('TARDANZA', 0)
                    porcentaje_asistencia = round((presentes / total) * 100, 2)
                
                resultados.append({
                    'grupo_id': int(grupo['id']),
                    'codigo': grupo['codigo'],
                    'materia': grupo['materia'],
                    'total_estudiantes': int(grupo['total_estudiantes']),
                    'estadisticas_asistencia': asistencia_data,
                    'porcentaje_asistencia': porcentaje_asistencia
                })
        
        return jsonify({
            'grupos': resultados,
            'total_grupos': len(resultados)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/prediccion/desercion', methods=['GET'])
def prediccion_desercion():
    """Identificar estudiantes en riesgo de deserción basado en asistencias"""
    try:
        # Obtener datos de los últimos 30 días
        query = """
        SELECT 
            u.id as estudiante_id,
            u.nombre_usuario,
            u.email,
            COUNT(CASE WHEN a.estado = 'AUSENTE' THEN 1 END) as ausencias,
            COUNT(*) as total_clases,
            ROUND(COUNT(CASE WHEN a.estado IN ('PRESENTE', 'TARDANZA') THEN 1 END) * 100.0 / COUNT(*), 2) as porcentaje_asistencia
        FROM usuarios u
        JOIN asistencias a ON u.id = a.estudiante_id
        WHERE a.fecha >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        GROUP BY u.id, u.nombre_usuario, u.email
        HAVING porcentaje_asistencia < 75
        ORDER BY porcentaje_asistencia ASC
        """
        
        df = pd.read_sql(query, engine)
        
        # Clasificar riesgo
        df['nivel_riesgo'] = pd.cut(
            df['porcentaje_asistencia'], 
            bins=[0, 50, 65, 75, 100],
            labels=['CRITICO', 'ALTO', 'MEDIO', 'BAJO']
        )
        
        estudiantes_riesgo = df.to_dict('records')
        
        return jsonify({
            'estudiantes_en_riesgo': estudiantes_riesgo,
            'total_en_riesgo': len(estudiantes_riesgo)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(port=5001, debug=True)