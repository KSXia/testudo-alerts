import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# --- CONFIGURATION ---
TERM = "202608" 

# Discord Webhook URLs (Pulled from GitHub Secrets)
WEBHOOK_SUCCESS_FAIL = os.environ.get('WEBHOOK_SUCCESS_FAIL')
WEBHOOK_FAIL = os.environ.get('WEBHOOK_FAIL')
WEBHOOK_STATUS_REPORT = os.environ.get('WEBHOOK_STATUS_REPORT')
WEBHOOK_SEAT_STALKER = os.environ.get('WEBHOOK_SEAT_STALKER')

# Discord Role IDs for Pings
ROLE_PING = "<@&1499095743024074883>" # For critical seat drops
STATUS_PING = "<@&1499097068386648195>" # For status reports
FAIL_PING = "<@&1499097740578128054>" # For script crashes/failures

# Target Configuration (Continuous logic removed for strict single-trigger)
TARGETS = {
    "STAT400": {
        "sections": {
            "0221": {"threshold": 10},
            "0222": {"threshold": 15}
        },
        "combinations": [
            {"name": "0221 + 0222 Combo", "sections": ["0221", "0222"], "threshold": 15}
        ]
    }
}

# --- FILE PATHS ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, 'sniper_state.json')
LOG_FILE = os.path.join(SCRIPT_DIR, 'sniper_log.txt')

SECTIONS_URL = f"https://app.testudo.umd.edu/soc/{TERM}/sections?courseIds="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest" 
}

# --- UTILITY FUNCTIONS ---
def send_discord(webhook_url, message):
    """Quietly sends a message to a designated Discord webhook."""
    if webhook_url:
        try:
            requests.post(webhook_url, json={"content": message})
        except Exception:
            pass # Fail silently so the script doesn't crash if Discord is down

def write_log(message):
    """Writes a message strictly to the local text file."""
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{message}\n")
    print(message)

def load_previous_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_current_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

# --- CORE LOGIC ---
def run_sniper():
    fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prev_state = load_previous_state()
    current_state = {}
    status_lines = []
    
    run_success = True
    error_msg = ""
    
    try:
        for course_id, config in TARGETS.items():
            ajax_url = f"{SECTIONS_URL}{course_id}"
            response = requests.get(ajax_url, headers=HEADERS)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            sections = soup.find_all('div', class_='section')
            current_state[course_id] = {}
            
            # Parse all sections
            for section in sections:
                section_id = section.find('span', class_='section-id').text.strip()
                open_seats_str = section.find('span', class_='open-seats-count').text.strip()
                open_seats = int(open_seats_str) if open_seats_str.isdigit() else 0
                current_state[course_id][section_id] = open_seats
                
            # Evaluate Individual Sections
            for sec_id, sec_config in config.get("sections", {}).items():
                curr_seats = current_state[course_id].get(sec_id)
                
                if curr_seats is not None:
                    status_lines.append(f"• **{course_id} {sec_id}:** {curr_seats} seats")
                    
                    prev_seats = prev_state.get(course_id, {}).get(sec_id, float('inf'))
                    threshold = sec_config["threshold"]
                    
                    # Triggers ONLY when crossing the threshold for the first time
                    if curr_seats <= threshold and prev_seats > threshold:
                        msg = f"🚨 **SEAT DROP!** {course_id} (Sec {sec_id}) hit **{curr_seats}** seats! (Threshold: {threshold})\n*(Retrieved at: {fetch_time})*\n{ROLE_PING}"
                        write_log(msg)
                        send_discord(WEBHOOK_SEAT_STALKER, msg)

            # Evaluate Combinations
            for combo in config.get("combinations", []):
                sections_in_combo = combo["sections"]
                threshold = combo["threshold"]
                combo_name = combo.get("name", "Combo")
                
                curr_sum = sum([current_state[course_id].get(s, 0) for s in sections_in_combo if s in current_state[course_id]])
                
                if not prev_state.get(course_id):
                    prev_sum = float('inf')
                else:
                    prev_sum = sum([prev_state[course_id].get(s, 0) for s in sections_in_combo if s in prev_state[course_id]])
                
                status_lines.append(f"• **{combo_name} Total:** {curr_sum} seats")
                
                if curr_sum <= threshold and prev_sum > threshold:
                    msg = f"🚨 **COMBO DROP!** {combo_name} hit **{curr_sum}** total seats! (Threshold: {threshold})\n*(Retrieved at: {fetch_time})*\n{ROLE_PING}"
                    write_log(msg)
                    send_discord(WEBHOOK_SEAT_STALKER, msg)

    except Exception as e:
        run_success = False
        error_msg = str(e)
        write_log(f"[{fetch_time}] ERROR: {error_msg}")
            
    # Overwrite the JSON file with the new seat counts
    save_current_state(current_state)
    
    # --- ROUTE FINAL LOG MESSAGES ---
    report_body = "\n".join(status_lines) if status_lines else "No seat data retrieved."
    
    if run_success:
        base_msg = f"✅ Run Successful at {fetch_time}"
        send_discord(WEBHOOK_SUCCESS_FAIL, base_msg)
        send_discord(WEBHOOK_STATUS_REPORT, f"{base_msg}\n\n**Current Status:**\n{report_body}\n\n{STATUS_PING}")
    else:
        base_msg = f"❌ Run Failed at {fetch_time}\n**Error:** {error_msg}"
        send_discord(WEBHOOK_SUCCESS_FAIL, base_msg)
        
        # APPENDED FAIL PING ONLY TO THE FAIL CHANNEL MESSAGE
        send_discord(WEBHOOK_FAIL, f"{base_msg}\n\n{FAIL_PING}")
        
        send_discord(WEBHOOK_STATUS_REPORT, f"{base_msg}\n\n**Partial Status (before crash):**\n{report_body}\n\n{STATUS_PING}")

if __name__ == "__main__":
    print("Running targeted sniper check...")
    run_sniper()
    print("Check complete. State saved.")
