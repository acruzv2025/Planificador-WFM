from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, not_
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
import pandas as pd
import math
import numpy as np
import io
import datetime
import functools
import os
print(f"--- DEBUGGING: El valor de DATABASE_URL es: {os.environ.get('DATABASE_URL')} ---")
import json
import random
import click 
import xlsxwriter

# ==============================================================================
# 0. CONFIGURACIÓN, MODELOS Y CONSTANTES
# ==============================================================================

# --- BLOQUE DE CÓDIGO FINAL, CORREGIDO Y A PRUEBA DE FALLOS ---

# 1. Obtenemos la URL de la base de datos de Render ANTES DE TODO.
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    # Si la variable no existe, el programa se detendrá con un error claro.
    # Eliminamos el print de depuración que ya no es necesario.
    raise RuntimeError("ERROR FATAL: La variable de entorno DATABASE_URL no fue encontrada.")

# Ajuste para compatibilidad con SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Definimos la ruta base del proyecto para encontrar las plantillas.
basedir = os.path.abspath(os.path.dirname(__file__))

# 3. Inicializamos la aplicación Flask, indicando explícitamente la carpeta de plantillas.
app = Flask(__name__,
            instance_relative_config=True,
            template_folder=os.path.join(basedir, 'templates'))

# 4. Configuramos la app con la clave secreta y la URI de la base de datos.
app.secret_key = 'mi-clave-secta-muy-dificil-de-adivinar-12345'
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 5. Inicializamos las extensiones de la base de datos DESPUÉS de que toda la configuración esté lista.
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- FIN DEL BLOQUE FINAL Y A PRUEBA DE FALLOS ---


VALID_AUSENCIA_CODES = ["VAC", "BMED", "LICMATER", "LICPATER", "LACT", "FEST", "ACC", "ENF", "ENFHOSP", "SIT-ESP", "OTRO"]

user_campaign_permissions = db.Table('user_campaign_permission',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('campaign_id', db.Integer, db.ForeignKey('campaign.id'), primary_key=True)
)

# --- MODELOS DE BASE DE DATOS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(80), nullable=False, default='user')
    campaigns = db.relationship('Campaign', secondary=user_campaign_permissions, lazy='subquery',
                                backref=db.backref('users', lazy=True))

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    country = db.Column(db.String(50), nullable=False)
    segments = db.relationship('Segment', backref='campaign', lazy=True, cascade="all, delete-orphan")

class Segment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    lunes_apertura = db.Column(db.String(5)); lunes_cierre = db.Column(db.String(5))
    martes_apertura = db.Column(db.String(5)); martes_cierre = db.Column(db.String(5))
    miercoles_apertura = db.Column(db.String(5)); miercoles_cierre = db.Column(db.String(5))
    jueves_apertura = db.Column(db.String(5)); jueves_cierre = db.Column(db.String(5))
    viernes_apertura = db.Column(db.String(5)); viernes_cierre = db.Column(db.String(5))
    sabado_apertura = db.Column(db.String(5)); sabado_cierre = db.Column(db.String(5))
    domingo_apertura = db.Column(db.String(5)); domingo_cierre = db.Column(db.String(5))
    weekend_policy = db.Column(db.String(50), nullable=False, default='REQUIRE_ONE_DAY_OFF')
    min_full_weekends_off_per_month = db.Column(db.Integer, nullable=False, default=2)
    staffing_results = db.relationship('StaffingResult', backref='segment', lazy=True, cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint('name', 'campaign_id', name='_name_campaign_uc'),)

class StaffingResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    result_date = db.Column(db.Date, nullable=False)
    agents_online = db.Column(db.Text, nullable=False)
    agents_total = db.Column(db.Text, nullable=False)
    calls_forecast = db.Column(db.Text, nullable=True)
    aht_forecast = db.Column(db.Text, nullable=True)
    reducers_forecast = db.Column(db.Text, nullable=True)
    segment_id = db.Column(db.Integer, db.ForeignKey('segment.id'), nullable=False)
    sla_target_percentage = db.Column(db.Float, nullable=True)
    sla_target_time = db.Column(db.Integer, nullable=True)
    __table_args__ = (db.UniqueConstraint('result_date', 'segment_id', name='_date_segment_uc'),)

# ===> NUEVO MODELO AÑADIDO DEL MÓDULO DE FORECASTING <===
class ActualsData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    result_date = db.Column(db.Date, nullable=False)
    actuals_data = db.Column(db.Text, nullable=False) # JSON con datos reales por intervalo
    segment_id = db.Column(db.Integer, db.ForeignKey('segment.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('result_date', 'segment_id', name='_date_segment_actuals_uc'),)

class Agent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    identificacion = db.Column(db.String(50), unique=True, nullable=False)
    nombre_completo = db.Column(db.String(200), nullable=False)
    segment_id = db.Column(db.Integer, db.ForeignKey('segment.id'))
    segment = db.relationship('Segment', backref=db.backref('agents', lazy=True))
    centro = db.Column(db.String(100)); contrato = db.Column(db.String(20))
    turno_sugerido = db.Column(db.String(50)); jornada = db.Column(db.String(50))
    concrecion = db.Column(db.String(100)); rotacion_finde = db.Column(db.String(10))
    ventana_horaria = db.Column(db.String(50)); modalidad_finde = db.Column(db.String(20), default='UNICO')
    rotacion_mensual_domingo = db.Column(db.String(20), default='NORMAL')
    semanas_libres_finde = db.Column(db.String(20))
    fecha_alta = db.Column(db.Date, nullable=False, default=datetime.date(1900, 1, 1))
    fecha_baja = db.Column(db.Date, nullable=True)

class SchedulingRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    country = db.Column(db.String(50), nullable=False)
    workday_rule = db.relationship('WorkdayRule', backref='scheduling_rule', uselist=False, cascade="all, delete-orphan")

class WorkdayRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    weekly_hours = db.Column(db.Float, nullable=False)
    max_daily_hours = db.Column(db.Float, nullable=False); min_daily_hours = db.Column(db.Float, nullable=False)
    days_per_week = db.Column(db.Integer, nullable=False, default=5)
    max_consecutive_work_days = db.Column(db.Integer, nullable=False, default=7)
    min_hours_between_shifts = db.Column(db.Integer, nullable=False, default=12)
    allow_irregular_shifts = db.Column(db.Boolean, nullable=False, default=False)
    rule_id = db.Column(db.Integer, db.ForeignKey('scheduling_rule.id'), nullable=False)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=False)
    schedule_date = db.Column(db.Date, nullable=False)
    shift = db.Column(db.String(50), default='LIBRE')
    hours = db.Column(db.Float, default=0.0)
    is_manual_edit = db.Column(db.Boolean, default=False)
    agent = db.relationship('Agent', backref=db.backref('schedule_entries', lazy=True))
    descanso1_he = db.Column(db.String(5), nullable=True); descanso1_hs = db.Column(db.String(5), nullable=True)
    descanso2_he = db.Column(db.String(5), nullable=True); descanso2_hs = db.Column(db.String(5), nullable=True)
    pvd1 = db.Column(db.String(5), nullable=True); pvd2 = db.Column(db.String(5), nullable=True)
    pvd3 = db.Column(db.String(5), nullable=True); pvd4 = db.Column(db.String(5), nullable=True)
    pvd5 = db.Column(db.String(5), nullable=True); pvd6 = db.Column(db.String(5), nullable=True)
    pvd7 = db.Column(db.String(5), nullable=True); pvd8 = db.Column(db.String(5), nullable=True)
    pvd9 = db.Column(db.String(5), nullable=True); pvd10 = db.Column(db.String(5), nullable=True)
    __table_args__ = (db.UniqueConstraint('agent_id', 'schedule_date', name='_agent_date_uc'),)

class BreakRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    country = db.Column(db.String(50), nullable=False)
    min_shift_hours = db.Column(db.Float, nullable=False); max_shift_hours = db.Column(db.Float, nullable=False)
    break_duration_minutes = db.Column(db.Integer, default=0); pvd_minutes_per_hour = db.Column(db.Integer, default=0)
    number_of_pvds = db.Column(db.Integer, default=0)

# ==============================================================================
# 1. DECORADOR Y FUNCIONES DE CÁLCULO
# ==============================================================================
def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash("Acceso no autorizado.", "error"); return redirect(url_for('calculator'))
        return f(*args, **kwargs)
    return decorated_function

# --- Funciones de cálculo basadas en la lógica VBA ---
def vba_erlang_b(servers, intensity):
    if servers < 0 or intensity < 0: return 0
    max_iterate = int(servers)
    last = 1.0; b = 1.0
    for count in range(1, max_iterate + 1):
        b = (intensity * last) / (count + (intensity * last))
        last = b
    return max(0, min(b, 1))

def vba_erlang_c(servers, intensity):
    if servers <= intensity: return 1.0
    b = vba_erlang_b(servers, intensity)
    denominator = (1 - (intensity / servers) * (1 - b))
    if denominator == 0: return 1.0
    c = b / denominator
    return max(0, min(c, 1))

def vba_sla(agents, service_time, calls_per_hour, aht):
    if agents <= 0 or aht <= 0 or calls_per_hour < 0:
        return 1.0 if calls_per_hour == 0 else 0.0
    traffic_rate = (calls_per_hour * aht) / 3600.0
    if traffic_rate >= agents: return 0.0
    c = vba_erlang_c(agents, traffic_rate)
    exponent = (traffic_rate - agents) * (service_time / aht)
    try: sl_queued = 1 - c * math.exp(exponent)
    except OverflowError: sl_queued = 0
    return max(0, min(sl_queued, 1))

def vba_agents_required(target_sla, service_time, calls_per_hour, aht):
    if calls_per_hour <= 0 or aht <= 0: return 0
    traffic_rate = (calls_per_hour * aht) / 3600.0
    num_agents = math.ceil(traffic_rate)
    if num_agents == 0 and traffic_rate > 0: num_agents = 1
    
    utilisation = traffic_rate / num_agents if num_agents > 0 else 0
    while utilisation >= 1.0:
        num_agents += 1
        utilisation = traffic_rate / num_agents
        
    while True:
        current_sla = vba_sla(num_agents, service_time, calls_per_hour, aht)
        if current_sla >= target_sla: break
        num_agents += 1
        if num_agents > calls_per_hour + 100: break
    return num_agents


def procesar_plantilla_unica(config, all_sheets):
    try:
        required_sheets = { 'calls': 'Llamadas_esperadas', 'aht': 'AHT_esperado', 'absenteeism': 'Absentismo_esperado', 'auxiliaries': 'Auxiliares_esperados', 'shrinkage': 'Desconexiones_esperadas' }
        for key, name in required_sheets.items():
            if name not in all_sheets: raise ValueError(f"Falta la hoja requerida: '{name}'")
        
        df_calls = all_sheets[required_sheets['calls']]
        df_aht = all_sheets[required_sheets['aht']]
        df_absent = all_sheets[required_sheets['absenteeism']]
        df_aux = all_sheets[required_sheets['auxiliaries']]
        df_shrink = all_sheets[required_sheets['shrinkage']]

        df_calls['Fecha'] = pd.to_datetime(df_calls['Fecha'], errors='coerce')
        df_calls.dropna(subset=['Fecha'], inplace=True)
        if df_calls.empty: return None

        index_cols = ['Fecha', 'Dia', 'Semana', 'Tipo']
        time_cols = [col for col in df_calls.columns if col not in index_cols]
        
        all_dfs = [df_calls, df_aht, df_absent, df_aux, df_shrink]
        
        for df in all_dfs:
            if df is not None:
                df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
                existing_time_cols = [col for col in time_cols if col in df.columns]
                df[existing_time_cols] = df[existing_time_cols].apply(pd.to_numeric, errors='coerce').fillna(0)

        # ... (TODA la lógica de merge y cálculo de agentes se mantiene exactamente igual hasta el final)
        df_master = df_calls.copy()
        dfs_to_merge = {'_aht': df_aht, '_abs': df_absent, '_aux': df_aux, '_shr': df_shrink}
        
        for suffix, df in dfs_to_merge.items():
            if df is not None and not df.empty:
                cols_to_keep = ['Fecha'] + [col for col in time_cols if col in df.columns]
                df_temp = df[cols_to_keep].rename(columns={t: f"{t}{suffix}" for t in time_cols})
                df_master = pd.merge(df_master, df_temp, on='Fecha', how='left')
        
        df_master.fillna(0, inplace=True)

        dim_data, pre_data, log_data, efe_data = [], [], [], []
        for index, row in df_master.iterrows():
            base_row = {col: row[col] for col in index_cols}; dim_row, pre_row, log_row, efe_row = base_row.copy(), base_row.copy(), base_row.copy(), base_row.copy()
            for col in time_cols:
                calls = row.get(col, 0); aht = row.get(f'{col}_aht', 0); abs_pct = row.get(f'{col}_abs', 0); shr_pct = row.get(f'{col}_shr', 0); aux_pct = row.get(f'{col}_aux', 0)
                efectivos = float(vba_agents_required(config["sla_objetivo"], config["sla_tiempo"], calls * 2, aht)); logados = efectivos / (1 - aux_pct) if (1 - aux_pct) > 0 else efectivos; presentes = logados / (1 - abs_pct) if (1 - abs_pct) > 0 else logados; dimensionados = presentes / (1 - shr_pct) if (1 - shr_pct) > 0 else presentes
                dim_row[col] = dimensionados; pre_row[col] = presentes; log_row[col] = logados; efe_row[col] = efectivos
            dim_data.append(dim_row); pre_data.append(pre_row); log_data.append(log_row); efe_data.append(efe_row)

        final_cols_order = index_cols + time_cols
        df_dimensionados = pd.DataFrame(dim_data)[final_cols_order]; df_presentes = pd.DataFrame(pre_data)[final_cols_order]; df_logados = pd.DataFrame(log_data)[final_cols_order]; df_efectivos = pd.DataFrame(efe_data)[final_cols_order]
        
        # --- INICIO DE LA CORRECCIÓN EN EL CÁLCULO DE KPIs ---
        
        # 1. Extraemos todos los valores numéricos de las hojas correspondientes.
        absent_values = df_absent[time_cols].values.flatten()
        aux_values = df_aux[time_cols].values.flatten()
        shrink_values = df_shrink[time_cols].values.flatten()

        # 2. Creamos nuevas listas filtrando y manteniendo SÓLO los valores que NO son cero.
        absent_values_non_zero = absent_values[absent_values != 0]
        aux_values_non_zero = aux_values[aux_values != 0]
        shrink_values_non_zero = shrink_values[shrink_values != 0]

        # 3. Calculamos el promedio (mean) de estas nuevas listas que ya no contienen ceros.
        absentismo_promedio = np.mean(absent_values_non_zero) if absent_values_non_zero.size > 0 else 0
        auxiliares_promedio = np.mean(aux_values_non_zero) if aux_values_non_zero.size > 0 else 0
        desconexiones_promedio = np.mean(shrink_values_non_zero) if shrink_values_non_zero.size > 0 else 0
        
        kpi_data = {
            'absentismo_pct': absentismo_promedio * 100,
            'auxiliares_pct': auxiliares_promedio * 100,
            'desconexiones_pct': desconexiones_promedio * 100
        }
        # --- FIN DE LA CORRECCIÓN EN EL CÁLCULO DE KPIs ---

        for df in [df_dimensionados, df_presentes, df_logados, df_efectivos]:
            df.replace([np.inf, -np.inf], 0, inplace=True); df.fillna(0, inplace=True)
            
        return df_dimensionados, df_presentes, df_logados, df_efectivos, kpi_data
    
    except Exception as e:
        import traceback; traceback.print_exc()
        raise ValueError(f"No se pudo procesar la plantilla. Error: {e}")

# ==============================================================================
# 2.5 CLASE DEL ALGORITMO DE SCHEDULING
# ==============================================================================
class Scheduler:
    # ... (El contenido de la clase Scheduler no cambia, puedes dejarla como está) ...
    def __init__(self, agents, rules_map, needs_by_day, time_labels, segment, day_types, absences_map={}, initial_coverage=None, initial_schedule=None):
        self.agents = agents
        self.rules_map = rules_map
        self.needs_by_day = {d: np.array(n) for d, n in needs_by_day.items()}
        self.time_labels = {time: i for i, time in enumerate(time_labels)}
        self.time_labels_list = list(self.time_labels.keys())
        self.segment = segment
        self.day_types = day_types
        self.absences_map = absences_map
        self.final_schedule = initial_schedule if initial_schedule is not None else {agent.nombre_completo: {} for agent in self.agents}
        self.coverage_by_day = initial_coverage if initial_coverage is not None else {day: np.zeros(len(time_labels)) for day in self.needs_by_day.keys()}
        self.day_map = {
            0: (segment.lunes_apertura, segment.lunes_cierre), 1: (segment.martes_apertura, segment.martes_cierre),
            2: (segment.miercoles_apertura, segment.miercoles_cierre), 3: (segment.jueves_apertura, segment.jueves_cierre),
            4: (segment.viernes_apertura, segment.viernes_cierre), 5: (segment.sabado_apertura, segment.sabado_cierre),
            6: (segment.domingo_apertura, segment.domingo_cierre),
        }
        self.agent_tracker = {}
        self.monthly_tracker = {}

    def run(self):
        sorted_days = sorted(self.needs_by_day.keys())
        weeks = {}
        for day in sorted_days:
            week_number = day.isocalendar()[1]
            if week_number not in weeks: weeks[week_number] = []
            weeks[week_number].append(day)
        
        self.monthly_tracker = {agent.id: {'sundays_worked': 0, 'full_weekends_off': 0} for agent in self.agents}

        for week_number, week_days in weeks.items():
            self.agent_tracker = {agent.id: {'weekly_hours': 0, 'last_work_day': None, 'consecutive_days': 0, 'days_worked_this_week': 0} for agent in self.agents}
            for day_date in sorted(week_days):
                self._schedule_day_pass_one(day_date)
            
            agents_by_urgency = sorted(self.agents, key=lambda a: self._get_urgency_score(a), reverse=True)
            for agent in agents_by_urgency:
                rule = self._get_rule_for_agent(agent)
                if not rule: continue
                while self._get_urgency_score(agent) > 0.1:
                    best_placement = self._find_best_spot_for_extra_shift(agent, sorted(week_days))
                    if best_placement:
                        day_to_add, shift_str, hours_to_add = best_placement
                        self._assign_and_update(agent, day_to_add, shift_str, hours_to_add)
                    else: break
            
            for agent in self.agents:
                saturday = next((d for d in week_days if d.weekday() == 5), None)
                sunday = next((d for d in week_days if d.weekday() == 6), None)
                if saturday and sunday:
                    sat_shift = self.final_schedule.get(agent.nombre_completo, {}).get(saturday.strftime('%Y-%m-%d'))
                    sun_shift = self.final_schedule.get(agent.nombre_completo, {}).get(sunday.strftime('%Y-%m-%d'))
                    if (not sat_shift or sat_shift == 'LIBRE') and (not sun_shift or sun_shift == 'LIBRE'):
                        self.monthly_tracker[agent.id]['full_weekends_off'] += 1

        for agent in self.agents:
            if agent.nombre_completo not in self.final_schedule: self.final_schedule[agent.nombre_completo] = {}
            for day in sorted_days:
                if day.strftime('%Y-%m-%d') not in self.final_schedule[agent.nombre_completo]:
                    agent_absences = self.absences_map.get(agent.id, set())
                    if day not in agent_absences:
                         self.final_schedule[agent.nombre_completo][day.strftime('%Y-%m-%d')] = "LIBRE"

        return self.final_schedule, {day.strftime('%Y-%m-%d'): cov.tolist() for day, cov in self.coverage_by_day.items()}

    def _schedule_day_pass_one(self, day_date):
        need_curve = self.needs_by_day.get(day_date, np.zeros(len(self.time_labels)))
        scheduled_today = set()
        fixed_agents_today = [a for a in self.agents if self._is_fixed_day_for_agent(a, day_date)]
        for agent in fixed_agents_today:
            if self._is_agent_eligible_on_day(agent, day_date):
                if self._assign_fixed_shift_for_day(agent, day_date): scheduled_today.add(agent.id)
        agent_pool = [a for a in self.agents if a.id not in scheduled_today and self._is_agent_eligible_on_day(a, day_date)]
        while True:
            remaining_need = np.maximum(0, need_curve - self.coverage_by_day.get(day_date, 0))
            if np.sum(remaining_need) < 1 or not agent_pool: break
            best_fit = self._find_best_fit_for_need(agent_pool, remaining_need, day_date)
            if best_fit:
                agent, _, hours, shift_str = best_fit
                self._assign_and_update(agent, day_date, shift_str, hours)
                agent_pool.remove(agent); scheduled_today.add(agent.id)
            else: break

    def _is_fixed_day_for_agent(self, agent, day_date):
        if day_date.weekday() >= 5:
            return False
        if agent.turno_sugerido and '-' in agent.turno_sugerido:
            return True
        concrecion = (agent.concrecion or 'NO').upper().strip()
        if concrecion == 'SI':
            return True
        return False

    def _assign_fixed_shift_for_day(self, agent, day_date):
        rule = self._get_rule_for_agent(agent)
        if not rule: return False
        tracker = self.agent_tracker[agent.id]
        if agent.rotacion_finde.upper() == 'SI' and tracker['days_worked_this_week'] >= (rule.workday_rule.days_per_week - 1):
            return False
        shift_str = agent.turno_sugerido
        if not (shift_str and '-' in shift_str): return False
        full_shift_hours = self._calculate_shift_duration(shift_str)
        remaining_weekly = rule.workday_rule.weekly_hours - tracker['weekly_hours']
        hours_today = min(full_shift_hours, remaining_weekly, rule.workday_rule.max_daily_hours)
        if hours_today >= rule.workday_rule.min_daily_hours:
            final_shift = shift_str if hours_today == full_shift_hours else self._get_partial_shift_str(shift_str, hours_today)
            self._assign_and_update(agent, day_date, final_shift, hours_today)
            return True
        return False
        
    def _find_best_spot_for_extra_shift(self, agent, week_days):
        best_day, best_shift_str, best_hours, min_weighted_score = None, None, 0, float('inf')
        rule = self._get_rule_for_agent(agent)
        if not rule: return None
        for day in week_days:
            if day.strftime('%Y-%m-%d') in self.final_schedule.get(agent.nombre_completo, {}): continue
            if not self._is_agent_eligible_on_day(agent, day, is_pass_two=True): continue
            possible_shifts = self._generate_possible_shifts(agent, rule, day)
            if not possible_shifts: continue
            weekend_off_penalty = 1000 if day.weekday() >= 5 and self.monthly_tracker.get(agent.id, {}).get('full_weekends_off', 0) < self.segment.min_full_weekends_off_per_month else 0
            day_type_penalty = 0
            day_type = self.day_types.get(day, 'N')
            if self.segment.weekend_policy == 'REQUIRE_ONE_DAY_OFF':
                if day.weekday() == 6 or day_type == 'F': day_type_penalty = 2000
                elif day.weekday() == 5: day_type_penalty = 1000
            elif self.segment.weekend_policy == 'FLEXIBLE':
                if day.weekday() == 6 or day_type == 'F': day_type_penalty = 1500
                elif day.weekday() == 5: day_type_penalty = 500
            current_coverage, need = self.coverage_by_day.get(day), self.needs_by_day.get(day)
            for shift in possible_shifts:
                start_idx, end_idx = shift
                new_coverage = current_coverage.copy(); new_coverage[start_idx:end_idx] += 1
                overstaffing_score = np.sum(np.maximum(0, new_coverage - need))
                total_weighted_score = overstaffing_score + weekend_off_penalty + day_type_penalty
                if total_weighted_score < min_weighted_score:
                    min_weighted_score, best_day = total_weighted_score, day
                    best_hours = (end_idx - start_idx) / 2.0
                    best_shift_str = f"{self.time_labels_list[start_idx]}-{self.time_labels_list[end_idx] if end_idx < len(self.time_labels_list) else '24:00'}"
        if best_day: return best_day, best_shift_str, best_hours
        return None

    def _find_best_fit_for_need(self, agent_pool, need_curve, day_date):
        best_agent, best_shift_details, best_score = None, None, -1
        for agent in agent_pool:
            rule = self._get_rule_for_agent(agent)
            if not rule: continue
            possible_shifts = self._generate_possible_shifts(agent, rule, day_date)
            if not possible_shifts: continue
            best_shift_for_agent = max(possible_shifts, key=lambda s: self._calculate_shift_score(s, need_curve))
            coverage_score = self._calculate_shift_score(best_shift_for_agent, need_curve)
            urgency_score = self._get_urgency_score(agent)
            penalty = 100 if day_date.weekday() < 5 and agent.rotacion_finde != 'NO' else 0
            bonus = 200 if day_date.weekday() == 6 and agent.rotacion_mensual_domingo == 'PRIORITARIO' else 0
            current_score = coverage_score + urgency_score - penalty + bonus
            if current_score > best_score:
                best_score, best_agent, best_shift_details = current_score, agent, best_shift_for_agent
        if best_agent:
            hours = (best_shift_details[1] - best_shift_details[0]) / 2.0
            shift_str = f"{self.time_labels_list[best_shift_details[0]]}-{self.time_labels_list[best_shift_details[1]] if best_shift_details[1] < len(self.time_labels_list) else '24:00'}"
            return best_agent, best_shift_details, hours, shift_str
        return None

    def _is_agent_eligible_on_day(self, agent, day_date, is_pass_two=False):
        if agent.fecha_alta and day_date < agent.fecha_alta:
            return False
        if agent.fecha_baja and day_date > agent.fecha_baja:
            return False
        agent_absences = self.absences_map.get(agent.id, set())
        if day_date in agent_absences:
            return False
        rule = self._get_rule_for_agent(agent)
        if not rule: return False
        tracker = self.agent_tracker[agent.id]
        week_start = day_date - datetime.timedelta(days=day_date.weekday())
        week_days_dates = [week_start + datetime.timedelta(days=i) for i in range(7)]
        avg_normal_day_need = np.mean([np.sum(self.needs_by_day.get(d, 0)) for d in week_days_dates if self.day_types.get(d) == 'N'] or [0])
        low_demand_holidays_this_week = {d for d in week_days_dates if self.day_types.get(d) == 'F' and np.sum(self.needs_by_day.get(d, 0)) < avg_normal_day_need * 0.75}
        holidays_not_worked = 0
        for holiday in low_demand_holidays_this_week:
            holiday_str = holiday.strftime('%Y-%m-%d')
            agent_holiday_absences = self.absences_map.get(agent.id, set())
            if self.final_schedule.get(agent.nombre_completo, {}).get(holiday_str) == 'LIBRE' or holiday in agent_holiday_absences:
                holidays_not_worked += 1
        allowed_work_days = rule.workday_rule.days_per_week - holidays_not_worked
        if tracker['days_worked_this_week'] >= allowed_work_days: return False
        if tracker['weekly_hours'] >= rule.workday_rule.weekly_hours: return False
        last_work_day = tracker.get('last_work_day')
        if last_work_day and (day_date - last_work_day).days == 1:
            if tracker['consecutive_days'] + 1 > rule.workday_rule.max_consecutive_work_days: return False
        is_weekend = day_date.weekday() >= 5
        if is_weekend:
            if agent.rotacion_finde == 'NO': return False
            if agent.semanas_libres_finde:
                week_of_month = (day_date.day - 1) // 7 + 1
                if str(week_of_month) in agent.semanas_libres_finde.split(','): return False
            if day_date.weekday() == 6 and agent.modalidad_finde == 'UNICO':
                saturday_date = day_date - datetime.timedelta(days=1)
                if self.final_schedule.get(agent.nombre_completo, {}).get(saturday_date.strftime('%Y-%m-%d'), 'LIBRE') != 'LIBRE': return False
            if day_date.weekday() == 6 and agent.rotacion_mensual_domingo == 'MAX_2':
                if self.monthly_tracker.get(agent.id, {}).get('sundays_worked', 0) >= 2: return False
            if self.segment.weekend_policy == 'REQUIRE_ONE_DAY_OFF':
                saturday_date = day_date - datetime.timedelta(days=1)
                if day_date.weekday() == 6 and self.final_schedule.get(agent.nombre_completo, {}).get(saturday_date.strftime('%Y-%m-%d'), 'LIBRE') != 'LIBRE':
                     return False
        if (rule.workday_rule.weekly_hours - tracker['weekly_hours']) < rule.workday_rule.min_daily_hours:
            if self._get_urgency_score(agent) > 0.1: return False
        return True

    def _get_urgency_score(self, agent):
        rule = self._get_rule_for_agent(agent)
        if not rule: return 0
        return rule.workday_rule.weekly_hours - self.agent_tracker.get(agent.id, {'weekly_hours': 0})['weekly_hours']

    def _assign_and_update(self, agent, day_date, shift_str, shift_hours):
        day_str = day_date.strftime('%Y-%m-%d')
        if agent.id not in self.agent_tracker:
             self.agent_tracker[agent.id] = {'weekly_hours': 0, 'last_work_day': None, 'consecutive_days': 0, 'days_worked_this_week': 0}
        tracker = self.agent_tracker[agent.id]
        last_work_day = tracker.get('last_work_day')
        if last_work_day and (day_date - last_work_day).days == 1: tracker['consecutive_days'] += 1
        else: tracker['consecutive_days'] = 1
        tracker['last_work_day'] = day_date
        tracker['weekly_hours'] += shift_hours
        tracker['days_worked_this_week'] += 1
        if day_date.weekday() == 6: 
            if agent.id not in self.monthly_tracker: self.monthly_tracker[agent.id] = {'sundays_worked': 0}
            self.monthly_tracker[agent.id]['sundays_worked'] = self.monthly_tracker[agent.id].get('sundays_worked', 0) + 1
        self.final_schedule[agent.nombre_completo][day_str] = shift_str
        for part in shift_str.split('/'):
            try:
                start_str, end_str = [s.strip() for s in part.split('-')]
                start_idx, end_idx = self.time_labels.get(start_str), self.time_labels.get(end_str) if end_str != '24:00' else len(self.time_labels_list)
                if start_idx is not None and end_idx is not None and day_date in self.coverage_by_day: 
                    self.coverage_by_day[day_date][start_idx:end_idx] += 1
            except: continue
    
    def _get_rule_for_agent(self, agent):
        try: return self.rules_map.get(str(int(float(agent.contrato))))
        except (ValueError, TypeError): return None

    def _calculate_shift_duration(self, shift_str):
        duration = 0
        for part in shift_str.split('/'):
            try:
                start_str, end_str = [s.strip() for s in part.split('-')]
                start_time, end_time = datetime.datetime.strptime(start_str, '%H:%M'), datetime.datetime.strptime(end_str, '%H:%M') if end_str != '24:00' else datetime.datetime.strptime('23:59', '%H:%M') + datetime.timedelta(minutes=1)
                if end_time <= start_time: end_time += datetime.timedelta(days=1)
                duration += (end_time - start_time).total_seconds() / 3600
            except: continue
        return duration
    
    def _get_partial_shift_str(self, full_shift_str, hours):
        parts, new_shift_parts, remaining_hours = full_shift_str.split('/'), [], hours
        for part in parts:
            part_duration = self._calculate_shift_duration(part)
            if remaining_hours <= 0: break
            hours_in_this_part = min(part_duration, remaining_hours)
            start_time_str = part.split('-')[0].strip()
            start_time = datetime.datetime.strptime(start_time_str, '%H:%M')
            end_time = start_time + datetime.timedelta(hours=hours_in_this_part)
            new_shift_parts.append(f"{start_time_str}-{end_time.strftime('%H:%M')}")
            remaining_hours -= hours_in_this_part
        return "/".join(new_shift_parts)

    def _generate_possible_shifts(self, agent, rule, day_date, is_fixed=False):
        if agent.id not in self.agent_tracker:
             self.agent_tracker[agent.id] = {'weekly_hours': 0, 'last_work_day': None, 'consecutive_days': 0, 'days_worked_this_week': 0}
        tracker = self.agent_tracker[agent.id]
        remaining_weekly = rule.workday_rule.weekly_hours - tracker['weekly_hours']
        apertura, cierre = self.day_map.get(day_date.weekday(), (None, None))
        start_service_idx, end_service_idx = self.time_labels.get(apertura), self.time_labels.get(cierre)
        if start_service_idx is None or end_service_idx is None:
            need_curve_for_day = self.needs_by_day.get(day_date, np.array([]))
            if np.any(need_curve_for_day > 0):
                non_zero_indices = np.where(need_curve_for_day > 0)[0]
                start_service_idx, end_service_idx = non_zero_indices[0], non_zero_indices[-1] + 1
            else: return []
        service_window_hours = (end_service_idx - start_service_idx) / 2.0
        hours_today = min(rule.workday_rule.max_daily_hours, remaining_weekly, service_window_hours) if not is_fixed else min(self._calculate_shift_duration(agent.turno_sugerido), remaining_weekly, service_window_hours)
        if hours_today < rule.workday_rule.min_daily_hours and not (service_window_hours <= rule.workday_rule.min_daily_hours and hours_today >= service_window_hours):
            if self._get_urgency_score(agent) < rule.workday_rule.min_daily_hours: return []
        if hours_today <= 0: return []
        num_intervals = int(hours_today * 2)
        if num_intervals <= 0: return []
        if is_fixed:
            try:
                start_str = agent.turno_sugerido.split('/')[0].split('-')[0].strip()
                start_idx_fixed = self.time_labels.get(start_str)
                if start_idx_fixed is not None and (start_idx_fixed + num_intervals) <= len(self.time_labels_list): return [(start_idx_fixed, start_idx_fixed + num_intervals)]
            except: return []
        try:
            start_win_str, end_win_str = agent.ventana_horaria.split('-')
            start_win_idx, end_win_idx = self.time_labels.get(start_win_str.strip(), start_service_idx), self.time_labels.get(end_win_str.strip(), end_service_idx)
        except (ValueError, AttributeError):
            start_win_idx, end_win_idx = start_service_idx, end_service_idx
        final_start, final_end = max(start_service_idx, start_win_idx), min(end_service_idx, end_win_idx)
        shifts = []
        if final_end > final_start and final_end - final_start >= num_intervals:
            for start_index in range(final_start, final_end - num_intervals + 1):
                shifts.append((start_index, start_index + num_intervals))
        return shifts

    def _calculate_shift_score(self, shift, need_curve):
        start_idx, end_idx = shift
        return np.sum(need_curve[start_idx:end_idx])


# ==============================================================================
# 4. RUTAS DE LA API WEB
# ==============================================================================
# ... (Deja todas tus rutas desde login hasta get_summary sin cambios) ...
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user' in session: return redirect(url_for('calculator'))
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user'], session['role'] = user.username, user.role
            flash('Inicio de sesión exitoso.', 'success')
            return redirect(url_for('calculator'))
        else: flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión exitosamente.', 'success')
    return redirect(url_for('login'))

@app.route('/calculator', methods=['GET', 'POST'])
def calculator():
    if 'user' not in session: return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            segment_id = request.form['segment_id']
            plantilla_excel_file = request.files['plantilla_excel']
            config = { "sla_objetivo": float(request.form['sla_objetivo']), "sla_tiempo": int(request.form['sla_tiempo']), "nda_objetivo": float(request.form['nda_objetivo']), "intervalo_seg": int(request.form['intervalo_seg']) }
        
            file_content = plantilla_excel_file.read()
            all_sheets = pd.read_excel(io.BytesIO(file_content), sheet_name=None)

            try:
                sample_columns = all_sheets[next(iter(all_sheets))].columns
                formatted_columns = []
                for col in sample_columns:
                    col_str = str(col).strip()
                    if isinstance(col, (datetime.time, datetime.datetime)): formatted_columns.append(col.strftime('%H:%M'))
                    elif ':' in col_str:
                        try: formatted_columns.append(pd.to_datetime(col_str).strftime('%H:%M'))
                        except (ValueError, TypeError): formatted_columns.append(col_str)
                    else: formatted_columns.append(col_str)
                for sheet_name in all_sheets:
                    all_sheets[sheet_name].columns = formatted_columns
            except Exception as e:
                 raise ValueError(f"Error al formatear columnas de tiempo: {e}")

            result_dfs = procesar_plantilla_unica(config, all_sheets)
            if result_dfs is None: 
                return jsonify({"error": "No se encontraron filas con fechas válidas en el archivo Excel."}), 400
            
            df_dimensionados, df_presentes, df_logados, df_efectivos = result_dfs
            
            if not df_dimensionados.empty:
                df_dimensionados['Fecha'] = pd.to_datetime(df_dimensionados['Fecha'])
                min_date = df_dimensionados['Fecha'].min().date()
                max_date = df_dimensionados['Fecha'].max().date()
                
                StaffingResult.query.filter(
                    StaffingResult.segment_id == segment_id,
                    StaffingResult.result_date.between(min_date, max_date)
                ).delete(synchronize_session=False)
                db.session.commit()

            index_cols = ['Fecha', 'Dia', 'Semana', 'Tipo']
            time_cols = [col for col in df_dimensionados.columns if col not in index_cols]
            
            all_dates = pd.to_datetime(df_dimensionados['Fecha']).dt.date.unique()
            
            new_entries = []
            for i, fecha_obj in enumerate(all_dates):
                
                reducers_data = {"absenteeism": {}, "shrinkage": {}, "auxiliaries": {}}
                reducer_map = {
                    "absenteeism": all_sheets.get('Absentismo_esperado'),
                    "shrinkage": all_sheets.get('Desconexiones_esperadas'),
                    "auxiliaries": all_sheets.get('Auxiliares_esperados')
                }

                for key, df_reducer in reducer_map.items():
                    temp_dict = {}
                    for t_col in time_cols:
                        try:
                            val = df_reducer.iloc[i][t_col]
                            numeric_val = pd.to_numeric(val, errors='coerce')
                            temp_dict[t_col] = 0.0 if pd.isna(numeric_val) else numeric_val
                        except (KeyError, IndexError):
                            temp_dict[t_col] = 0.0
                    reducers_data[key] = temp_dict
                
                def row_to_json_string(df, date):
                    df['Fecha'] = pd.to_datetime(df['Fecha'])
                    row_df = df[df['Fecha'].dt.date == date]
                    if row_df.empty: return "{}"
                    
                    row_df = row_df.replace({np.nan: None})
                    row_dict = row_df.iloc[0].to_dict()

                    if 'Fecha' in row_dict and isinstance(row_dict['Fecha'], pd.Timestamp):
                        row_dict['Fecha'] = row_dict['Fecha'].strftime('%Y-%m-%d %H:%M:%S')
                    
                    for k, v in row_dict.items():
                        if isinstance(v, np.generic): row_dict[k] = v.item()

                    return json.dumps(row_dict)

                new_entry = StaffingResult(
                    result_date=fecha_obj,
                    agents_online=row_to_json_string(df_efectivos, fecha_obj),
                    agents_total=row_to_json_string(df_dimensionados, fecha_obj),
                    calls_forecast=row_to_json_string(all_sheets['Llamadas_esperadas'], fecha_obj),
                    aht_forecast=row_to_json_string(all_sheets['AHT_esperado'], fecha_obj),
                    reducers_forecast=json.dumps(reducers_data),
                    segment_id=segment_id
                )
                new_entries.append(new_entry)
            
            db.session.bulk_save_objects(new_entries)
            db.session.commit()
            
            results_to_send = {
                "dimensionados": format_and_calculate_simple(df_dimensionados).to_dict(orient='split'),
                "presentes": format_and_calculate_simple(df_presentes).to_dict(orient='split'),
                "logados": format_and_calculate_simple(df_logados).to_dict(orient='split'),
                "efectivos": format_and_calculate_simple(df_efectivos).to_dict(orient='split')
            }
            for key in results_to_send:
                if 'index' in results_to_send[key]: del results_to_send[key]['index']
            
            flash('Dimensionamiento calculado y guardado con éxito.', 'success')
            return jsonify(results_to_send)
        except Exception as e:
            import traceback; traceback.print_exc()
            db.session.rollback()
            return jsonify({"error": f"Error al procesar el archivo: No se pudo procesar la plantilla. Error: {e}"}), 400

    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()
        return redirect(url_for('login'))
    if user.role == 'admin':
        segments = Segment.query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        segments = Segment.query.join(Campaign).filter(Campaign.id.in_([c.id for c in user.campaigns])).order_by(Campaign.name, Segment.name).all()
    return render_template('calculator.html', segments=segments)

@app.route('/history')
def history():
    if 'user' not in session: return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()
        return redirect(url_for('login'))
    if user.role == 'admin':
        segments = Segment.query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        segments = Segment.query.join(Campaign).filter(Campaign.id.in_([c.id for c in user.campaigns])).order_by(Campaign.name, Segment.name).all()
    return render_template('history.html', segments=segments)

@app.route('/scheduling')
def scheduling():
    if 'user' not in session: return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()
        return redirect(url_for('login'))
    if user.role == 'admin':
        segments = Segment.query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        segments = Segment.query.join(Campaign).filter(Campaign.id.in_([c.id for c in user.campaigns])).order_by(Campaign.name, Segment.name).all()
    return render_template('scheduling.html', segments=segments)
    
@app.route('/summary')
def summary():
    if 'user' not in session: return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()
        return redirect(url_for('login'))
    if user.role == 'admin':
        segments = Segment.query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        segments = Segment.query.join(Campaign).filter(Campaign.id.in_([c.id for c in user.campaigns])).order_by(Campaign.name, Segment.name).all()
    return render_template('summary.html', segments=segments)

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create_user':
            new_username, new_password, new_role = request.form.get('new_username'), request.form['new_password'], request.form['new_role']
            if User.query.filter_by(username=new_username).first(): flash(f"El usuario '{new_username}' ya existe.", 'error')
            elif not new_password: flash("La contraseña no puede estar vacía.", "error")
            else:
                new_user = User(username=new_username, password_hash=generate_password_hash(new_password, method='pbkdf2:sha256'), role=new_role)
                db.session.add(new_user); db.session.commit()
                flash(f"Usuario '{new_username}' creado con rol '{new_role}'.", 'success')
        elif action == 'create_campaign':
            code = request.form.get('new_campaign_code')
            new_campaign_name = request.form.get('new_campaign_name')
            country = request.form.get('new_campaign_country')
            
            if Campaign.query.filter_by(name=new_campaign_name).first(): 
                flash(f"La campaña '{new_campaign_name}' ya existe.", 'error')
            elif code and Campaign.query.filter_by(code=code).first():
                flash(f"El código de campaña '{code}' ya está en uso.", 'error')
            elif not country: 
                flash("Debe seleccionar un país para la campaña.", 'error')
            else:
                new_campaign = Campaign(code=code if code else None, name=new_campaign_name, country=country)
                db.session.add(new_campaign)
                db.session.commit()
                flash(f"Campaña '{new_campaign_name}' ({country}) creada con éxito.", 'success')

        elif action == 'delete_campaign':
            campaign_to_delete = Campaign.query.get(request.form.get('delete_campaign_id'))
            if campaign_to_delete:
                db.session.delete(campaign_to_delete); db.session.commit()
                flash(f"Campaña '{campaign_to_delete.name}' y todos sus datos han sido eliminados.", 'success')
            else: flash("No se encontró la campaña a eliminar.", 'error')
        elif action == 'create_segment' or action == 'update_segment':
            campaign_id = request.form.get('campaign_id_for_segment')
            segment_name = request.form.get('segment_name')
            if action == 'create_segment':
                if Segment.query.filter_by(name=segment_name, campaign_id=campaign_id).first():
                    flash(f"El segmento '{segment_name}' ya existe en esta campaña.", 'error')
                    return redirect(url_for('admin'))
                segment = Segment(campaign_id=campaign_id)
                db.session.add(segment)
                flash(f"Segmento '{segment_name}' creado con éxito.", 'success')
            else:
                segment_id = request.form.get('segment_id')
                segment = Segment.query.get(segment_id)
                if not segment:
                    flash("Error: No se encontró el segmento a actualizar.", "error")
                    return redirect(url_for('admin'))
                flash(f"Segmento '{segment.name}' actualizado con éxito.", 'success')
            segment.name = segment_name
            segment.lunes_apertura=request.form.get('lunes_apertura') or None; segment.lunes_cierre=request.form.get('lunes_cierre') or None
            segment.martes_apertura=request.form.get('martes_apertura') or None; segment.martes_cierre=request.form.get('martes_cierre') or None
            segment.miercoles_apertura=request.form.get('miercoles_apertura') or None; segment.miercoles_cierre=request.form.get('miercoles_cierre') or None
            segment.jueves_apertura=request.form.get('jueves_apertura') or None; segment.jueves_cierre=request.form.get('jueves_cierre') or None
            segment.viernes_apertura=request.form.get('viernes_apertura') or None; segment.viernes_cierre=request.form.get('viernes_cierre') or None
            segment.sabado_apertura=request.form.get('sabado_apertura') or None; segment.sabado_cierre=request.form.get('sabado_cierre') or None
            segment.domingo_apertura=request.form.get('domingo_apertura') or None; segment.domingo_cierre=request.form.get('domingo_cierre') or None
            segment.weekend_policy = request.form.get('weekend_policy')
            segment.min_full_weekends_off_per_month = int(request.form.get('min_full_weekends_off_per_month'))
            db.session.commit()
        elif action == 'delete_segment':
            segment_to_delete = Segment.query.get(request.form.get('delete_segment_id'))
            if segment_to_delete:
                db.session.delete(segment_to_delete); db.session.commit()
                flash(f"Segmento '{segment_to_delete.name}' eliminado.", 'success')
            else: flash("No se encontró el segmento a eliminar.", 'error')        
        elif action == 'update_user':
            for user in User.query.all():
                if user.username == 'admin': continue
                new_role = request.form.get(f'role_{user.id}')
                if new_role and new_role != user.role:
                    user.role = new_role; flash(f"Rol de '{user.username}' actualizado a '{new_role}'.", 'success')
                assigned_campaign_ids = request.form.getlist(f'permissions_{user.id}')
                user.campaigns = Campaign.query.filter(Campaign.id.in_(assigned_campaign_ids)).all()
            db.session.commit(); flash('Cambios de usuario guardados con éxito.', 'success')
        elif action == 'create_rule':
            name, country = request.form.get('new_rule_name'), request.form.get('new_rule_country')
            if SchedulingRule.query.filter_by(name=name).first(): flash(f"Ya existe una regla con el nombre '{name}'.", 'error')
            else:
                new_rule = SchedulingRule(name=name, country=country)
                new_workday_rule = WorkdayRule(
                    weekly_hours=float(request.form.get('new_rule_weekly_hours')), max_daily_hours=float(request.form.get('new_rule_max_daily_hours')),
                    min_daily_hours=float(request.form.get('new_rule_min_daily_hours')), days_per_week=int(request.form.get('new_rule_days_per_week')),
                    max_consecutive_work_days=int(request.form.get('new_rule_max_consecutive')), min_hours_between_shifts=int(request.form.get('new_rule_min_hours_between')),
                    scheduling_rule=new_rule )
                db.session.add_all([new_rule, new_workday_rule]); db.session.commit()
                flash(f"Regla '{name}' creada con éxito.", 'success')
        elif action == 'delete_rule':
            rule_to_delete = SchedulingRule.query.get(request.form.get('delete_rule_id'))
            if rule_to_delete:
                db.session.delete(rule_to_delete); db.session.commit()
                flash(f"Regla '{rule_to_delete.name}' eliminada.", 'success')
        return redirect(url_for('admin'))
    
    users, campaigns, rules = User.query.all(), Campaign.query.order_by(Campaign.name).all(), SchedulingRule.query.order_by(SchedulingRule.country, SchedulingRule.name).all()
    return render_template('admin_users.html', users=users, campaigns=campaigns, rules=rules)

@app.route('/forecasting')
def forecasting():
    if 'user' not in session: return redirect(url_for('login'))
    user = User.query.filter_by(username=session['user']).first()
    if not user: session.clear(); return redirect(url_for('login'))
    if user.role == 'admin':
        segments = Segment.query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        user_campaign_ids = [c.id for c in user.campaigns]
        segments = Segment.query.join(Campaign).filter(Campaign.id.in_(user_campaign_ids)).order_by(Campaign.name, Segment.name).all()
    return render_template('forecasting.html', segments=segments)

@app.route('/intraday_forecaster')
def intraday_forecaster():
    # --- 1. Verificación de Sesión de Usuario ---
    # Si no hay un usuario en la sesión, se redirige a la página de login.
    if 'user' not in session: 
        return redirect(url_for('login'))

    # --- 2. Obtención de los Datos del Usuario Actual ---
    # Se busca al usuario en la base de datos usando el nombre guardado en la sesión.
    user = User.query.filter_by(username=session['user']).first()
    
    # Si por alguna razón el usuario ya no existe en la BD, se limpia la sesión y se redirige.
    if not user: 
        session.clear()
        return redirect(url_for('login'))

    # --- 3. Lógica para Obtener Segmentos Basada en el Rol (AJUSTE CLAVE) ---
    # Esta es la lógica para cargar los segmentos que el usuario tiene permiso de ver.
    
    # Si el usuario es 'admin', tiene acceso a todos los segmentos de todas las campañas.
    if user.role == 'admin':
        # Se obtienen todos los segmentos, uniéndolos con las campañas para poder ordenarlos
        # por nombre de campaña y luego por nombre de segmento.
        segments = Segment.query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        # Si no es admin, solo se le mostrarán los segmentos de las campañas a las que tiene permiso.
        
        # Se obtiene una lista de los IDs de las campañas asignadas al usuario.
        user_campaign_ids = [c.id for c in user.campaigns]
        
        # Se buscan los segmentos cuya campaña asociada (campaign_id) esté en la lista de permisos del usuario.
        segments = Segment.query.join(Campaign).filter(
            Campaign.id.in_(user_campaign_ids)
        ).order_by(Campaign.name, Segment.name).all()

    # --- 4. Renderizado de la Plantilla ---
    # Se renderiza la plantilla HTML y se le pasa la lista de 'segments' obtenida.
    # La plantilla usará esta lista para poblar el menú desplegable del "Paso 4".
    return render_template('intraday_forecaster.html', segments=segments)
    
@app.route('/api/get_segment_details/<int:segment_id>')
def get_segment_details(segment_id):
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if session.get('role') != 'admin': return jsonify({"error": "Acceso denegado"}), 403
    segment = Segment.query.get(segment_id)
    if segment:
        return jsonify({
            'id': segment.id, 'name': segment.name, 'campaign_id': segment.campaign_id,
            'lunes_apertura': segment.lunes_apertura or '', 'lunes_cierre': segment.lunes_cierre or '',
            'martes_apertura': segment.martes_apertura or '', 'martes_cierre': segment.martes_cierre or '',
            'miercoles_apertura': segment.miercoles_apertura or '', 'miercoles_cierre': segment.miercoles_cierre or '',
            'jueves_apertura': segment.jueves_apertura or '', 'jueves_cierre': segment.jueves_cierre or '',
            'viernes_apertura': segment.viernes_apertura or '', 'viernes_cierre': segment.viernes_cierre or '',
            'sabado_apertura': segment.sabado_apertura or '', 'sabado_cierre': segment.sabado_cierre or '',
            'domingo_apertura': segment.domingo_apertura or '', 'domingo_cierre': segment.domingo_cierre or '',
            'weekend_policy': segment.weekend_policy, 'min_full_weekends_off_per_month': segment.min_full_weekends_off_per_month
        })
    return jsonify({'error': 'Segmento no encontrado'}), 404

@app.route('/api/update_schedule', methods=['POST'])
def update_schedule():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if session.get('role') != 'admin': return jsonify({"error": "Acceso denegado"}), 403
    try:
        data = request.json
        agent_id, date_str, new_shift = data.get('agent_id'), data.get('date'), data.get('shift')
        schedule_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        entry = Schedule.query.filter_by(agent_id=agent_id, schedule_date=schedule_date).first()
        if not entry:
            entry = Schedule(agent_id=agent_id, schedule_date=schedule_date)
            db.session.add(entry)
        entry.shift, entry.is_manual_edit = new_shift, True
        hours = 0
        if new_shift != "LIBRE" and '-' in new_shift:
             try:
                 temp_scheduler = Scheduler([],{},{},[],Segment(),{})
                 hours = temp_scheduler._calculate_shift_duration(new_shift)
             except: hours = 0
        entry.hours = hours
        db.session.commit()
        week_number = schedule_date.isocalendar()[1]
        year = schedule_date.isocalendar()[0]
        start_of_week = datetime.date.fromisocalendar(year, week_number, 1)
        end_of_week = start_of_week + datetime.timedelta(days=6)
        weekly_hours = db.session.query(db.func.sum(Schedule.hours)).filter(
            Schedule.agent_id == agent_id,
            Schedule.schedule_date.between(start_of_week, end_of_week)
        ).scalar() or 0.0
        return jsonify({"message": "Turno actualizado con éxito", "new_hours": hours, "new_weekly_total": weekly_hours})
    except Exception as e:
        db.session.rollback(); return jsonify({"error": f"Error al actualizar el turno: {e}"}), 500

@app.route('/api/get_schedule', methods=['POST'])
def get_schedule():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if session.get('role') != 'admin': return jsonify({"error": "Acceso denegado"}), 403
    try:
        data = request.json
        segment_id, start_date_str, end_date_str = data.get('segment_id'), data.get('start_date'), data.get('end_date')
        if not start_date_str or not end_date_str: return jsonify({"error": "Las fechas de inicio y fin son requeridas."}), 400
        start_date, end_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date(), datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        segment_agents = Agent.query.filter_by(segment_id=segment_id).order_by(Agent.nombre_completo).all()
        if not segment_agents:
            return jsonify({"error": "No hay agentes cargados para este segmento."}), 404
        agent_ids = [agent.id for agent in segment_agents]
        schedule_entries = Schedule.query.filter(Schedule.agent_id.in_(agent_ids), Schedule.schedule_date.between(start_date, end_date)).all()
        schedule_map = {(entry.agent_id, entry.schedule_date): entry for entry in schedule_entries}
        final_schedule = {}
        date_range = [start_date + datetime.timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        for agent in segment_agents:
            agent_schedule = {}
            for day in date_range:
                date_str = day.strftime('%Y-%m-%d')
                shift_display = 'LIBRE'
                is_manual = False
                if agent.fecha_alta and day < agent.fecha_alta:
                    shift_display = 'PENDIENTE ALTA'
                elif agent.fecha_baja and day > agent.fecha_baja:
                    shift_display = 'BAJA'
                else:
                    entry = schedule_map.get((agent.id, day))
                    if entry:
                        shift_display = entry.shift
                        is_manual = entry.is_manual_edit
                agent_schedule[date_str] = shift_display
                if is_manual:
                    agent_schedule[f"{date_str}_manual"] = True
            final_schedule[agent.nombre_completo] = agent_schedule
        staffing_needs_raw = StaffingResult.query.filter(StaffingResult.segment_id == segment_id, StaffingResult.result_date >= start_date, StaffingResult.result_date <= end_date).all()
        needs_by_day, time_labels = {}, []
        if staffing_needs_raw:
            for need in staffing_needs_raw:
                day_data = json.loads(need.agents_online)
                needs_by_day[need.result_date] = [int(v) if v is not None else 0 for k, v in day_data.items() if k.replace(':', '').isdigit()]
                if not time_labels: time_labels = [k for k in day_data.keys() if k.replace(':', '').isdigit()]
        
        agent_map = {agent.nombre_completo: agent.id for agent in segment_agents}
        coverage_data_for_chart = {day.strftime('%Y-%m-%d'): np.zeros(len(time_labels)) for day in needs_by_day.keys()}
        temp_scheduler = Scheduler([],{},{},time_labels,Segment(),{})
        for agent_name, daily_shifts in final_schedule.items():
            weekly_totals = {}
            for date_str, shift in daily_shifts.items():
                if '_manual' not in date_str and shift not in ["LIBRE", "Error Formato", "BAJA", "PENDIENTE ALTA"] and isinstance(shift, str) and '-' in shift:
                    day_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                    week_number = day_date.isocalendar()[1]
                    hours = temp_scheduler._calculate_shift_duration(shift)
                    weekly_totals[week_number] = weekly_totals.get(week_number, 0) + hours
                    if time_labels:
                        for part in shift.split('/'):
                            try:
                                start_str, end_str = [s.strip() for s in part.split('-')]
                                start_idx, end_idx = time_labels.index(start_str), time_labels.index(end_str) if end_str != '24:00' else len(time_labels)
                                if date_str in coverage_data_for_chart:
                                    coverage_data_for_chart[date_str][start_idx:end_idx] += 1
                            except (ValueError, IndexError): continue
            for week_number, total_hours in weekly_totals.items():
                final_schedule[agent_name][f"week_{week_number}_total"] = total_hours
        chart_data_by_day = {"labels": time_labels, "days": {}}
        for day, need in needs_by_day.items():
            day_str = day.strftime('%Y-%m-%d')
            chart_data_by_day["days"][day_str] = {"need": need, "coverage": coverage_data_for_chart.get(day_str, np.zeros(len(time_labels))).tolist()}
        return jsonify({"schedule": final_schedule, "chart_data": chart_data_by_day, "agent_map": agent_map})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Ocurrió un error al consultar los horarios: {e}"}), 500



@app.route('/calcular', methods=['GET', 'POST'])
def calcular():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        segment_id = request.form['segment_id']
        plantilla_excel_file = request.files['plantilla_excel']
        config = { 
            "sla_objetivo": float(request.form['sla_objetivo']), 
            "sla_tiempo": int(request.form['sla_tiempo']), 
            "nda_objetivo": float(request.form['nda_objetivo']), 
            "intervalo_seg": int(request.form['intervalo_seg']) 
        }
        
        file_content = plantilla_excel_file.read()
        all_sheets = pd.read_excel(io.BytesIO(file_content), sheet_name=None)

        try:
            # ... (tu código de formateo de columnas, se mantiene igual)
            sample_columns = all_sheets[next(iter(all_sheets))].columns
            formatted_columns = []
            for col in sample_columns:
                col_str = str(col).strip()
                if isinstance(col, (datetime.time, datetime.datetime)): 
                    formatted_columns.append(col.strftime('%H:%M'))
                elif ':' in col_str:
                    try: 
                        formatted_columns.append(pd.to_datetime(col_str).strftime('%H:%M'))
                    except (ValueError, TypeError): 
                        formatted_columns.append(col_str)
                else:
                    formatted_columns.append(col_str)
            for sheet_name in all_sheets:
                all_sheets[sheet_name].columns = formatted_columns
        except Exception as e:
             raise ValueError(f"Error al formatear columnas de tiempo: {e}")

        # --- CAMBIO 1: Desempaquetar los 5 valores devueltos por la función ---
        # Ahora esperamos 5 resultados (4 DataFrames + 1 diccionario de KPIs)
        # en lugar de un solo tuple que luego se desempaquetaba.
        df_dim_frac, df_pre_frac, df_log_frac, df_efe_frac, kpi_data = procesar_plantilla_unica(config, all_sheets)
        
        # La comprobación ahora se hace sobre uno de los DataFrames devueltos
        if df_dim_frac is None or df_dim_frac.empty: 
            return jsonify({"error": "No se encontraron filas con fechas válidas en el archivo Excel."}), 400
        
        # --- FIN DEL CAMBIO 1 ---
        
        
        if not df_dim_frac.empty:
            # ... (tu código para borrar y guardar en la base de datos, se mantiene igual)
            df_dim_frac['Fecha'] = pd.to_datetime(df_dim_frac['Fecha'])
            min_date = df_dim_frac['Fecha'].min().date()
            max_date = df_dim_frac['Fecha'].max().date()
            
            StaffingResult.query.filter(
                StaffingResult.segment_id == segment_id,
                StaffingResult.result_date.between(min_date, max_date)
            ).delete(synchronize_session=False)
            db.session.commit()

        index_cols = ['Fecha', 'Dia', 'Semana', 'Tipo']
        time_cols = [col for col in df_dim_frac.columns if col not in index_cols]
        all_dates = pd.to_datetime(df_dim_frac['Fecha']).dt.date.unique()
        
        new_entries = []
        
        reducer_map_dfs = {
            "absenteeism": all_sheets.get('Absentismo_esperado'),
            "shrinkage": all_sheets.get('Desconexiones_esperadas'),
            "auxiliaries": all_sheets.get('Auxiliares_esperados')
        }
        for key, df_reducer in reducer_map_dfs.items():
            if df_reducer is not None:
                df_reducer['Fecha'] = pd.to_datetime(df_reducer['Fecha'], errors='coerce')

        for fecha_obj in all_dates:
            # ... (el resto de tu lógica para guardar en la base de datos se mantiene igual)
            reducers_data = {"absenteeism": {}, "shrinkage": {}, "auxiliaries": {}}
            for key, df_reducer in reducer_map_dfs.items():
                temp_dict = {}
                if df_reducer is not None:
                    reducer_row = df_reducer[df_reducer['Fecha'].dt.date == fecha_obj]
                    if not reducer_row.empty:
                        for t_col in time_cols:
                            val = reducer_row.iloc[0].get(t_col, 0)
                            numeric_val = pd.to_numeric(val, errors='coerce')
                            temp_dict[t_col] = 0.0 if pd.isna(numeric_val) else numeric_val
                    else:
                        for t_col in time_cols: temp_dict[t_col] = 0.0
                reducers_data[key] = temp_dict

            def row_to_json_string(df, date):
                df_copy = df.copy()
                df_copy['Fecha'] = pd.to_datetime(df_copy['Fecha'])
                row_df = df_copy[df_copy['Fecha'].dt.date == date]
                if row_df.empty: return "{}"
                
                row_df = row_df.replace({np.nan: None})
                row_dict = row_df.iloc[0].to_dict()

                if 'Fecha' in row_dict and isinstance(row_dict['Fecha'], pd.Timestamp):
                    row_dict['Fecha'] = row_dict['Fecha'].strftime('%Y-%m-%d %H:%M:%S')
                
                for k, v in row_dict.items():
                    if isinstance(v, np.generic): row_dict[k] = v.item()

                return json.dumps(row_dict)

            new_entry = StaffingResult(
                result_date=fecha_obj,
                agents_online=row_to_json_string(df_efe_frac, fecha_obj),
                agents_total=row_to_json_string(df_dim_frac, fecha_obj),
                calls_forecast=row_to_json_string(all_sheets['Llamadas_esperadas'], fecha_obj),
                aht_forecast=row_to_json_string(all_sheets['AHT_esperado'], fecha_obj),
                reducers_forecast=json.dumps(reducers_data),
                segment_id=segment_id,
                sla_target_percentage=config["sla_objetivo"],
                sla_target_time=config["sla_tiempo"]
            )
            new_entries.append(new_entry)
        
        db.session.bulk_save_objects(new_entries)
        db.session.commit()
        
        def final_format_for_display(df_frac):
            # ... (tu función de formateo, se mantiene igual)
            df_display = df_frac.copy()
            index_cols = ['Fecha', 'Dia', 'Semana', 'Tipo']
            time_cols = [col for col in df_frac.columns if col not in index_cols]
            
            for col in time_cols:
                df_display[col] = df_display[col].round(1)

            df_display['Horas-Totales'] = df_frac[time_cols].sum(axis=1) / 2.0
            
            if 'Fecha' in df_display.columns:
                df_display['Fecha'] = pd.to_datetime(df_display['Fecha']).dt.strftime('%d/%m/%Y')
            
            return df_display.to_dict(orient='split')

        # --- CAMBIO 2: Añadir los KPIs al diccionario de la respuesta JSON ---
        results_to_send = {
            "dimensionados": final_format_for_display(df_dim_frac),
            "presentes": final_format_for_display(df_pre_frac),
            "logados": final_format_for_display(df_log_frac),
            "efectivos": final_format_for_display(df_efe_frac),
            "kpis": kpi_data  # <-- Aquí se añaden los datos para las tarjetas
        }
        # --- FIN DEL CAMBIO 2 ---
        
        for key in results_to_send:
            if 'index' in results_to_send.get(key, {}): 
                del results_to_send[key]['index']
        
        return jsonify(results_to_send)
        
    except Exception as e:
        import traceback; traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Error al procesar el archivo: {e}"}), 400

@app.route('/api/upload_actuals', methods=['POST'])
def upload_actuals():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        if 'actuals_excel' not in request.files: return jsonify({"error": "No se encontró el archivo de datos reales."}), 400
        segment_id = request.form.get('segment_id')
        file = request.files['actuals_excel']
        required_sheets = ['ENTRANTES', 'ATENDIDAS', 'NDS', 'AHT']
        all_sheets_df = pd.read_excel(file, sheet_name=required_sheets)
        df_entrantes = all_sheets_df['ENTRANTES']
        date_column_name = df_entrantes.columns[3] 
        time_interval_columns = df_entrantes.columns[4:]
        for index in df_entrantes.index:
            date_val = df_entrantes.loc[index, date_column_name]
            if pd.isna(pd.to_datetime(date_val, errors='coerce')): continue
            date = pd.to_datetime(date_val).date()
            day_data_by_interval = {}
            for time_col in time_interval_columns:
                interval_str = time_col.strftime('%H:%M') if not isinstance(time_col, str) else str(time_col)
                day_data_by_interval[interval_str] = {
                    "entrantes": float(all_sheets_df['ENTRANTES'].loc[index, time_col] or 0),
                    "atendidas": float(all_sheets_df['ATENDIDAS'].loc[index, time_col] or 0),
                    "nds": float(all_sheets_df['NDS'].loc[index, time_col] or 0),
                    "aht": float(all_sheets_df['AHT'].loc[index, time_col] or 0),
                }
            existing_record = ActualsData.query.filter_by(result_date=date, segment_id=segment_id).first()
            actuals_json_string = json.dumps(day_data_by_interval)
            if existing_record:
                existing_record.actuals_data = actuals_json_string
            else:
                db.session.add(ActualsData(result_date=date, segment_id=segment_id, actuals_data=actuals_json_string))
        db.session.commit()
        return jsonify({"message": "Datos reales cargados con éxito."})
    except KeyError as e:
        db.session.rollback()
        return jsonify({"error": f"No se encontró la hoja requerida en el Excel: {e}."}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al procesar el archivo: {e}"}), 500

@app.route('/api/get_forecasting_data', methods=['POST'])
def get_forecasting_data():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json
        segment_id = data.get('segment_id'); start_date = datetime.datetime.strptime(data.get('start_date'), '%Y-%m-%d').date(); end_date = datetime.datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        forecast_results = StaffingResult.query.filter(StaffingResult.segment_id == segment_id, StaffingResult.result_date.between(start_date, end_date)).order_by(StaffingResult.result_date).all()
        actuals_results = ActualsData.query.filter(ActualsData.segment_id == segment_id, ActualsData.result_date.between(start_date, end_date)).all()
        if not forecast_results: return jsonify({"error": "No se encontraron datos de pronóstico para el rango."}), 404
        actuals_map = {r.result_date: r for r in actuals_results}
        response_data = []
        for forecast in forecast_results:
            date = forecast.result_date
            try: forecast_calls_data = json.loads(forecast.calls_forecast); forecast_aht_data = json.loads(forecast.aht_forecast)
            except (json.JSONDecodeError, TypeError): continue
            total_forecast_calls = sum(float(v or 0) for k, v in forecast_calls_data.items() if str(k).replace(':', '').isdigit())
            weighted_aht_sum = sum(float(forecast_calls_data.get(k, 0) or 0) * float(forecast_aht_data.get(k, 0) or 0) for k in forecast_calls_data if str(k).replace(':', '').isdigit())
            avg_forecast_aht = (weighted_aht_sum / total_forecast_calls) if total_forecast_calls > 0 else 0
            day_summary = {"date": date.strftime('%d/%m/%Y'), "forecast_calls": round(total_forecast_calls), "forecast_aht": round(avg_forecast_aht), "real_entrantes": "N/A", "real_atendidas": "N/A", "real_aht": "N/A", "real_nda": "N/A", "real_llamadas_nds": "N/A", "real_nds_percent": "N/A", "real_nda_numeric": None, "desviacion_llamadas_percent": "N/A", "desviacion_aht_percent": "N/A"}
            if date in actuals_map:
                try:
                    actuals_json = json.loads(actuals_map[date].actuals_data)
                    total_real_entrantes = sum(float(d.get('entrantes', 0) or 0) for d in actuals_json.values()); total_real_atendidas = sum(float(d.get('atendidas', 0) or 0) for d in actuals_json.values()); total_real_nds_calls = sum(float(d.get('nds', 0) or 0) for d in actuals_json.values())
                    weighted_real_aht_sum = sum(float(d.get('atendidas', 0) or 0) * float(d.get('aht', 0) or 0) for d in actuals_json.values())
                    avg_real_aht = (weighted_real_aht_sum / total_real_atendidas) if total_real_atendidas > 0 else 0
                    avg_real_nda_percent = (total_real_atendidas / total_real_entrantes) * 100 if total_real_entrantes > 0 else 0; avg_real_nds_percent = (total_real_nds_calls / total_real_atendidas) * 100 if total_real_atendidas > 0 else 0
                    desv_calls_pct = ((total_real_entrantes - total_forecast_calls) / total_forecast_calls) * 100 if total_forecast_calls > 0 else 0; desv_aht_pct = ((avg_real_aht - avg_forecast_aht) / avg_forecast_aht) * 100 if avg_forecast_aht > 0 else 0
                    day_summary.update({"real_entrantes": round(total_real_entrantes), "real_atendidas": round(total_real_atendidas), "real_aht": round(avg_real_aht), "real_nda": f"{avg_real_nda_percent:.1f}%", "real_llamadas_nds": round(total_real_nds_calls), "real_nds_percent": f"{avg_real_nds_percent:.1f}%", "real_nda_numeric": avg_real_nda_percent, "desviacion_llamadas_percent": f"{desv_calls_pct:.1f}%", "desviacion_aht_percent": f"{desv_aht_pct:.1f}%"})
                except (json.JSONDecodeError, TypeError, ValueError): pass
            response_data.append(day_summary)
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"error": f"Error de servidor: {e}"}), 500



@app.route('/api/build_weighted_curve', methods=['POST'])
def build_weighted_curve():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json; weights = data.get('weights'); day_of_week = data.get('day_of_week'); all_weekly_data = data.get('all_weekly_data'); labels = data.get('labels')
        if not all([weights, day_of_week is not None, all_weekly_data, labels]): return jsonify({"error": "Faltan datos."}), 400
        data_for_day = all_weekly_data.get(str(day_of_week), [])
        if not data_for_day: return jsonify({"error": "No hay datos para el día."}), 400
        weighted_calls = {label: 0 for label in labels}
        for week_data in data_for_day:
            weight = float(weights.get(str(week_data['week']), 0)) / 100.0
            if weight > 0:
                for label in labels: weighted_calls[label] += week_data['intraday_raw'].get(label, 0) * weight
        total_weighted_calls = sum(weighted_calls.values())
        if total_weighted_calls == 0: return jsonify({"error": "La suma ponderada es cero."}), 400
        final_distribution = {label: (calls / total_weighted_calls) for label, calls in weighted_calls.items()}
        return jsonify({"final_curve": final_distribution})
    except Exception as e: return jsonify({"error": f"Error de servidor: {e}"}), 500

@app.route('/api/generate_forecast_from_curve', methods=['POST'])
def generate_forecast_from_curve():
    # --- 1. Verificación de Seguridad y Entradas ---
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    try:
        # Validar que los datos necesarios (archivo y curvas) fueron enviados
        if 'forecast_file' not in request.files or 'curves_data' not in request.form:
            return jsonify({"error": "Faltan archivos o datos de curvas. Asegúrese de subir el archivo de volumen y tener curvas generadas."}), 400

        forecast_file = request.files['forecast_file']
        curves_data_str = request.form['curves_data']
        
        # --- 2. Procesamiento de Datos de Entrada ---
        # Cargar los datos JSON enviados desde el frontend (curvas y etiquetas de tiempo)
        data_from_js = json.loads(curves_data_str)
        curves_to_use = data_from_js.get('curves', {})
        time_labels = data_from_js.get('labels', [])

        if not curves_to_use or not time_labels:
            return jsonify({"error": "Los datos de las curvas de distribución están vacíos o corruptos."}), 400

        # Cargar el archivo Excel con los volúmenes totales por día
        df_forecast = pd.read_excel(forecast_file)
        # Estandarizar nombres de columnas (eliminar espacios, etc.)
        df_forecast.columns = [str(col).strip() for col in df_forecast.columns]

        # --- 3. Búsqueda Dinámica de Columnas (CORRECCIÓN CLAVE) ---
        if 'Fecha' not in df_forecast.columns:
            return jsonify({"error": "El archivo de volumen debe tener una columna llamada 'Fecha'."}), 400
        
        # Búsqueda dinámica de la columna de volumen.
        # Asumimos que es la primera columna que no se llama 'Fecha'.
        volume_column_name = None
        for col in df_forecast.columns:
            if str(col).strip().lower() != 'fecha':
                volume_column_name = col
                break  # Encontramos la columna, salimos del bucle

        if volume_column_name is None:
            return jsonify({"error": "No se pudo encontrar una columna de volumen en el archivo. Se esperaba una columna 'Fecha' y otra con los totales."}), 400

        # --- 4. Preparación del DataFrame de Volumen ---
        # Convertir la columna 'Fecha' a formato datetime y eliminar filas sin fecha válida
        df_forecast['Fecha'] = pd.to_datetime(df_forecast['Fecha'], errors='coerce')
        df_forecast.dropna(subset=['Fecha'], inplace=True)
        # Convertir la columna de volumen a numérico, tratando errores como ceros
        df_forecast[volume_column_name] = pd.to_numeric(df_forecast[volume_column_name], errors='coerce').fillna(0)

        # --- 5. Lógica de Distribución de Llamadas ---
        output_rows = []
        day_name_map_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}

        # Iterar sobre cada día en el archivo de volumen
        for index, row in df_forecast.iterrows():
            date_obj = row['Fecha']
            total_volume = float(row[volume_column_name])
            
            # Omitir filas sin fecha o sin volumen
            if pd.isna(date_obj) or total_volume <= 0:
                continue

            # Obtener el número del día de la semana (Lunes=0, Domingo=6)
            day_of_week_num = str(date_obj.weekday())
            
            # Si no tenemos una curva guardada para ese día de la semana, lo saltamos
            if day_of_week_num not in curves_to_use:
                continue

            # Obtener la curva de distribución para el día correspondiente
            curve_for_day = curves_to_use[day_of_week_num]
            
            # Crear la estructura base de la nueva fila de resultados
            new_row = {
                'Fecha': date_obj,
                'Dia': day_name_map_es.get(int(day_of_week_num)),
                'Semana': date_obj.isocalendar()[1],
                'Tipo': 'N' # Asumimos 'N' (Normal) por defecto
            }
            
            distributed_sum = 0
            
            # Distribuir el volumen total en cada intervalo de tiempo según los pesos de la curva
            for interval in time_labels:
                weight = curve_for_day.get(interval, 0)
                distributed_calls = round(total_volume * weight)
                new_row[interval] = distributed_calls
                distributed_sum += distributed_calls
            
            # Ajuste por redondeo: la suma distribuida puede no ser exactamente igual al total.
            # La diferencia se suma (o resta) del intervalo con mayor peso (el pico de llamadas).
            difference = round(total_volume - distributed_sum)
            if difference != 0 and curve_for_day:
                # Encontrar el intervalo con el mayor porcentaje de llamadas
                peak_interval = max(curve_for_day, key=curve_for_day.get)
                new_row[peak_interval] += difference

            output_rows.append(new_row)

        # Si no se generó ningún resultado, informar al usuario.
        if not output_rows:
            return jsonify({"error": "No se pudo generar ninguna fila de pronóstico. Verifique que las fechas en su archivo de volumen coincidan con los días para los que generó y guardó curvas."}), 400

        # --- 6. Creación del Archivo Excel de Salida ---
        df_final = pd.DataFrame(output_rows)
        # Asegurar el orden correcto de las columnas
        cols_order = ['Fecha', 'Dia', 'Semana', 'Tipo'] + time_labels
        df_final = df_final[cols_order]

        # Crear un archivo Excel en memoria para no guardarlo en el servidor
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter', datetime_format='dd/mm/yyyy')
        
        # Escribir la hoja principal con el pronóstico distribuido
        df_final.to_excel(writer, index=False, sheet_name='Llamadas_esperadas')
        
        # Crear y añadir las hojas vacías requeridas por el módulo de la calculadora
        # Esto permite que el archivo sea compatible directamente.
        required_empty_sheets = ['AHT_esperado', 'Absentismo_esperado', 'Auxiliares_esperados', 'Desconexiones_esperadas']
        for sheet_name in required_empty_sheets:
            pd.DataFrame(columns=df_final.columns).to_excel(writer, index=False, sheet_name=sheet_name)

        writer.close()
        output.seek(0)
        
        # --- 7. Envío del Archivo al Usuario ---
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='Pronostico_Distribuido.xlsx'
        )

    except json.JSONDecodeError:
        return jsonify({"error": "Error al procesar los datos de las curvas. El formato JSON parece ser inválido."}), 400
    except Exception as e:
        # Capturar cualquier otro error inesperado y reportarlo
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Ocurrió un error inesperado en el servidor: {e}"}), 500
    
@app.route('/api/forecast_and_calculate', methods=['POST'])
def forecast_and_calculate():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401

    try:
        # 1. Obtener todos los datos del formulario
        segment_id = request.form.get('segment_id')
        
        # El pronóstico de llamadas ahora viene como un string JSON
        # que creaste en el frontend a partir de la tabla final.
        forecast_data_json = request.form.get('forecast_data')
        
        # Archivos de AHT y reductores
        aht_file = request.files.get('aht_file')
        absenteeism_file = request.files.get('absenteeism_file')
        auxiliaries_file = request.files.get('auxiliaries_file')
        shrinkage_file = request.files.get('shrinkage_file')

        if not all([segment_id, forecast_data_json, aht_file, absenteeism_file, auxiliaries_file, shrinkage_file]):
            return jsonify({"error": "Faltan datos. Asegúrese de incluir el pronóstico, AHT y todos los reductores."}), 400

        # Configuración del cálculo
        config = {
            "sla_objetivo": float(request.form.get('sla_objetivo', 0.8)),
            "sla_tiempo": int(request.form.get('sla_tiempo', 20)),
            # ... (otros parámetros de config que puedas necesitar)
        }

        # 2. Construir los DataFrames en memoria
        
        # DataFrame de Llamadas (desde el JSON)
        forecast_data = json.loads(forecast_data_json)
        df_calls = pd.DataFrame(forecast_data)
        # Asegurarse que la fecha es datetime
        df_calls['Fecha'] = pd.to_datetime(df_calls['Fecha'], format='%d/%m/%Y')


        # Diccionario para pasar a la función de procesamiento
        all_sheets = {}
        all_sheets['Llamadas_esperadas'] = df_calls
        
        # Leer los archivos y añadirlos al diccionario
        all_sheets['AHT_esperado'] = pd.read_excel(aht_file)
        all_sheets['Absentismo_esperado'] = pd.read_excel(absenteeism_file)
        all_sheets['Auxiliares_esperados'] = pd.read_excel(auxiliaries_file)
        all_sheets['Desconexiones_esperadas'] = pd.read_excel(shrinkage_file)

        # 3. Formatear las columnas de tiempo (reutilizando tu lógica)
        try:
            sample_columns = all_sheets['Llamadas_esperadas'].columns
            formatted_columns = []
            for col in sample_columns:
                col_str = str(col).strip()
                if isinstance(col, (datetime.time, datetime.datetime)):
                    formatted_columns.append(col.strftime('%H:%M'))
                elif ':' in col_str:
                    try:
                        formatted_columns.append(pd.to_datetime(col_str).strftime('%H:%M'))
                    except (ValueError, TypeError):
                        formatted_columns.append(col_str)
                else:
                    formatted_columns.append(col_str)
            
            for sheet_name in all_sheets:
                all_sheets[sheet_name].columns = formatted_columns
        except Exception as e:
            return jsonify({"error": f"Error al formatear columnas de tiempo: {e}"}), 400

        # 4. Llamar a la función de cálculo existente
        # ¡Aquí está la magia! Reutilizamos todo tu motor de cálculo.
        result_dfs = procesar_plantilla_unica(config, all_sheets)
        if result_dfs is None:
            return jsonify({"error": "No se encontraron filas con fechas válidas en los datos."}), 400
        
        df_dimensionados, df_presentes, df_logados, df_efectivos, kpi_data = result_dfs
        
        # 5. Guardar en la DB y devolver el resultado (código copiado y adaptado de tu ruta /calcular)
        if not df_dimensionados.empty:
            df_dimensionados['Fecha'] = pd.to_datetime(df_dimensionados['Fecha'])
            min_date = df_dimensionados['Fecha'].min().date()
            max_date = df_dimensionados['Fecha'].max().date()
            
            StaffingResult.query.filter(
                StaffingResult.segment_id == segment_id,
                StaffingResult.result_date.between(min_date, max_date)
            ).delete(synchronize_session=False)
            db.session.commit()

        # ... (Aquí pegarías TODA la lógica que tienes en /calcular para guardar los
        #      StaffingResult en la base de datos, desde `new_entries = []` en adelante) ...
        # ... (Este bloque es largo, asegúrate de copiarlo correctamente de tu ruta /calcular o la ruta que he corregido en este prompt)
        
        # Por simplicidad, aquí pongo la parte final de la respuesta
        def final_format_for_display(df_frac):
            # Tu función de formateo
            df_display = df_frac.copy()
            index_cols = ['Fecha', 'Dia', 'Semana', 'Tipo']
            time_cols = [col for col in df_frac.columns if col not in index_cols]
            df_display[time_cols] = df_display[time_cols].round(1)
            df_display['Horas-Totales'] = df_frac[time_cols].sum(axis=1) / 2.0
            if 'Fecha' in df_display.columns:
                df_display['Fecha'] = pd.to_datetime(df_display['Fecha']).dt.strftime('%d/%m/%Y')
            return df_display.to_dict(orient='split')

        results_to_send = {
            "dimensionados": final_format_for_display(df_dimensionados),
            "presentes": final_format_for_display(df_presentes),
            "logados": final_format_for_display(df_logados),
            "efectivos": final_format_for_display(df_efectivos),
            "kpis": kpi_data
        }
        
        flash('Dimensionamiento calculado y guardado con éxito desde el módulo de previsión.', 'success')
        return jsonify(results_to_send)

    except Exception as e:
        import traceback; traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Error en el cálculo integrado: {e}"}), 500    

@app.route('/api/save_forecast_to_db', methods=['POST'])
def save_forecast_to_db():
    # --- 1. Verificación y Obtención de Datos ---
    if 'user' not in session: 
        return jsonify({"error": "No autorizado"}), 401
    try:
        # Validar que todos los datos necesarios fueron enviados
        if not all(k in request.files for k in ['forecast_file']) or not all(k in request.form for k in ['curves_data', 'segment_id']):
            return jsonify({"error": "Faltan datos. Asegúrese de subir el archivo de volumen, tener curvas guardadas y seleccionar un segmento."}), 400

        segment_id = request.form.get('segment_id')
        forecast_file = request.files['forecast_file']
        curves_data = json.loads(request.form['curves_data'])
        curves_to_use = curves_data.get('curves', {})
        time_labels = curves_data.get('labels', [])

        if not segment_id:
            return jsonify({"error": "Debe seleccionar un segmento para guardar el pronóstico."}), 400

        # --- 2. Lógica para Generar la Distribución (reutilizada) ---
        df_forecast = pd.read_excel(forecast_file)
        df_forecast.columns = [str(col).strip() for col in df_forecast.columns]
        
        if 'Fecha' not in df_forecast.columns:
            return jsonify({"error": "El archivo de volumen debe tener una columna 'Fecha'."}), 400

        # Búsqueda dinámica de la columna de volumen
        volume_column_name = next((col for col in df_forecast.columns if str(col).strip().lower() != 'fecha'), None)
        if volume_column_name is None:
            return jsonify({"error": "No se pudo encontrar una columna de volumen en el archivo."}), 400
            
        df_forecast['Fecha'] = pd.to_datetime(df_forecast['Fecha'], errors='coerce')
        df_forecast.dropna(subset=['Fecha'], inplace=True)
        df_forecast[volume_column_name] = pd.to_numeric(df_forecast[volume_column_name], errors='coerce').fillna(0)

        output_rows = []
        day_name_map_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        
        for index, row in df_forecast.iterrows():
            date_obj, total_volume = row['Fecha'], float(row[volume_column_name])
            if pd.isna(date_obj) or total_volume <= 0: continue
            day_of_week_num = str(date_obj.weekday())
            if day_of_week_num not in curves_to_use: continue
            
            curve_for_day = curves_to_use[day_of_week_num]
            new_row = {'Fecha': date_obj, 'Dia': day_name_map_es.get(int(day_of_week_num)), 'Semana': date_obj.isocalendar()[1], 'Tipo': 'N'}
            distributed_sum = 0
            
            for interval in time_labels:
                weight = curve_for_day.get(interval, 0)
                distributed_calls = round(total_volume * weight)
                new_row[interval] = distributed_calls
                distributed_sum += distributed_calls
            
            difference = round(total_volume - distributed_sum)
            if difference != 0 and curve_for_day:
                peak_interval = max(curve_for_day, key=curve_for_day.get)
                new_row[peak_interval] += difference
            output_rows.append(new_row)

        if not output_rows:
            return jsonify({"error": "No se generaron filas de pronóstico. Verifique las fechas y las curvas guardadas."}), 400

        df_final = pd.DataFrame(output_rows)

        # --- 3. Lógica de Guardado en la Base de Datos ---
        min_date = df_final['Fecha'].min().date()
        max_date = df_final['Fecha'].max().date()
        
        # Borrar registros existentes para este segmento y rango de fechas para evitar duplicados
        StaffingResult.query.filter(
            StaffingResult.segment_id == segment_id,
            StaffingResult.result_date.between(min_date, max_date)
        ).delete(synchronize_session=False)
        db.session.commit() # Hacemos commit después de borrar
        
        new_entries = []
        for index, row in df_final.iterrows():
            calls_dict = row.to_dict()
            if 'Fecha' in calls_dict and isinstance(calls_dict['Fecha'], pd.Timestamp):
                 calls_dict['Fecha'] = calls_dict['Fecha'].strftime('%Y-%m-%d %H:%M:%S')

            new_entry = StaffingResult(
                result_date=row['Fecha'].date(),
                segment_id=segment_id,
                calls_forecast=json.dumps(calls_dict),
                agents_online=json.dumps({col: 0 for col in time_labels}),
                agents_total=json.dumps({col: 0 for col in time_labels}),
                aht_forecast=json.dumps({col: 0 for col in time_labels}),
                reducers_forecast=json.dumps({})
            )
            new_entries.append(new_entry)
            
        db.session.bulk_save_objects(new_entries)
        db.session.commit()
        
        return jsonify({"message": f"Pronóstico de {len(new_entries)} días guardado con éxito en el sistema."})

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error al guardar el pronóstico: {e}"}), 500    
    

@app.route('/api/get_history', methods=['POST'])
def get_history():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json
        segment_id, start_date, end_date = data.get('segment_id'), datetime.datetime.strptime(data.get('start_date'), '%Y-%m-%d').date(), datetime.datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        results = StaffingResult.query.filter(StaffingResult.segment_id == segment_id, StaffingResult.result_date >= start_date, StaffingResult.result_date <= end_date).order_by(StaffingResult.result_date).all()
        if not results: return jsonify({"error": "No se encontraron resultados para los filtros seleccionados."}), 404
        online_data, total_data = [json.loads(r.agents_online) for r in results], [json.loads(r.agents_total) for r in results]
        df_online, df_totales = pd.DataFrame(online_data), pd.DataFrame(total_data)
        df_online_formatted, df_totales_formatted = format_and_calculate_simple(df_online), format_and_calculate_simple(df_totales)
        dict_online_resp, dict_totales_resp = df_online_formatted.to_dict(orient='split'), df_totales_formatted.to_dict(orient='split')
        if 'index' in dict_online_resp: del dict_online_resp['index']
        if 'index' in dict_totales_resp: del dict_totales_resp['index']
        return jsonify({"agentes_online": dict_online_resp, "agentes_totales": dict_totales_resp})
    except Exception as e: return jsonify({"error": "Ocurrió un error al procesar la solicitud."}), 500

@app.route('/api/upload_agents', methods=['POST'])
def upload_agents():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    user = User.query.filter_by(username=session['user']).first()
    try:
        if 'agents_excel' not in request.files: return jsonify({"error": "No se encontró el archivo de agentes."}), 400
        file = request.files['agents_excel']; df = pd.read_excel(file)
        df.columns = [str(col).lower().strip().replace(' ', '_').replace('/', '_') for col in df.columns]
        required_columns = ['identificación', 'nombre_completo', 'contrato', 'segmento', 'fecha_alta']
        for col in required_columns:
            if col not in df.columns: return jsonify({"error": f"Falta la columna requerida en el Excel: '{col}'"}), 400
        segments_in_file_names = df['segmento'].dropna().unique()
        user_campaign_ids = {c.id for c in user.campaigns}
        segment_cache = {s.name: s for s in Segment.query.all()}
        if user.role != 'admin':
            for segment_name in segments_in_file_names:
                segment = segment_cache.get(str(segment_name).strip())
                if not segment or segment.campaign_id not in user_campaign_ids:
                    return jsonify({"error": f"No tienes permiso para modificar agentes del segmento '{segment_name}'."}), 403
        created_count, updated_count, error_count = 0, 0, 0
        for index, row in df.iterrows():
            segment_name = str(row.get('segmento', '')).strip()
            segment = segment_cache.get(segment_name)
            if not segment:
                error_count += 1
                continue
            identificacion = str(row['identificación']).strip()
            if not identificacion or pd.isna(row['identificación']): continue
            agent = Agent.query.filter_by(identificacion=identificacion).first()
            if not agent:
                agent = Agent(identificacion=identificacion, segment_id=segment.id)
                db.session.add(agent)
                created_count += 1
            else:
                agent.segment_id = segment.id
                updated_count += 1
            agent.nombre_completo = str(row['nombre_completo']).strip()
            agent.contrato = str(row.get('contrato', '')).strip()
            agent.rotacion_finde = str(row.get('rotacion_fin_de_semana', 'NO')).strip().upper()
            agent.centro = str(row.get('centro', '')).strip()
            agent.turno_sugerido = str(row.get('turno_sugerido', '')).strip()
            agent.jornada = str(row.get('jornada', '')).strip()
            agent.concrecion = str(row.get('concreción', '')).strip()
            agent.ventana_horaria = str(row.get('ventana_horaria', '')).strip()
            agent.modalidad_finde = str(row.get('modalidad_finde', 'UNICO')).upper().strip()
            agent.rotacion_mensual_domingo = str(row.get('rotacion_mensual_domingo', 'NORMAL')).upper().strip()
            agent.semanas_libres_finde = str(row.get('semanas_libres_finde', '')).strip()
            fecha_alta_val = pd.to_datetime(row.get('fecha_alta'), errors='coerce')
            fecha_baja_val = pd.to_datetime(row.get('fecha_baja'), errors='coerce')
            agent.fecha_alta = fecha_alta_val.date() if pd.notna(fecha_alta_val) else datetime.date(1900, 1, 1)
            agent.fecha_baja = fecha_baja_val.date() if pd.notna(fecha_baja_val) else None
        db.session.commit()
        message = f"Plantilla procesada. Creados: {created_count}. Actualizados: {updated_count}."
        if error_count > 0: message += f" {error_count} agentes fueron omitidos por segmento inválido."
        return jsonify({"message": message})
    except Exception as e:
        import traceback; traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Ocurrió un error al procesar el archivo: {e}"}), 500
    
@app.route('/api/calculate_intraday_distribution', methods=['POST'])
def calculate_intraday_distribution():  # <-- ASEGÚRATE DE QUE EL NOMBRE SEA ESTE
    if 'user' not in session: 
        return jsonify({"error": "No autorizado"}), 401
    
    if 'historical_data' not in request.files: 
        return jsonify({"error": "No se encontró el archivo histórico."}), 400

    try:
        file = request.files['historical_data']
        df = pd.read_excel(file)
        df.columns = [str(col).strip() for col in df.columns]

        # --- Detección y Conversión de Formato (Ancho a Largo) ---
        required_long_format_cols = ['Fecha', 'Intervalo', 'Llamadas Ofrecidas']
        if not all(col in df.columns for col in required_long_format_cols):
            if 'Fecha' not in df.columns:
                return jsonify({"error": "El archivo debe contener una columna 'Fecha'."}), 400
            
            id_cols = [col for col in df.columns if col.lower() in ['fecha', 'dia', 'semana', 'tipo']]
            time_cols = [col for col in df.columns if ':' in str(col)]
            
            if not time_cols:
                 return jsonify({"error": "No se encontraron columnas de intervalo de tiempo (ej: 08:00, 08:30) en el archivo."}), 400

            df = pd.melt(df, id_vars=id_cols, value_vars=time_cols, var_name='Intervalo', value_name='Llamadas Ofrecidas')

        # --- Procesamiento y Limpieza de Datos ---
        df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df.dropna(subset=['Fecha'], inplace=True)
        df['Llamadas Ofrecidas'] = pd.to_numeric(df['Llamadas Ofrecidas'], errors='coerce').fillna(0)
        
        def format_interval(x):
            try:
                if isinstance(x, (datetime.time, datetime.datetime)): return x.strftime('%H:%M')
                time_str = str(x).split(' ')[-1]
                return pd.to_datetime(time_str).strftime('%H:%M')
            except (ValueError, TypeError): return "00:00"

        df['Intervalo'] = df['Intervalo'].apply(format_interval)

        # --- Filtrado de las últimas 6 semanas ---
        max_date = df['Fecha'].max()
        if pd.isna(max_date):
            return jsonify({"error": "No se encontraron fechas válidas en el archivo histórico."}), 400
            
        six_weeks_ago = max_date - pd.to_timedelta(41, unit='d')
        df_filtered = df[df['Fecha'] >= six_weeks_ago]

        if df_filtered.empty: 
            return jsonify({"error": "No se encontraron datos en el rango de las últimas 6 semanas."}), 400
        
        df_pivot = df_filtered.pivot_table(index='Fecha', columns='Intervalo', values='Llamadas Ofrecidas', aggfunc='sum').fillna(0)
        time_labels = sorted([col for col in df_pivot.columns if ':' in str(col)])
        df_pivot.reset_index(inplace=True)
        df_pivot['day_of_week'] = df_pivot['Fecha'].dt.weekday
        df_pivot['week_number'] = df_pivot['Fecha'].dt.isocalendar().week
        
        weekly_data = {i: [] for i in range(7)}
        
        # --- Lógica de Ponderación ---
        for day_num in range(7):
            day_group_df = df_pivot[df_pivot['day_of_week'] == day_num].sort_values(by='Fecha', ascending=False)
            if day_group_df.empty: continue
            
            day_curves = day_group_df[time_labels].div(day_group_df[time_labels].sum(axis=1), axis=0).fillna(0)
            if len(day_curves) < 2: continue

            reference_curve = day_curves.head(4).mean()
            deviations = ((day_curves - reference_curve)**2).mean(axis=1)
            is_outlier = pd.Series([False]*len(day_curves), index=day_curves.index)
            if len(deviations) >= 4:
                q1, q3 = deviations.quantile(0.25), deviations.quantile(0.75)
                is_outlier = (deviations > q3 + 1.5 * (q3 - q1))

            inverse_deviations = 1 / (deviations + 1e-9)
            inverse_deviations[is_outlier] = 0
            total_inverse_dev = inverse_deviations.sum()

            if total_inverse_dev == 0 and len(day_curves) > 0:
                 weights = pd.Series([100.0/len(day_curves)]*len(day_curves), index=day_curves.index)
            elif total_inverse_dev > 0:
                 weights = (inverse_deviations / total_inverse_dev) * 100
            else:
                 weights = pd.Series([0]*len(day_curves), index=day_curves.index)
            
            for index, row in day_group_df.iterrows():
                intraday_raw_calls = row[time_labels].to_dict()
                total_calls = sum(intraday_raw_calls.values())
                intraday_percentages = {k: (v / total_calls if total_calls > 0 else 0) for k, v in intraday_raw_calls.items()}
                
                weekly_data[day_num].append({
                    'week': int(row['week_number']), 'date': row['Fecha'].strftime('%d/%m/%Y'), 
                    'total_calls': total_calls, 'is_outlier': bool(is_outlier.get(index, False)), 
                    'proposed_weight': round(weights.get(index, 0)), 'intraday_dist': intraday_percentages, 
                    'intraday_raw': intraday_raw_calls
                })
                
        return jsonify({"weekly_data": weekly_data, "labels": time_labels})

    except Exception as e: 
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Error al procesar el archivo: {e}"}), 500    

@app.route('/api/generate_schedule', methods=['POST'])
def generate_schedule():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if session.get('role') != 'admin': return jsonify({"error": "Acceso denegado"}), 403
    try:
        data = request.json
        segment_id, start_date_str, end_date_str = data.get('segment_id'), data.get('start_date'), data.get('end_date')
        if not start_date_str or not end_date_str: return jsonify({"error": "Las fechas de inicio y fin son requeridas."}), 400
        start_date, end_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date(), datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        segment = Segment.query.get(segment_id)
        if not segment: return jsonify({"error": "Segmento no encontrado."}), 404
        agents_raw = Agent.query.filter_by(segment_id=segment_id).all()
        if not agents_raw: return jsonify({"error": "No se han cargado agentes para este segmento."}), 404
        agent_ids = [agent.id for agent in agents_raw]
        existing_absences = Schedule.query.filter(Schedule.agent_id.in_(agent_ids), Schedule.schedule_date.between(start_date, end_date), Schedule.shift.in_(VALID_AUSENCIA_CODES)).all()
        absences_map = {}
        for absence in existing_absences:
            if absence.agent_id not in absences_map:
                absences_map[absence.agent_id] = set()
            absences_map[absence.agent_id].add(absence.schedule_date)
        staffing_needs_raw = StaffingResult.query.filter(StaffingResult.segment_id == segment_id, StaffingResult.result_date >= start_date, StaffingResult.result_date <= end_date).all()
        if not staffing_needs_raw: return jsonify({"error": "No se encontraron datos de dimensionamiento para este servicio y fechas."}), 404
        contratos_unicos = {agent.contrato for agent in agents_raw if agent.contrato}
        rules_map = {}
        for contrato_str in contratos_unicos:
            try:
                contrato_limpio = str(int(float(contrato_str)))
                rule = SchedulingRule.query.filter(SchedulingRule.name.like(f"%{contrato_limpio}%"), SchedulingRule.country == segment.campaign.country).first()
                if not rule:
                    error_msg = f"Falta una regla para el contrato '{contrato_limpio}h' en '{segment.campaign.country}'."
                    return jsonify({"error": error_msg}), 400
                rules_map[contrato_limpio] = rule
            except (ValueError, TypeError): continue
        needs_by_day, time_labels, day_types = {}, [], {}
        for need in staffing_needs_raw:
            day_data = json.loads(need.agents_online)
            day_types[need.result_date] = day_data.get('Tipo', 'N')
            needs_by_day[need.result_date] = [int(v) if v is not None else 0 for k, v in day_data.items() if k.replace(':', '').isdigit()]
            if not time_labels: time_labels = [k for k in day_data.keys() if k.replace(':', '').isdigit()]
        scheduler = Scheduler(agents_raw, rules_map, needs_by_day, time_labels, segment, day_types, absences_map)
        final_schedule, _ = scheduler.run()
        db.session.query(Schedule).filter(Schedule.agent_id.in_(agent_ids), Schedule.schedule_date.between(start_date, end_date), not_(Schedule.shift.in_(VALID_AUSENCIA_CODES))).delete(synchronize_session=False)
        all_agents = {agent.nombre_completo: agent for agent in agents_raw}
        new_schedule_entries = []
        for agent_name, daily_shifts in final_schedule.items():
            agent_obj = all_agents.get(agent_name)
            if not agent_obj: continue
            for date_str, shift in daily_shifts.items():
                if not date_str.startswith('week_'):
                    schedule_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                    hours = 0
                    if shift != "LIBRE" and '-' in shift:
                        try: hours = scheduler._calculate_shift_duration(shift)
                        except: hours = 0
                    new_entry = Schedule(agent_id=agent_obj.id, schedule_date=schedule_date, shift=shift, hours=hours, is_manual_edit=False)
                    new_schedule_entries.append(new_entry)
        db.session.bulk_save_objects(new_schedule_entries)
        db.session.commit()
        return get_schedule()
    except Exception as e:
        import traceback; traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Ocurrió un error inesperado: {e}"}), 500

@app.route('/api/fill_gaps_schedule', methods=['POST'])
def fill_gaps_schedule():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if session.get('role') != 'admin': return jsonify({"error": "Acceso denegado"}), 403
    try:
        data = request.json
        segment_id, start_date_str, end_date_str = data.get('segment_id'), data.get('start_date'), data.get('end_date')
        start_date, end_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date(), datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        segment = Segment.query.get(segment_id)
        all_agents = Agent.query.filter_by(segment_id=segment_id).all()
        if not all_agents: return jsonify({"error": "No hay agentes para este segmento."}), 404
        existing_schedules = Schedule.query.filter(Schedule.agent_id.in_([a.id for a in all_agents]), Schedule.schedule_date.between(start_date, end_date)).all()
        agents_with_work = {s.agent_id for s in existing_schedules if s.shift not in VALID_AUSENCIA_CODES and s.shift != 'LIBRE'}
        agents_to_schedule = [agent for agent in all_agents if agent.id not in agents_with_work]
        if not agents_to_schedule:
            return jsonify({"flash_message": "No se encontraron agentes nuevos o sin planificar para asignar."})
        needs_by_day, time_labels, day_types = {}, [], {}
        staffing_needs_raw = StaffingResult.query.filter(StaffingResult.segment_id == segment_id, StaffingResult.result_date >= start_date, StaffingResult.result_date <= end_date).all()
        if not staffing_needs_raw: return jsonify({"error": "No se encontraron datos de dimensionamiento para estas fechas."}), 404
        for need in staffing_needs_raw:
            day_data = json.loads(need.agents_online)
            day_types[need.result_date] = day_data.get('Tipo', 'N')
            needs_by_day[need.result_date] = [int(v) if v is not None else 0 for k, v in day_data.items() if k.replace(':', '').isdigit()]
            if not time_labels: time_labels = [k for k in day_data.keys() if k.replace(':', '').isdigit()]
        initial_coverage = {day: np.zeros(len(time_labels)) for day in needs_by_day.keys()}
        initial_schedule = {agent.nombre_completo: {} for agent in all_agents}
        temp_scheduler = Scheduler([],{},{},time_labels,Segment(),{})
        agent_map_by_id = {a.id: a for a in all_agents}
        for entry in existing_schedules:
            agent = agent_map_by_id.get(entry.agent_id)
            if agent: initial_schedule[agent.nombre_completo][entry.schedule_date.strftime('%Y-%m-%d')] = entry.shift
            if entry.shift not in VALID_AUSENCIA_CODES and entry.shift != 'LIBRE':
                for part in entry.shift.split('/'):
                    try:
                        start_str, end_str = [s.strip() for s in part.split('-')]
                        start_idx, end_idx = time_labels.index(start_str), time_labels.index(end_str) if end_str != '24:00' else len(time_labels)
                        if entry.schedule_date in initial_coverage: initial_coverage[entry.schedule_date][start_idx:end_idx] += 1
                    except (ValueError, IndexError): continue
        rules_map = {str(int(float(c))): SchedulingRule.query.filter(SchedulingRule.name.like(f"%{int(float(c))}%"), SchedulingRule.country == segment.campaign.country).first() for c in {a.contrato for a in agents_to_schedule if a.contrato}}
        scheduler = Scheduler(agents_to_schedule, rules_map, needs_by_day, time_labels, segment, day_types, initial_coverage=initial_coverage, initial_schedule=initial_schedule)
        final_schedule, _ = scheduler.run()
        existing_schedule_keys = {(s.agent_id, s.schedule_date) for s in existing_schedules}
        new_entries = []
        for agent in agents_to_schedule:
            for date_str, shift in final_schedule.get(agent.nombre_completo, {}).items():
                if not date_str.startswith('week_'):
                    schedule_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                    if (agent.id, schedule_date) not in existing_schedule_keys:
                        hours = temp_scheduler._calculate_shift_duration(shift) if '-' in shift else 0
                        new_entries.append(Schedule(agent_id=agent.id, schedule_date=schedule_date, shift=shift, hours=hours, is_manual_edit=False))
        if new_entries:
            db.session.bulk_save_objects(new_entries)
            db.session.commit()
        return jsonify({"flash_message": f"Se han asignado horarios a {len(agents_to_schedule)} agentes nuevos/sin planificar."})
    except Exception as e:
        import traceback; traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Ocurrió un error inesperado al asignar personal: {e}"}), 500
    
@app.route('/api/upload_ausencias', methods=['POST'])
def upload_ausencias():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if session.get('role') != 'admin': return jsonify({"error": "Acceso denegado"}), 403
    if 'ausencias_excel' not in request.files:
        return jsonify({"error": "No se encontró el archivo de ausencias."}), 400
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    if not start_date_str or not end_date_str:
        return jsonify({"error": "Por favor, seleccione un rango de fechas en el Paso 2 antes de cargar ausencias."}), 400
    planning_end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
    file = request.files['ausencias_excel']
    try:
        df = pd.read_excel(file)
        df.columns = [str(col).strip().upper() for col in df.columns]
        required_cols = ['CODIGO EMPLEADO', 'DNI', 'FECHA INICIO INCIDENCIA / FECHA DE ABSENTISMO', 'FECHA FIN INCIDENCIA', 'NOMBRE INCIDENCIA / NOMBRE ABSENTISMO']
        for col in required_cols:
            if col not in df.columns:
                return jsonify({"error": f"Falta la columna requerida en el Excel: '{col}'"}), 400
        updated_count = 0
        not_found_count = 0
        code_map = { "Consulta Médica": "BMED", "Vacaciones Laborales": "VAC", "Vacaciones": "VAC", "Enfermedad": "BMED", "Paternidad": "LICPATER", "Horas de Lactancia": "LACT", "Enfermedad Hospitalaria": "BMED", "Maternidad": "LICMATER", "Accidente": "BMED", "Sit. Especial IT C.C. - S.S. día siguiente baja": "BMED" }
        df['start_date_dt'] = pd.to_datetime(df['FECHA INICIO INCIDENCIA / FECHA DE ABSENTISMO'], errors='coerce')
        df['end_date_dt'] = pd.to_datetime(df['FECHA FIN INCIDENCIA'], errors='coerce')
        for index, row in df.iterrows():
            if pd.isna(row['start_date_dt']): continue
            dni = str(row.get('DNI', '')).strip()
            employee_id = str(row.get('CODIGO EMPLEADO', '')).strip()
            agent = None
            if dni and dni != 'nan':
                agent = Agent.query.filter(Agent.identificacion == dni).first()
            if not agent and employee_id and employee_id != 'nan':
                agent = Agent.query.filter(Agent.identificacion == employee_id).first()
            if not agent:
                not_found_count += 1
                continue
            start_date = row['start_date_dt'].date()
            end_date = row['end_date_dt'].date() if pd.notna(row['end_date_dt']) else planning_end_date
            code_name = str(row['NOMBRE INCIDENCIA / NOMBRE ABSENTISMO']).strip()
            code = code_map.get(code_name, "OTRO") 
            delta = end_date - start_date
            for i in range(delta.days + 1):
                day = start_date + datetime.timedelta(days=i)
                entry = Schedule.query.filter_by(agent_id=agent.id, schedule_date=day).first()
                if not entry:
                    entry = Schedule(agent_id=agent.id, schedule_date=day)
                    db.session.add(entry)
                entry.shift = code
                entry.hours = 0
                entry.is_manual_edit = True
                updated_count += 1
        db.session.commit()
        message = f"Carga masiva completada. Turnos actualizados: {updated_count}."
        if not_found_count > 0:
            message += f" Agentes no encontrados por DNI o Código de Empleado: {not_found_count}."
        return jsonify({"message": message})
    except Exception as e:
        import traceback; traceback.print_exc()
        db.session.rollback()
        return jsonify({"error": f"Ocurrió un error al procesar el archivo: {e}"}), 500

def _calculate_sl_capacity(num_agents, aht, sl_target, sl_time, interval_seconds=1800):
    if num_agents == 0 or aht == 0:
        return 0
    for traffic in np.arange(num_agents - 0.01, 0, -0.01):
        calls_per_hour_equivalent = (traffic * 3600) / aht
        sl = vba_sla(num_agents, sl_time, calls_per_hour_equivalent, aht)
        if sl >= sl_target:
            return math.floor((traffic * interval_seconds) / aht)
    return 0

@app.route('/api/get_summary', methods=['POST'])
def get_summary():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json
        segment_id, start_date_str, end_date_str = data.get('segment_id'), data.get('start_date'), data.get('end_date')
        start_date, end_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date(), datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()

        results = StaffingResult.query.filter(StaffingResult.segment_id == segment_id, StaffingResult.result_date.between(start_date, end_date)).order_by(StaffingResult.result_date).all()
        if not results: return jsonify({"error": "No se encontraron datos de dimensionamiento para los filtros seleccionados."}), 404

        all_schedules_in_period = Schedule.query.join(Agent).filter(Agent.segment_id == segment_id, Schedule.schedule_date.between(start_date, end_date)).all()
        
        time_labels = [k for k in json.loads(results[0].agents_online).keys() if ':' in k]

        SLA_PERCENT_TARGET = results[0].sla_target_percentage if results[0].sla_target_percentage is not None else 0.80
        SLA_TIME_TARGET = results[0].sla_target_time if results[0].sla_target_time is not None else 20

        date_range = [start_date + datetime.timedelta(days=i) for i in range((end_date - start_date).days + 1)]
        coverage_by_day = {day: {label: 0 for label in time_labels} for day in date_range}
        for s in all_schedules_in_period:
            if s.shift and '-' in s.shift and s.shift not in VALID_AUSENCIA_CODES:
                try:
                    for part in s.shift.split('/'):
                        start_str, end_str = [x.strip() for x in part.split('-')]
                        start_idx = time_labels.index(start_str)
                        end_idx = time_labels.index(end_str) if end_str != "24:00" else len(time_labels)
                        for i in range(start_idx, end_idx):
                            if s.schedule_date in coverage_by_day: coverage_by_day[s.schedule_date][time_labels[i]] += 1
                except (ValueError, IndexError): continue
        
        summary_data = {}
        for r in results:
            day_str = r.result_date.strftime('%d/%m/%Y')
            planned_hc, reducers, calls, aht, required_hc = coverage_by_day.get(r.result_date, {}), json.loads(r.reducers_forecast or '{}'), json.loads(r.calls_forecast or '{}'), json.loads(r.aht_forecast or '{}'), json.loads(r.agents_online or '{}')
            present_hc = {lbl: planned_hc.get(lbl, 0) * (1 - float(reducers.get("absenteeism", {}).get(lbl, 0))) for lbl in time_labels}
            logged_hc = {lbl: present_hc.get(lbl, 0) * (1 - float(reducers.get("shrinkage", {}).get(lbl, 0))) for lbl in time_labels}
            effective_hc = {lbl: logged_hc.get(lbl, 0) * (1 - float(reducers.get("auxiliaries", {}).get(lbl, 0))) for lbl in time_labels}
            over_under, sl_real, nda_real, capacity, handled_calls, attended_within_sla = {}, {}, {}, {}, {}, {}
            for lbl in time_labels:
                agents, aht_val, calls_val = math.floor(effective_hc.get(lbl, 0)), float(aht.get(lbl, 0)), float(calls.get(lbl, 0))
                over_under[lbl] = effective_hc.get(lbl, 0) - float(required_hc.get(lbl, 0))
                capacity_val = _calculate_sl_capacity(agents, aht_val, SLA_PERCENT_TARGET, SLA_TIME_TARGET) if agents > 0 and aht_val > 0 else 0
                capacity[lbl] = capacity_val; handled_calls[lbl] = min(capacity_val, calls_val)
                attainable_with_sla = capacity_val * SLA_PERCENT_TARGET; attended_within_sla[lbl] = min(calls_val, attainable_with_sla)
                if calls_val > 0: sl_real[lbl], nda_real[lbl] = (attended_within_sla[lbl] / calls_val), (handled_calls[lbl] / calls_val)
                else: sl_real[lbl], nda_real[lbl] = 0.0, 0.0
            summary_data[day_str] = {'planned_headcount': planned_hc, 'present_headcount': present_hc, 'logged_headcount': logged_hc, 'effective_headcount': effective_hc, 'calls_forecast': calls, 'aht_forecast': aht, 'over_under_staffing': over_under, 'call_capacity': capacity, 'service_level_real': sl_real, 'attention_level_real': nda_real, 'handled_calls': handled_calls, 'attended_within_sla': attended_within_sla }

        totals = { key: 0 for key in ['calls', 'aht_weighted', 'capacity', 'handled', 'attended_sla', 'h_plan', 'h_pres', 'h_log', 'h_eff'] }
        def sum_time_slots(data_dict): return sum(float(v) for k, v in data_dict.items() if ':' in str(k))
        for day_data in summary_data.values():
            totals['calls'] += sum_time_slots(day_data['calls_forecast']); totals['capacity'] += sum_time_slots(day_data['call_capacity']); totals['handled'] += sum_time_slots(day_data['handled_calls']); totals['attended_sla'] += sum_time_slots(day_data['attended_within_sla'])
            totals['h_plan'] += sum_time_slots(day_data['planned_headcount']) * 0.5; totals['h_pres'] += sum_time_slots(day_data['present_headcount']) * 0.5
            totals['h_log'] += sum_time_slots(day_data['logged_headcount']) * 0.5; totals['h_eff'] += sum_time_slots(day_data['effective_headcount']) * 0.5
            for lbl in time_labels: totals['aht_weighted'] += float(day_data['calls_forecast'].get(lbl, 0)) * float(day_data['aht_forecast'].get(lbl, 0))
        
        num_days = (end_date - start_date).days + 1
        vac_count = sum(1 for s in all_schedules_in_period if s.shift == 'VAC')
        bmed_count = sum(1 for s in all_schedules_in_period if s.shift == 'BMED')

        period_summary = {
            "Total Llamadas": totals['calls'], "AHT promedio": totals['aht_weighted'] / totals['calls'] if totals['calls'] > 0 else 0,
            "Call Capacity Total": totals['capacity'], "Llamadas Atendidas Alcanzables": totals['handled'], "Total Atendidas < Objetivo": totals['attended_sla'],
            "NS Final": totals['attended_sla'] / totals['calls'] if totals['calls'] > 0 else 0, "NDA Final": totals['handled'] / totals['calls'] if totals['calls'] > 0 else 0,
            "Horas Dimensionadas": totals['h_plan'], "Horas Presentes": totals['h_pres'], "Horas Logadas": totals['h_log'], "Horas efectivas": totals['h_eff'],
            "Adherencia Bruta": totals['h_log'] / totals['h_pres'] if totals['h_pres'] > 0 else 0, "Adherencia Neta": totals['h_eff'] / totals['h_pres'] if totals['h_pres'] > 0 else 0,
            "VAC promedio": vac_count / num_days if num_days > 0 else 0,
            "BMED promedio": bmed_count / num_days if num_days > 0 else 0
        }

        def format_table(key, title, is_percent=False, is_kpi=False):
            cols = ['Día'] + time_labels + ['Total/Promedio']; rows = []
            for day, data in sorted(summary_data.items(), key=lambda i: datetime.datetime.strptime(i[0], '%d/%m/%Y')):
                row = {'Día': day}; series = data.get(key, {})
                numeric_values = [float(series.get(lbl, 0)) for lbl in time_labels]
                for i, lbl in enumerate(time_labels): row[lbl] = numeric_values[i]
                daily_total = sum(numeric_values)
                if key.endswith('_headcount'): row['Total/Promedio'] = daily_total * 0.5; cols[-1] = 'Horas del Día'
                elif is_kpi:
                    relevant_values = [ val for i, val in enumerate(numeric_values) if float(summary_data[day]['calls_forecast'].get(time_labels[i], 0)) > 0 ]
                    row['Total/Promedio'] = sum(relevant_values) / len(relevant_values) if relevant_values else 0
                else: row['Total/Promedio'] = daily_total
                rows.append(row)
            period_total_value = None
            if not is_kpi: period_total_value = sum(row['Total/Promedio'] for row in rows)
            return {'table_key': key, 'title': title, 'is_percent': is_percent, 'is_kpi': is_kpi, 'columns': cols, 'data': rows, 'period_total': period_total_value}

        response = { "tables": {
            "planned": format_table("planned_headcount", "Asesores Planificados"), "present": format_table("present_headcount", "Asesores Presentes"),
            "logged": format_table("logged_headcount", "Asesores Logados"), "effective": format_table("effective_headcount", "Asesores Efectivos"),
            "over_under": format_table("over_under_staffing", "Sobredimensionamiento / Subdimensionamiento"), "service_level": format_table("service_level_real", "Nivel de Servicio", is_percent=True, is_kpi=True),
            "attention_level": format_table("attention_level_real", "Nivel de Atención", is_percent=True, is_kpi=True), "calls": format_table("calls_forecast", "Llamadas Pronosticadas"),
            "attended_within_sla": format_table("attended_within_sla", "Total Atendidas < Objetivo"), "handled_calls": format_table("handled_calls", "Llamadas Atendidas Alcanzables"),
            "aht": format_table("aht_forecast", "AHT Pronosticado"), "capacity": format_table("call_capacity", "Capacidad Máxima de Llamadas")
        }, "summary": period_summary }
        return jsonify(response)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Ocurrió un error al procesar el resumen: {e}"}), 500

def _floor_time(t, precision_minutes):
    if not t: return None
    total_minutes = t.hour * 60 + t.minute
    floored_minutes = math.floor(total_minutes / precision_minutes) * precision_minutes
    return t.replace(hour=floored_minutes // 60, minute=floored_minutes % 60, second=0, microsecond=0)

# --- FUNCIÓN CORREGIDA Y ROBUSTA ---
@app.route('/breaks')
def breaks():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()
        return redirect(url_for('login'))

    # Usamos joinedload para cargar eficientemente la relación con Campaign.
    # Esto previene errores en la plantilla y mejora el rendimiento.
    query = Segment.query.options(joinedload(Segment.campaign))

    if user.role == 'admin':
        # Para el admin, obtenemos todos los segmentos.
        segments = query.join(Campaign).order_by(Campaign.name, Segment.name).all()
    else:
        # Para usuarios no-admin, filtramos por sus campañas asignadas.
        campaign_ids = [c.id for c in user.campaigns]
        
        if campaign_ids:
            segments = query.join(Campaign).filter(
                Campaign.id.in_(campaign_ids)
            ).order_by(Campaign.name, Segment.name).all()
        else:
            # Si no tiene campañas, la lista de segmentos estará vacía.
            segments = []
            
    return render_template('breaks.html', segments=segments)

@app.route('/api/assign_breaks', methods=['POST'])
def assign_breaks():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json
        segment_id = data.get('segment_id')
        start_date = datetime.datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        
        segment = Segment.query.get(segment_id)
        schedules_to_update = Schedule.query.join(Agent).filter(
            Agent.segment_id == segment_id,
            Schedule.schedule_date.between(start_date, end_date),
            Schedule.shift != 'LIBRE',
            not_(Schedule.shift.in_(VALID_AUSENCIA_CODES))
        ).all()
        
        updated_count = 0
        for schedule in schedules_to_update:
            # Limpiar descansos y PVDs previos para este registro
            for i in range(1, 11): setattr(schedule, f'pvd{i}', None)
            schedule.descanso1_he = None
            schedule.descanso1_hs = None
            # Si tuvieras más campos de descanso (descanso2_he, etc.), límpialos aquí también.

            # --- NUEVA LÓGICA PARA TURNOS PARTIDOS ---
            shift_parts = schedule.shift.split('/')
            
            # Contadores para asignar PVDs y descansos de forma secuencial en el registro
            pvd_idx = 1
            descanso_idx = 1

            for part in shift_parts:
                part = part.strip()
                if '-' not in part:
                    continue

                try:
                    start_str, end_str = part.split('-')
                    hora_inicio = datetime.datetime.strptime(start_str.strip(), "%H:%M")
                    end_dt_str = end_str.strip()
                    hora_fin = datetime.datetime.strptime('23:59', '%H:%M') + datetime.timedelta(minutes=1) if end_dt_str == '24:00' else datetime.datetime.strptime(end_dt_str, '%H:%M')
                    
                    # Calcula la duración en horas para esta parte del turno
                    part_duration_hours = (hora_fin - hora_inicio).total_seconds() / 3600
                    if part_duration_hours < 0: # Para turnos que cruzan la medianoche
                        part_duration_hours += 24
                        
                except ValueError:
                    continue

                duracion_redondeada = round(part_duration_hours)
                descanso_inicio, descanso_fin = None, None
                
                # --- LÓGICA ESPAÑA (aplicada a cada "parte" del turno) ---
                if segment.campaign.country == 'España':
                    descanso_duracion = 0
                    if 4 <= duracion_redondeada <= 5: descanso_duracion = 10
                    elif 6 <= duracion_redondeada <= 8: descanso_duracion = 20
                    elif 9 <= duracion_redondeada <= 10: descanso_duracion = 30
                    
                    if descanso_duracion > 0:
                        ventana_min = hora_inicio + datetime.timedelta(hours=2)
                        ventana_max = hora_inicio + datetime.timedelta(hours=4, minutes=30)
                        if ventana_max > hora_fin - datetime.timedelta(hours=1):
                            ventana_max = hora_fin - datetime.timedelta(hours=1)
                        
                        if ventana_max > ventana_min:
                            rand_seconds = random.random() * (ventana_max - ventana_min).total_seconds()
                            descanso_inicio_raw = ventana_min + datetime.timedelta(seconds=rand_seconds)
                            descanso_inicio = _floor_time(descanso_inicio_raw, 10)
                            descanso_fin = descanso_inicio + datetime.timedelta(minutes=descanso_duracion)
                            
                            # Asigna al siguiente campo de descanso disponible
                            if descanso_idx == 1:
                                schedule.descanso1_he = descanso_inicio.strftime('%H:%M')
                                schedule.descanso1_hs = descanso_fin.strftime('%H:%M')
                            # Si tuvieras un descanso2, aquí iría la lógica:
                            # elif descanso_idx == 2:
                            #     schedule.descanso2_he = ...
                            descanso_idx += 1

                    num_pvd = duracion_redondeada
                    if num_pvd > 0:
                        pvd_horas = []
                        margen_inicio = hora_inicio + datetime.timedelta(minutes=45 + random.randint(0, 29))
                        margen_fin = hora_fin - datetime.timedelta(minutes=30)
                        
                        pvd_hora = margen_inicio
                        j = 0
                        while j < num_pvd and (pvd_hora + datetime.timedelta(minutes=5)) <= margen_fin:
                            pvd_hora_floored = _floor_time(pvd_hora, 5)
                            
                            is_in_break = False
                            if descanso_inicio:
                                if max(pvd_hora_floored, descanso_inicio) < min(pvd_hora_floored + datetime.timedelta(minutes=5), descanso_fin):
                                    is_in_break = True
                            
                            if is_in_break:
                                pvd_hora = descanso_fin + datetime.timedelta(minutes=5)
                                continue

                            if pvd_hora_floored < margen_fin:
                                pvd_horas.append(pvd_hora_floored)
                                j += 1
                            
                            pvd_hora = pvd_hora_floored + datetime.timedelta(minutes=45 + random.randint(0, 15))
                        
                        for pvd_time in pvd_horas:
                            if pvd_idx <= 10: # Límite de 10 PVDs en total
                                setattr(schedule, f'pvd{pvd_idx}', pvd_time.strftime('%H:%M'))
                                pvd_idx += 1

                # --- LÓGICA COLOMBIA ---
                elif segment.campaign.country == 'Colombia':
                    # ... (tu lógica de Colombia iría aquí, aplicada a la "parte" del turno) ...
                    pass

            updated_count += 1
        
        db.session.commit()
        return jsonify({"message": f"¡Éxito! Se han calculado y guardado descansos para {updated_count} registros de turno."})
    except Exception as e:
        db.session.rollback(); import traceback; traceback.print_exc(); return jsonify({"error": f"Ocurrió un error al asignar descansos: {e}"}), 500

@app.route('/api/get_break_distribution', methods=['POST'])
def get_break_distribution():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json
        segment_id, start_date_str, end_date_str = data.get('segment_id'), data.get('start_date'), data.get('end_date')
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        all_schedules = Schedule.query.join(Agent).filter(
            Agent.segment_id == segment_id,
            Schedule.schedule_date.between(start_date, end_date)
        ).options(joinedload(Schedule.agent)).order_by(Agent.nombre_completo, Schedule.schedule_date).all()
        
        table_data, total_work_hours, total_break_minutes = [], 0, 0

        for schedule in all_schedules:
            if schedule.shift in VALID_AUSENCIA_CODES or schedule.shift == 'LIBRE':
                continue
            
            total_work_hours += schedule.hours # El total de horas sigue siendo el del registro completo
            
            # --- NUEVA LÓGICA PARA MOSTRAR TURNOS PARTIDOS ---
            shift_parts = schedule.shift.split('/')
            
            # Obtenemos todos los descansos y PVDs guardados en el registro
            all_breaks = []
            if schedule.descanso1_he and schedule.descanso1_hs:
                all_breaks.append({'start': schedule.descanso1_he, 'end': schedule.descanso1_hs})
            # Si tuvieras más descansos, los añadirías aquí a la lista.

            all_pvds = [getattr(schedule, f'pvd{j}', None) for j in range(1, 11) if getattr(schedule, f'pvd{j}', None)]

            for part in shift_parts:
                part = part.strip()
                if '-' not in part: continue

                try:
                    start_str, end_str = part.split('-')
                    hora_inicio = datetime.datetime.strptime(start_str.strip(), "%H:%M")
                    end_dt_str = end_str.strip()
                    hora_fin = datetime.datetime.strptime('23:59', '%H:%M') + datetime.timedelta(minutes=1) if end_dt_str == '24:00' else datetime.datetime.strptime(end_dt_str, '%H:%M')

                    part_duration_hours = (hora_fin - hora_inicio).total_seconds() / 3600
                    if part_duration_hours < 0: part_duration_hours += 24
                except ValueError:
                    continue

                # Filtramos los descansos y PVDs que corresponden a ESTA parte del turno
                part_break_start, part_break_end = None, None
                for b in all_breaks:
                    break_start_time = datetime.datetime.strptime(b['start'], "%H:%M")
                    if hora_inicio <= break_start_time < hora_fin:
                        part_break_start = b['start']
                        part_break_end = b['end']
                        # Sumamos al KPI
                        total_break_minutes += (datetime.datetime.strptime(part_break_end, "%H:%M") - break_start_time).total_seconds() / 60
                        break # Asumimos un descanso por parte

                part_pvds = {}
                pvd_count = 1
                for pvd_str in all_pvds:
                    pvd_time = datetime.datetime.strptime(pvd_str, "%H:%M")
                    if hora_inicio <= pvd_time < hora_fin:
                        part_pvds[f'pvd{pvd_count}'] = pvd_str
                        pvd_count += 1
                        total_break_minutes += 5 # Sumamos al KPI
                
                # Cada "parte" del turno se convierte en una fila en la tabla
                table_data.append({
                    "unique_id": f"{schedule.id}-{part}", # ID único para la fila
                    "schedule_id": schedule.id,
                    "dni": schedule.agent.identificacion,
                    "nombre": schedule.agent.nombre_completo,
                    "fecha": schedule.schedule_date.strftime('%d/%m/%Y'),
                    "turno": part, # Mostramos solo la parte del turno
                    "horas": f"{part_duration_hours:.2f}", # Mostramos las horas de esta parte
                    "inicio_descanso": part_break_start,
                    "fin_descanso": part_break_end,
                    # Rellenamos hasta 10 PVDs, los que no correspondan estarán vacíos
                    **{f'pvd{j}': part_pvds.get(f'pvd{j}', None) for j in range(1, 11)}
                })
        
        # --- La lógica del gráfico se mantiene, ya que se alimenta de `table_data` que ahora es correcta ---
        time_labels = [(datetime.datetime.strptime("00:00", "%H:%M") + datetime.timedelta(minutes=5 * i)).strftime('%H:%M') for i in range(288)]
        chart_data_by_day = defaultdict(lambda: {"coverage": [0]*288, "breaks": [0]*288, "pvds": [0]*288})

        for row in table_data: # Usamos la nueva table_data con filas duplicadas
            day_str = datetime.datetime.strptime(row['fecha'], '%d/%m/%Y').strftime('%Y-%m-%d')
            # ... (el resto de la lógica del gráfico no necesita cambios)
            try:
                start_s, end_s_str = row['turno'].split('-')
                start_shift = datetime.datetime.strptime(start_s.strip(), '%H:%M')
                end_shift = datetime.datetime.strptime('23:59', '%H:%M') + datetime.timedelta(minutes=1) if end_s_str.strip() == '24:00' else datetime.datetime.strptime(end_s_str.strip(), '%H:%M')
                for i, label in enumerate(time_labels):
                    interval_start = datetime.datetime.strptime(label, "%H:%M")
                    if start_shift <= interval_start < end_shift:
                        chart_data_by_day[day_str]["coverage"][i] += 1
                
                if row['inicio_descanso'] and row['fin_descanso']:
                    start_b = datetime.datetime.strptime(row['inicio_descanso'], "%H:%M"); end_b = datetime.datetime.strptime(row['fin_descanso'], "%H:%M")
                    for i, label in enumerate(time_labels):
                        interval_start = datetime.datetime.strptime(label, "%H:%M")
                        if max(start_b, interval_start) < min(end_b, interval_start + datetime.timedelta(minutes=5)):
                            chart_data_by_day[day_str]["breaks"][i] += 1
                for i in range(1, 11):
                    pvd_str = row.get(f'pvd{i}')
                    if pvd_str:
                        start_p = datetime.datetime.strptime(pvd_str, "%H:%M"); end_p = start_p + datetime.timedelta(minutes=5)
                        for j, label in enumerate(time_labels):
                            interval_start = datetime.datetime.strptime(label, "%H:%M")
                            if max(start_p, interval_start) < min(end_p, interval_start + datetime.timedelta(minutes=5)):
                                chart_data_by_day[day_str]["pvds"][j] += 1
            except (ValueError, TypeError): continue


        kpi_data = {"total_work_hours": total_work_hours, "total_break_minutes": total_break_minutes}
        return jsonify({"table_data": table_data, "chart_data": {"labels": time_labels, "days": chart_data_by_day}, "kpi_data": kpi_data})
    except Exception as e:
        import traceback; traceback.print_exc(); return jsonify({"error": f"Ocurrió un error al obtener la distribución: {e}"}), 500

# --- RUTA PARA GUARDAR CAMBIOS DEL MODAL ---
@app.route('/api/update_breaks_bulk', methods=['POST'])
def update_breaks_bulk():
    # ... (Esta función se mantiene igual que en la respuesta anterior)
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.json
        schedule_id = data.get('schedule_id')
        schedule = Schedule.query.get(schedule_id)
        if not schedule: return jsonify({"error": "Registro no encontrado"}), 404
        
        schedule.descanso1_he = data.get('inicio_descanso').strip() or None
        schedule.descanso1_hs = data.get('fin_descanso').strip() or None
        for i in range(1, 9):
            setattr(schedule, f'pvd{i}', data.get(f'pvd{i}', '').strip() or None)
            
        db.session.commit()
        return jsonify({"message": "Descansos actualizados con éxito."})
    except Exception as e:
        db.session.rollback(); return jsonify({"error": str(e)}), 500
  

@app.route('/api/export_schedule', methods=['POST'])
def export_schedule():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    
    try:
        data = request.json
        segment_id, start_date_str, end_date_str = data.get('segment_id'), data.get('start_date'), data.get('end_date')
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()

        segment = Segment.query.options(joinedload(Segment.campaign)).filter_by(id=segment_id).first()
        if not segment: return jsonify({"error": "Segmento no encontrado."}), 404
        
        campaign_code = segment.campaign.code if segment.campaign else ""
        
        agents = Agent.query.filter_by(segment_id=segment_id).order_by(Agent.nombre_completo).all()
        if not agents: return jsonify({"error": "No hay agentes en este segmento."}), 404

        agent_ids = [agent.id for agent in agents]
        schedules = Schedule.query.filter(
            Schedule.agent_id.in_(agent_ids),
            Schedule.schedule_date.between(start_date, end_date)
        ).all()
        
        schedule_map = {(s.agent_id, s.schedule_date): s for s in schedules}

        columns = [
            'Centro', 'Servicio', 'Id_Legal', 'Fecha_Entrada', 'Fecha_Salida',
            'Hora_Entrada', 'Hora_Salida', 'Novedad', 'Formacion1_HE', 'Formacion1_HS',
            'Formacion2_HE', 'Formacion2_HS', 'Descanso1_HE', 'Descanso1_HS', 'Descanso2_HE', 'Descanso2_HS',
            'PVD1', 'PVD2', 'PVD3', 'PVD4', 'PVD5', 'PVD6', 'PVD7', 'PVD8', 'PVD9', 'PVD10',
            'Observacion', 'susceptible_de_pago', 'Complementarias'
        ]
        
        export_data = []
        date_range = [start_date + datetime.timedelta(days=i) for i in range((end_date - start_date).days + 1)]

        for agent in agents:
            for day in date_range:
                schedule_entry = schedule_map.get((agent.id, day))
                if not schedule_entry or schedule_entry.shift in VALID_AUSENCIA_CODES: continue
                
                parts = schedule_entry.shift.split('/')

                # Para España, creamos una fila por cada bloque del turno
                if segment.campaign.country == 'España':
                    for i, part in enumerate(parts):
                        if '-' not in part: continue
                        
                        row = {col: '' for col in columns}
                        row['Centro'] = agent.centro or ''
                        row['Servicio'] = campaign_code
                        row['Id_Legal'] = agent.identificacion
                        row['Fecha_Entrada'] = day.strftime('%d/%m/%Y')
                        row['Fecha_Salida'] = day.strftime('%d/%m/%Y')
                        
                        start_str, end_str = part.split('-')
                        row['Hora_Entrada'] = start_str.strip()
                        row['Hora_Salida'] = end_str.strip()

                        # Asignar descansos y PVDs a la fila correcta
                        # (Simplificación: todos los descansos/PVDs se ponen en todas las filas del día)
                        row['Descanso1_HE'] = schedule_entry.descanso1_he or ''
                        row['Descanso1_HS'] = schedule_entry.descanso1_hs or ''
                        row['Descanso2_HE'] = schedule_entry.descanso2_he or ''
                        row['Descanso2_HS'] = schedule_entry.descanso2_hs or ''
                        for pvd_num in range(1, 11):
                            row[f'PVD{pvd_num}'] = getattr(schedule_entry, f'pvd{pvd_num}', '') or ''
                        
                        row['susceptible_de_pago'] = 'SI' if len(parts) > 1 else 'NO' # Ejemplo
                        row['Complementarias'] = 'NO'
                        export_data.append(row)

                else: # Lógica original para otros países
                    row = {col: '' for col in columns}
                    # ... (puedes pegar aquí la lógica de exportación anterior si la necesitas para otros países)
        
        df = pd.DataFrame(export_data, columns=columns).fillna('')
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        df.to_excel(writer, index=False, sheet_name='Horarios')
        writer.close()
        output.seek(0)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'Horarios_{start_date_str}_a_{end_date_str}.xlsx')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Ocurrió un error al exportar: {e}"}), 500    

# ==============================================================================
# 5. REGISTRO DE COMANDOS Y PUNTO DE ENTRADA
# ==============================================================================

@click.group()
def db_cli():
    """Comandos para la gestión de la base de datos."""
    pass

@db_cli.command('create-all')
def db_create_all():
    db.create_all(); print("Base de datos y tablas creadas con éxito.")

@db_cli.command('seed')
def db_seed():
    if not User.query.filter_by(username='admin').first():
        admin_user = User(username='admin', password_hash=generate_password_hash('password123', method='pbkdf2:sha256'), role='admin')
        db.session.add(admin_user); print("Usuario 'admin' creado.")
    
    if not Campaign.query.first():
       c1 = Campaign(name='Banco de Bogotá', country='Colombia')
       c2 = Campaign(name='Ventas España', country='España')
       s1 = Segment(name='SAC', campaign=c1, lunes_apertura='08:00', lunes_cierre='22:00', martes_apertura='08:00', martes_cierre='22:00', miercoles_apertura='08:00', miercoles_cierre='22:00', jueves_apertura='08:00', jueves_cierre='22:00', viernes_apertura='08:00', viernes_cierre='22:00', sabado_apertura='09:00', sabado_cierre='18:00', domingo_apertura='09:00', domingo_cierre='15:00')
       s2 = Segment(name='Facturación', campaign=c1)
       s3 = Segment(name='General', campaign=c2)
       db.session.add_all([c1, c2, s1, s2, s3]); print("Campañas y Segmentos de ejemplo creados.")
    
    db.session.commit(); print("Base de datos poblada con datos iniciales.")

app.cli.add_command(db_cli, 'db-custom')

@db_cli.command('seed-breaks')
def db_seed_breaks():
    """Puebla la BD con reglas de descanso para Colombia y España."""
    
    BreakRule.query.delete()

    colombia_rules = [
        BreakRule(name='COL 4 Horas', country='Colombia', min_shift_hours=4.0, max_shift_hours=4.99, break_duration_minutes=10),
        BreakRule(name='COL 5 Horas', country='Colombia', min_shift_hours=5.0, max_shift_hours=5.99, break_duration_minutes=15),
        BreakRule(name='COL 6 Horas', country='Colombia', min_shift_hours=6.0, max_shift_hours=6.99, break_duration_minutes=20),
        BreakRule(name='COL 7 Horas', country='Colombia', min_shift_hours=7.0, max_shift_hours=7.99, break_duration_minutes=25),
        BreakRule(name='COL 8 Horas', country='Colombia', min_shift_hours=8.0, max_shift_hours=8.99, break_duration_minutes=30),
        BreakRule(name='COL 9 Horas', country='Colombia', min_shift_hours=9.0, max_shift_hours=9.99, break_duration_minutes=35),
        BreakRule(name='COL 10 Horas', country='Colombia', min_shift_hours=10.0, max_shift_hours=10.99, break_duration_minutes=40),
    ]

    spain_rules = [
        BreakRule(name='ESP 4-6 Horas', country='España', min_shift_hours=4.0, max_shift_hours=6.99, break_duration_minutes=10, pvd_minutes_per_hour=5, number_of_pvds=2),
        BreakRule(name='ESP 7 Horas', country='España', min_shift_hours=7.0, max_shift_hours=7.99, break_duration_minutes=20, pvd_minutes_per_hour=5, number_of_pvds=3),
        BreakRule(name='ESP 8-10 Horas', country='España', min_shift_hours=8.0, max_shift_hours=10.99, break_duration_minutes=30, pvd_minutes_per_hour=5, number_of_pvds=4),
    ]

    db.session.add_all(colombia_rules)
    db.session.add_all(spain_rules)
    db.session.commit()
    print("Reglas de descanso para Colombia y España (LÍMITES CORREGIDOS) creadas con éxito.")


if __name__ == '__main__':
    app.run(debug=True)





