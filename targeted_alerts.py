import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# --- FILE PATHS ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'targets.json')
STATE_FILE = os.path.join(SCRIPT_DIR, 'sniper_state.json')
LOG_FILE = os.path.join(SCRIPT_DIR, 'sniper_log.txt')

# Discord Webhook URLs (Pulled from GitHub Secrets)
WEBHOOK_SUCCESS_FAIL = os.environ.get('WEBHOOK_SUCCESS_FAIL')
WEBHOOK_FAIL = os.environ.get('WEBHOOK_FAIL')
WEBHOOK_STATUS_REPORT = os.environ.get('WEBHOOK_STATUS_REPORT')
WEBHOOK_SEAT_STALKER = os.environ.get('WEBHOOK_SEAT_STALKER')

# --- UTILITY FUNCTIONS ---
def send_discord(webhook_url, message):
    if webhook_url:
        try:
            requests.post(webhook_url, json={"content": message})
        except Exception:
            pass

def write_log(message):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{message}\n")
    print(message)

def load_config():
    """Loads the external targets.json file."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Config file not found at {CONFIG_FILE}")
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

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
    status_lines = []
    run_success = True
    error_msg = ""
    
    # Placeholders for config values
    TERM = ""
    PINGS = {}
    TARGETS = {}

    try:
        # 1. Load External Configuration
        config = load_config()
        TERM = config.get("TERM", "202608")
        PINGS = config.get("PINGS", {})
        TARGETS = config.get("TARGETS", {})
        
        SECTIONS_URL = f"https://app.testudo.umd.edu/soc/{TERM}/sections?courseIds="
        HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        
        prev_state = load_previous_state()
        current_state = {}

        for course_id, course_config in TARGETS.items():
            ajax_url = f"{SECTIONS_URL}{course_id}"
            response = requests.get(ajax_url, headers=HEADERS)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            sections = soup.find_all('div', class_='section')
            current_state[course_id] = {}
            
            for section in sections:
                section_id = section.find('span', class_='section-id').text.strip()
                open_seats_str = section.find('span', class_='open-seats-count').text.strip()
                open_seats = int(open_seats_str) if open_seats_str.isdigit() else 0
                current_state[course_id][section_id] = open_seats
                
            # Individual Sections
            for sec_id, sec_config in course_config.get("sections", {}).items():
                curr_seats = current_state[course_id].get(sec_id)
                if curr_seats is not None:
                    status_lines.append(f"• **{course_id} {sec_id}:** {curr_seats} seats")
                    prev_seats = prev_state.get(course_id, {}).get(sec_id, float('inf'))
                    threshold = sec_config["threshold"]
                    
                    if curr_seats <= threshold and prev_seats > threshold:
                        msg = f"🚨 **SEAT DROP!** {course_id} (Sec {sec_id}) hit **{curr_seats}** seats! (Threshold: {threshold})\n*(Retrieved at: {fetch_time})*\n{PINGS.get('SEAT_DROP', '')}"
                        write_log(msg)
                        send_discord(WEBHOOK_SEAT_STALKER, msg)

            # Combinations
            for combo in course_config.get("combinations", []):
                sections_in_combo = combo["sections"]
                threshold = combo["threshold"]
                combo_name = combo.get("name", "Combo")
                curr_sum = sum([current_state[course_id].get(s, 0) for s in sections_in_combo if s in current_state[course_id]])
                prev_sum = sum([prev_state.get(course_id, {}).get(s, 0) for s in sections_in_combo]) if prev_state.get(course_id) else float('inf')
                
                status_lines.append(f"• **{combo_name} Total:** {curr_sum} seats")
                
                if curr_sum <= threshold and prev_sum > threshold:
                    msg = f"🚨 **COMBO DROP!** {combo_name} hit **{curr_sum}** total seats! (Threshold: {threshold})\n*(Retrieved at: {fetch_time})*\n{PINGS.get('SEAT_DROP', '')}"
                    write_log(msg)
                    send_discord(WEBHOOK_SEAT_STALKER, msg)

        save_current_state(current_state)

    except Exception as e:
        run_success = False
        error_msg = str(e)
        write_log(f"[{fetch_time}] ERROR: {error_msg}")
            
    # --- FINAL REPORTING ---
    report_body = "\n".join(status_lines) if status_lines else "No seat data retrieved."
    
    if run_success:
        base_msg = f"✅ Run Successful at {fetch_time}"
        send_discord(WEBHOOK_SUCCESS_FAIL, base_msg)
        send_discord(WEBHOOK_STATUS_REPORT, f"{base_msg}\n\n**Current Status:**\n{report_body}\n\n{PINGS.get('STATUS_REPORT', '')}")
    else:
        base_msg = f"❌ Run Failed at {fetch_time}\n**Error:** {error_msg}"
        send_discord(WEBHOOK_SUCCESS_FAIL, base_msg)
        send_discord(WEBHOOK_FAIL, f"{base_msg}\n\n{PINGS.get('FAIL_ALARM', '')}")
        send_discord(WEBHOOK_STATUS_REPORT, f"{base_msg}\n\n**Partial Status:**\n{report_body}\n\n{PINGS.get('STATUS_REPORT', '')}")

if __name__ == "__main__":
    run_sniper()
