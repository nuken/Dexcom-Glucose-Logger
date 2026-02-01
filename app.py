import os
import sqlite3
import threading
import time
import csv 
import io  
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

# GLOBAL STATE
# We use this to prevent spamming Dexcom logins
last_sync_time = 0
SYNC_COOLDOWN = 300  # 5 Minutes (in seconds)

# --- DATABASE FUNCTIONS ---
def init_db():
    # Ensure the folder exists before creating the DB file
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS readings (
                time_str TEXT PRIMARY KEY,
                timestamp DATETIME,
                mg_dl INTEGER,
                trend TEXT,
                trend_arrow TEXT
            )
        ''')

def save_readings_to_db(readings):
    if not readings:
        return
    with sqlite3.connect(DB_FILE) as conn:
        for r in readings:
            t_str = r.datetime.strftime('%Y-%m-%d %H:%M:%S')
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO readings (time_str, timestamp, mg_dl, trend, trend_arrow) VALUES (?, ?, ?, ?, ?)",
                    (t_str, r.datetime, r.value, r.trend_description, r.trend_arrow)
                )
            except Exception as e:
                print(f"DB Error: {e}")

# --- SYNC FUNCTION (Shared) ---
def perform_dexcom_sync(minutes=1440):
    """Handles the actual connection to Dexcom."""
    global last_sync_time
    try:
        print(f"Connecting to Dexcom (Lookback: {minutes}m)...")
        dexcom = Dexcom(
            username=DEXCOM_USER, 
            password=DEXCOM_PASS, 
            region=DEXCOM_REGION
        )
        readings = dexcom.get_glucose_readings(minutes=minutes)
        save_readings_to_db(readings)
        
        # Update the timestamp so we know we just synced
        last_sync_time = time.time()
        return True
    except Exception as e:
        print(f"Sync Failed: {e}")
        return False

# --- BACKGROUND SYNC ---
def background_sync():
    """Runs every 30 minutes to fetch data."""
    while True:
        perform_dexcom_sync(minutes=1440)
        time.sleep(1800)

try:
    init_db()
    threading.Thread(target=background_sync, daemon=True).start()
except Exception as e:
    print(f"Startup Error: {e}")

# --- WEB ROUTES ---
@app.route('/api/export/health')
def export_health_csv():
    """Generates a CSV formatted for medical app imports (Dexcom Clarity style)."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Medical apps prefer chronological order (ASC)
            cursor.execute("SELECT time_str, mg_dl, trend FROM readings ORDER BY timestamp ASC")
            rows = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Standard headers recognized by Glooko/Tidepool parsers
        writer.writerow(['Index', 'Timestamp (YYYY-MM-DDThh:mm:ss)', 'Glucose Value (mg/dL)', 'Trend'])
        
        for i, row in enumerate(rows):
            # Convert 'YYYY-MM-DD HH:MM:SS' to ISO 8601 'YYYY-MM-DDTHH:MM:SS'
            iso_time = row[0].replace(" ", "T")
            writer.writerow([i, iso_time, row[1], row[2]])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=dexcom_health_export.csv"}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/readings')
def get_readings():
    # --- RATE LIMIT PROTECTION ---
    # Only "Live Sync" if it has been more than 5 minutes since the last sync
    global last_sync_time
    time_since_last_sync = time.time() - last_sync_time
    
    if time_since_last_sync > SYNC_COOLDOWN:
        print("Live sync triggered (Cooldown expired)")
        perform_dexcom_sync(minutes=40)
    else:
        print(f"Skipping live sync (Recently synced {int(time_since_last_sync)}s ago)")

    # 2. Query & Filter Data (Same as before)
    try:
        step = int(request.args.get('step', 1))
        minutes_back = int(request.args.get('minutes', 1440))
        target_interval = 0 if step == 1 else (step * 5)
        cutoff = datetime.now() - timedelta(minutes=minutes_back)
        
        data = []
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT time_str, mg_dl, trend, trend_arrow FROM readings WHERE timestamp > ? ORDER BY timestamp DESC", (cutoff,))
            rows = cursor.fetchall()
            
            last_kept_time = None
            for row in rows:
                dt = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                keep_row = False
                if step == 1:
                    keep_row = True
                elif last_kept_time is None:
                    keep_row = True
                else:
                    diff_mins = (last_kept_time - dt).total_seconds() / 60
                    if diff_mins >= target_interval:
                        keep_row = True
                
                if keep_row:
                    last_kept_time = dt
                    friendly_time = dt.strftime('%b %d, %Y %-I:%M %p').replace('AM', 'am').replace('PM', 'pm')
                    data.append({
                        'timestamp': row[0],
                        'time': friendly_time,
                        'mg_dl': row[1],
                        'trend': row[2],
                        'trend_arrow': row[3]
                    })
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':

    app.run(host='0.0.0.0', port=5000)

