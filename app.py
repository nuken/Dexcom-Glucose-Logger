import os
import sqlite3
import time
import csv 
import io  
import json
import re
import requests
import math  # <--- NEW IMPORT
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, Response 
from pydexcom import Dexcom

app = Flask(__name__)

# CONFIGURATION
DEXCOM_USER = os.environ.get('DEXCOM_USER')
DEXCOM_PASS = os.environ.get('DEXCOM_PASS')
IS_OUS = os.environ.get('DEXCOM_OUS', 'False').lower() == 'true'
DEXCOM_REGION = "ous" if IS_OUS else "us"
DB_FILE = "/app/data/glucose.db"

# USDA Configuration
USDA_API_KEY = os.environ.get('USDA_API_KEY', 'DEMO_KEY')
if USDA_API_KEY == 'your_key_here' or not USDA_API_KEY:
    USDA_API_KEY = 'DEMO_KEY'

last_sync_time = 0
SYNC_COOLDOWN = 60 # Check at most once per minute

# --- HELPER: TIME PARSING ---
def parse_db_time(time_val):
    if isinstance(time_val, datetime): return time_val
    if not isinstance(time_val, str): return datetime.now()
    
    match = re.match(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?([+-]\d{2}:?\d{2}|Z)?', time_val)
    if match:
        date_part, time_part, micro_part, tz_part = match.groups()
        iso_str = f"{date_part}T{time_part}"
        if micro_part: iso_str += f".{micro_part}"
        if tz_part:
            if len(tz_part) == 5 and tz_part != 'Z' and ':' not in tz_part:
                tz_part = tz_part[:3] + ':' + tz_part[3:]
            iso_str += tz_part
        try: return datetime.fromisoformat(iso_str)
        except: pass

    try:
        clean_time = time_val.split('.')[0].split('+')[0].split('-')[0]
        return datetime.strptime(clean_time.strip(), '%Y-%m-%d %H:%M:%S')
    except:
        return datetime.now()

# --- DATABASE ---
def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS readings (
            time_str TEXT PRIMARY KEY, timestamp DATETIME, mg_dl INTEGER, trend TEXT, trend_arrow TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME, meal_type TEXT, items TEXT, carbs INTEGER, notes TEXT)''')

def save_readings_to_db(readings):
    if not readings: return
    with sqlite3.connect(DB_FILE) as conn:
        for r in readings:
            t_str = r.datetime.strftime('%Y-%m-%d %H:%M:%S')
            try:
                conn.execute("INSERT OR IGNORE INTO readings (time_str, timestamp, mg_dl, trend, trend_arrow) VALUES (?, ?, ?, ?, ?)",
                    (t_str, r.datetime, r.value, r.trend_description, r.trend_arrow))
            except: pass

def get_last_reading_time():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("SELECT timestamp FROM readings ORDER BY timestamp DESC LIMIT 1").fetchone()
            if row:
                return parse_db_time(row[0])
    except: pass
    return None

# --- SYNC LOGIC ---
def smart_sync():
    global last_sync_time
    
    # 1. Rate Limit (In-Memory)
    if time.time() - last_sync_time < SYNC_COOLDOWN:
        return

    try:
        print("Checking Dexcom sync...")
        last_db_time = get_last_reading_time()
        
        if not last_db_time:
            # FIX: Dexcom API limit is 1440 minutes (24 hours) per request
            minutes_to_fetch = 1440 
        else:
            now = datetime.now()
            last_naive = last_db_time.replace(tzinfo=None) if last_db_time.tzinfo else last_db_time
            gap_minutes = (now - last_naive).total_seconds() / 60
            
            if gap_minutes < 5: 
                print("Data is up to date.")
                last_sync_time = time.time()
                return 
            
            minutes_to_fetch = min(int(gap_minutes) + 20, 1440)

        print(f"Connecting to Dexcom (Lookback: {minutes_to_fetch}m)...")
        dexcom = Dexcom(username=DEXCOM_USER, password=DEXCOM_PASS, region=DEXCOM_REGION)
        readings = dexcom.get_glucose_readings(minutes=minutes_to_fetch)
        save_readings_to_db(readings)
        last_sync_time = time.time()
        print(f"Sync complete. Saved {len(readings) if readings else 0} readings.")
        
    except Exception as e:
        print(f"Sync Failed: {e}")

try:
    init_db()
except: pass

# --- ROUTES ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/trends')
def trends(): return render_template('trends.html')

@app.route('/add-meal')
def add_meal_page(): return render_template('add_meal.html')

@app.route('/edit-meal/<int:meal_id>')
def edit_meal_page(meal_id):
    return render_template('edit_meal.html', meal_id=meal_id)

@app.route('/meals')
def meals_page(): return render_template('meals.html')

# --- MEAL API ---

@app.route('/api/meals', methods=['GET', 'POST'])
def handle_meals():
    if request.method == 'POST':
        try:
            data = request.json
            dt = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
            items_json = json.dumps(data.get('items', []))
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute("INSERT INTO meals (timestamp, meal_type, items, carbs, notes) VALUES (?, ?, ?, ?, ?)",
                    (dt, data['meal_type'], items_json, data.get('carbs'), data.get('notes')))
            return jsonify({'success': True})
        except Exception as e: return jsonify({'error': str(e)}), 500
    else:
        try:
            meals_data = []
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM meals ORDER BY timestamp DESC")
                meals = cursor.fetchall()
                for meal in meals:
                    meal_time = parse_db_time(meal['timestamp'])
                    if meal_time.tzinfo is not None: meal_time = meal_time.replace(tzinfo=None)
                    end_window = meal_time + timedelta(hours=2)
                    
                    cursor.execute("SELECT mg_dl, timestamp FROM readings WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC", (meal_time, end_window))
                    window_readings = cursor.fetchall()
                    
                    start_glucose = window_readings[0]['mg_dl'] if window_readings else None
                    peak_glucose = max((r['mg_dl'] for r in window_readings), default=None)
                    rise = (peak_glucose - start_glucose) if (peak_glucose and start_glucose) else 0
                    
                    timeline = []
                    checkpoints = [0, 30, 60, 90, 120]
                    if window_readings:
                        readings_processed = []
                        for r in window_readings:
                            rt = parse_db_time(r['timestamp'])
                            if rt.tzinfo is not None: rt = rt.replace(tzinfo=None)
                            readings_processed.append({'time': rt, 'val': r['mg_dl']})
                        for cp in checkpoints:
                            target_time = meal_time + timedelta(minutes=cp)
                            closest_val = None
                            min_diff = 300
                            for r in readings_processed:
                                diff = abs((r['time'] - target_time).total_seconds())
                                if diff < min_diff: min_diff = diff; closest_val = r['val']
                            timeline.append({'min': cp, 'val': closest_val if closest_val else '-'})

                    meals_data.append({
                        'id': meal['id'],
                        'time_str': meal_time.strftime('%b %d, %-I:%M %p'),
                        'timestamp': meal['timestamp'],
                        'type': meal['meal_type'],
                        'items': json.loads(meal['items']),
                        'carbs': meal['carbs'],
                        'notes': meal['notes'],
                        'analysis': {'start': start_glucose, 'peak': peak_glucose, 'rise': rise, 'timeline': timeline}
                    })
            return jsonify(meals_data)
        except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/meals/<int:meal_id>', methods=['GET', 'PUT', 'DELETE'])
def single_meal_ops(meal_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        if request.method == 'GET':
            row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
            if not row: return jsonify({'error': 'Not found'}), 404
            return jsonify(dict(row))
            
        if request.method == 'DELETE':
            conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
            return jsonify({'success': True})
            
        if request.method == 'PUT':
            data = request.json
            dt = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
            items_json = json.dumps(data.get('items', []))
            conn.execute("""
                UPDATE meals SET timestamp=?, meal_type=?, items=?, carbs=?, notes=?
                WHERE id=?
            """, (dt, data['meal_type'], items_json, data.get('carbs'), data.get('notes'), meal_id))
            return jsonify({'success': True})

@app.route('/api/calculate-carbs', methods=['POST'])
def calculate_carbs():
    items = request.json.get('items', [])
    total_carbs = 0
    using_demo = (USDA_API_KEY == 'DEMO_KEY')
    
    for item in items:
        url = f"https://api.nal.usda.gov/fdc/v1/foods/search?api_key={USDA_API_KEY}&query={item}&pageSize=1"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 429:
                return jsonify({'error': 'Rate limit exceeded. Please get a free API key at fdc.nal.usda.gov'}), 429
            
            data = r.json()
            if data.get('foods'):
                food = data['foods'][0]
                nutrients = food.get('foodNutrients', [])
                carb_val = 0
                for n in nutrients:
                    if "Carbohydrate" in n.get('nutrientName', ''):
                        carb_val = n.get('value', 0)
                        break
                total_carbs += carb_val
        except Exception as e:
            print(f"Error looking up {item}: {e}")
            continue
            
    return jsonify({
        # Round up to the nearest whole number for safer bolusing
        'total_carbs': int(math.ceil(total_carbs)), 
        'is_demo': using_demo
    })

@app.route('/api/readings')
def get_readings():
    smart_sync()
        
    try:
        step = int(request.args.get('step', 1))
        minutes = int(request.args.get('minutes', 1440))
        target_interval = 0 if step == 1 else (step * 5)
        
        cutoff = datetime.now() - timedelta(minutes=minutes)
        
        data = []
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT time_str, mg_dl, trend, trend_arrow FROM readings WHERE timestamp > ? ORDER BY timestamp DESC", (cutoff,))
            
            last_kept = None
            for row in cursor.fetchall():
                dt = parse_db_time(row[0])
                if step == 1 or last_kept is None or (last_kept - dt).total_seconds()/60 >= target_interval:
                    last_kept = dt
                    data.append({'timestamp': row[0], 'time': dt.strftime('%b %d, %Y %-I:%M %p'), 'mg_dl': row[1], 'trend': row[2], 'trend_arrow': row[3]})
        return jsonify(data)
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/export/health')
def export_health_csv():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("SELECT time_str, mg_dl, trend FROM readings ORDER BY timestamp ASC").fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Index', 'Timestamp (YYYY-MM-DDThh:mm:ss)', 'Glucose Value (mg/dL)', 'Trend'])
        for i, row in enumerate(rows): writer.writerow([i, row[0].replace(" ", "T"), row[1], row[2]])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=dexcom_health_export.csv"})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/export/meals')
def export_meals_csv():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM meals ORDER BY timestamp ASC").fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Timestamp', 'Type', 'Items', 'Carbs', 'Notes'])
        for row in rows:
            items = ", ".join(json.loads(row['items']))
            writer.writerow([row['timestamp'], row['meal_type'], items, row['carbs'], row['notes']])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=meal_history.csv"})
    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)