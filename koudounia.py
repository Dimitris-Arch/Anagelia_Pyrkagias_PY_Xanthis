#!/usr/bin/env python3
import RPi.GPIO as GPIO
import os
import time
import threading
import subprocess
import logging
from gtts import gTTS
from datetime import datetime, time as dt_time

# ---------------- VOLUME CONTROL ----------------
def set_volume_93():
    """FORCE 93% πριν κάθε ήχο"""
    try:
        subprocess.run(["amixer", "sset", "Speaker", "93%"], 
                      capture_output=True, check=True)
        subprocess.run(["amixer", "sset", "Mic", "93%"], 
                      capture_output=True, check=True)
        logger.info("🔊 Volume → 93%")
    except:
        logger.warning("Volume set skip")

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info("=== Ξεκινάει το Koudounia ===")

# ---------------- GPIO ----------------
GPIO.setmode(GPIO.BCM)
astiki_btn = 5
asanser_btn = 6
troxaio_btn = 13
dasiki_btn = 19
mic_btn = 26
relay1 = 17
relay2 = 27
led_red = 16
led_blue = 20
led_running = 12

# --------- ΚΑΤΑΣΤΑΣΕΙΣ ---------
relay1_manual_on = False
daytime_forced_on = False
alarm_event = threading.Event()

# --------- ΩΡΑΡΙΟ RELAY1 ---------
DAY_START = dt_time(7, 30)
DAY_END = dt_time(22, 15)

def is_daytime():
    now_t = datetime.now().time()
    return DAY_START <= now_t <= DAY_END

# ---------------- FILES ----------------
BASE_DIR = "/home/pi"
SOUNDS = {
    astiki_btn: os.path.join(BASE_DIR, "astiki.mp3"),
    asanser_btn: os.path.join(BASE_DIR, "asanser.mp3"),
    troxaio_btn: os.path.join(BASE_DIR, "troxaio.mp3"),
    dasiki_btn: os.path.join(BASE_DIR, "dasiki.mp3"),
    mic_btn: os.path.join(BASE_DIR, "mic.mp3"),
}
TTS_TEXTS = {
    astiki_btn: "Αστική Πυρκαγιά",
    asanser_btn: "Παροχή βοηθείας",
    troxaio_btn: "Τροχαίο",
    dasiki_btn: "Δασική Αγροτοδασική Πυρκαγιά",
}
TTS_FILES = {
    pin: os.path.join(BASE_DIR, f"tts_{pin}.mp3")
    for pin in TTS_TEXTS
}

# ---------------- GPIO SETUP ----------------
GPIO.setup([astiki_btn, asanser_btn, troxaio_btn, dasiki_btn, mic_btn],
           GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup([relay1, relay2, led_red, led_blue, led_running],
           GPIO.OUT, initial=GPIO.HIGH)

GPIO.output(relay1, GPIO.HIGH)
GPIO.output(relay2, GPIO.HIGH)
GPIO.output(led_red, GPIO.LOW)
GPIO.output(led_blue, GPIO.LOW)
GPIO.output(led_running, GPIO.HIGH)
logger.info("Σύστημα έτοιμο – led_running ON")

# ---------------- WATCHDOG ----------------
def watchdog_kick_loop():
    try:
        with open('/dev/watchdog', 'w') as wd:
            logger.info("Watchdog kicking")
            while True:
                wd.write('1')
                wd.flush()
                time.sleep(10)
    except Exception as e:
        if "busy" in str(e):
            logger.warning("Watchdog busy - OK")
        else:
            logger.error(f"Watchdog: {e}")

threading.Thread(target=watchdog_kick_loop, daemon=True).start()

# ---------------- HELPERS ----------------
def play_mp3(path):
    set_volume_93()  # 93% ΚΑΘΕ ΦΟΡΑ!
    if not os.path.exists(path):
        logger.error(f"Λείπει: {path}")
        return
    subprocess.run(["mpg123", "-q", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def ensure_tts(pin):
    if os.path.exists(TTS_FILES[pin]):
        return
    gTTS(text=TTS_TEXTS[pin], lang="el").save(TTS_FILES[pin])

def play_tts_mp3_tts(pin):
    ensure_tts(pin)
    play_mp3(TTS_FILES[pin])
    play_mp3(SOUNDS[pin])
    play_mp3(TTS_FILES[pin])

def immediate_relay1_on():
    """ΚΑΤΕΥΘΕΙΑΝ relay1 ON - αγνοεί manual/daytime"""
    global relay1_manual_on
    logger.info("⚡ IMMEDIATE relay1 ON")
    GPIO.output(relay1, GPIO.LOW)
    relay1_manual_on = False  # Ακυρώνει manual

def turn_on_relay2():
    logger.info("  → relay2 flash")
    GPIO.output(relay2, GPIO.LOW)
    time.sleep(0.5)
    GPIO.output(relay2, GPIO.HIGH)

def init_relay1_by_time():
    now = datetime.now().strftime("%H:%M:%S")
    is_day = is_daytime()
    global daytime_forced_on
    
    logger.info(f"*** INIT | {now} | day: {is_day} ***")
    
    if is_day:
        GPIO.output(relay1, GPIO.LOW)
        daytime_forced_on = True
        logger.info(f"*** ΗΜΕΡΑ ON: GPIO{relay1}={GPIO.input(relay1)}")
    else:
        GPIO.output(relay1, GPIO.HIGH)
        daytime_forced_on = False
        logger.info(f"*** ΝΥΧΤΑ OFF: GPIO{relay1}={GPIO.input(relay1)}")

def day_scheduler_loop():
    global daytime_forced_on
    while True:
        now_day = is_daytime()
        now_str = datetime.now().strftime("%H:%M")
        
        if now_day and not daytime_forced_on and not relay1_manual_on:
            logger.info(f"*** SCHED {now_str}: ΗΜΕΡΑ ON ***")
            GPIO.output(relay1, GPIO.LOW)
            daytime_forced_on = True
        
        elif not now_day and daytime_forced_on and not relay1_manual_on:
            logger.info(f"*** SCHED {now_str}: ΝΥΧΤΑ OFF ***")
            GPIO.output(relay1, GPIO.HIGH)
            daytime_forced_on = False
        
        time.sleep(30)

def start_alarm_for_pin(pin):
    """SIMPLE & RELIABLE - ΚΑΘΕ ΠΑΤΗΜΑ δουλεύει!"""
    logger.info(f"🚨 ALARM START pin{pin}")
    
    # ΚΑΤΕΥΘΕΙΑΝ relay1 ON
    immediate_relay1_on()
    turn_on_relay2()
    
    # Delay: 5s νύχτα / 4s μέρα
    delay = 5 if not is_daytime() else 4
    logger.info(f"⏱️  Delay {delay}s")
    time.sleep(delay)
    
    # Ήχος
    if pin == mic_btn:
        play_mp3(SOUNDS[mic_btn])
    else:
        play_tts_mp3_tts(pin)
    
    logger.info("✅ ALARM END")

# ---------------- MIC HANDLER ----------------
def handle_mic_button():
    GPIO.output(led_red, GPIO.HIGH)
    start = time.time()
    long_press = False

    while GPIO.input(mic_btn) == GPIO.LOW:
        if not long_press and time.time() - start >= 2:
            long_press = True
            global relay1_manual_on
            if not relay1_manual_on:
                logger.info("🔵 MIC LONG → MANUAL ON")
                GPIO.output(relay1, GPIO.LOW)
                GPIO.output(led_blue, GPIO.HIGH)
                relay1_manual_on = True
            else:
                logger.info("🔴 MIC LONG → MANUAL OFF")
                GPIO.output(relay1, GPIO.HIGH)
                GPIO.output(led_blue, GPIO.LOW)
                relay1_manual_on = False
        time.sleep(0.05)

    if not long_press:
        start_alarm_for_pin(mic_btn)
    GPIO.output(led_red, GPIO.LOW)

# ---------------- MAIN ----------------
def handle_button(pin):
    GPIO.output(led_red, GPIO.HIGH)
    logger.info(f"🔴 BUTTON {pin}")
    
    if pin == mic_btn:
        handle_mic_button()
    else:
        start_alarm_for_pin(pin)
    
    time.sleep(0.3)
    GPIO.output(led_red, GPIO.LOW)

# ---------------- START ----------------
init_relay1_by_time()
threading.Thread(target=day_scheduler_loop, daemon=True).start()

logger.info("🎯 READY - ΚΑΘΕ ΠΑΤΗΜΑ δουλεύει!")
try:
    while True:
        for btn in [astiki_btn, asanser_btn, troxaio_btn, dasiki_btn, mic_btn]:
            if GPIO.input(btn) == GPIO.LOW:
                handle_button(btn)
                time.sleep(0.3)
        time.sleep(0.05)
except KeyboardInterrupt:
    logger.info("⏹️ STOP")
finally:
    GPIO.output(led_running, GPIO.LOW)
    GPIO.output(relay1, GPIO.HIGH)
    GPIO.output(relay2, GPIO.HIGH)
    GPIO.cleanup()
    logger.info("✅ CLEANUP")
