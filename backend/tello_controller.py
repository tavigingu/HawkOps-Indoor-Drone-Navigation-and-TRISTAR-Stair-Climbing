#!/usr/bin/env python3
"""
Tello Controller - Singleton Pattern
Gestionează conexiunea și controlul dronei DJI Tello cu thread-safety.
"""

import threading
import time
from djitellopy import Tello
import cv2
import numpy as np


class TelloController:
    """
    Controller singleton pentru drona Tello.
    Asigură o singură instanță activă pentru a preveni conflicte de conexiune.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """
        Implementare Singleton Pattern cu thread-safety.
        Returnează aceeași instanță pentru toate apelurile.
        """
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking pentru thread-safety
                if cls._instance is None:
                    instance = super(TelloController, cls).__new__(cls)
                    try:
                        instance._initialize()
                    except Exception:
                        cls._instance = None
                        raise
                    cls._instance = instance
        return cls._instance
    
    def _initialize(self):
        """
        Inițializare internă - apelată o singură dată.
        Conectează la dronă și activează stream-ul video.
        """
        self._is_flying = False
        self._flight_lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._frame_error_count = 0
        self._last_stream_recovery_ts = 0.0
        self._stream_recovery_cooldown_s = 3.0
        self._frame_read = None

        print("Inițializare TelloController...")
        self.tello = Tello()
        self.tello.connect()
        
        # Așteaptă ca starea să fie inițializată (UDP state thread)
        print("Așteptare inițializare stare dronă...")
        time.sleep(3)
        
        # Încearcă să obții starea de mai multe ori
        max_retries = 5
        for i in range(max_retries):
            try:
                battery = self.tello.get_battery()
                temp = self.tello.get_temperature()
                print(f"✓ Conectat la Tello. Baterie: {battery}%, Temperatură: {temp}°C")
                break
            except Exception as e:
                if i < max_retries - 1:
                    print(f"Încercare {i+1}/{max_retries} de citire stare... {e}")
                    time.sleep(2)
                else:
                    print(f"⚠️ Nu s-a putut citi starea după {max_retries} încercări")
        
        # Activează stream video
        self.tello.streamon()
        print("✓ Stream video activat")

        # Inițializează frame reader-ul o singură dată
        self._frame_read = self.tello.get_frame_read()
        
        # Așteaptă puțin să se stabilizeze stream-ul
        time.sleep(1)
        
        # State deja inițializat la începutul metodei

    def _recover_video_stream(self, reason="unknown"):
        """Încearcă recovery pentru stream video fără a bloca excesiv bucla de captură."""
        now = time.monotonic()
        if now - self._last_stream_recovery_ts < self._stream_recovery_cooldown_s:
            return

        with self._stream_lock:
            now = time.monotonic()
            if now - self._last_stream_recovery_ts < self._stream_recovery_cooldown_s:
                return

            self._last_stream_recovery_ts = now

            try:
                print(f"⚠️ Stream video instabil ({reason}) - încerc recovery...")
                try:
                    self.tello.streamoff()
                except Exception:
                    pass

                time.sleep(0.25)
                self.tello.streamon()
                self._frame_read = self.tello.get_frame_read()
                self._frame_error_count = 0
                print("✅ Recovery stream video reușit")
            except Exception as e:
                print(f"❌ Recovery stream video eșuat: {e}")
    
    # ==================== CONTROL BASIC ====================
    
    def takeoff(self, max_attempts=2):
        """Decolează drona cu retry scurt și re-arm SDK mode."""
        print("Takeoff...")
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                self.stop_movement()
                time.sleep(0.15)
                self.tello.takeoff()
                with self._flight_lock:
                    self._is_flying = True
                return
            except Exception as e:
                last_error = e
                print(f"⚠️ Takeoff attempt {attempt}/{max_attempts} eșuat: {e}")

                if attempt < max_attempts:
                    try:
                        self.tello.send_control_command("command")
                    except Exception as cmd_error:
                        print(f"⚠️ Re-arm SDK mode eșuat: {cmd_error}")
                    time.sleep(0.8)

        raise RuntimeError(f"Takeoff eșuat după {max_attempts} încercări: {last_error}")
    
    def land(self):
        """Aterizează drona."""
        print("Landing...")
        self.tello.land()
        with self._flight_lock:
            self._is_flying = False
    
    def is_flying(self):
        """Returnează True dacă drona este în zbor."""
        with self._flight_lock:
            return self._is_flying
    
    def emergency(self):
        """Oprire de urgență - oprește toate motoarele imediat!"""
        print("⚠️ EMERGENCY STOP!")
        self.tello.emergency()
        with self._flight_lock:
            self._is_flying = False
    
    # ==================== MIȘCARE SIMPLĂ ====================
    
    def move_up(self, distance_cm):
        """Mișcare în sus cu distanță specificată (cm)."""
        self.tello.move_up(distance_cm)
    
    def move_down(self, distance_cm):
        """Mișcare în jos cu distanță specificată (cm)."""
        self.tello.move_down(distance_cm)
    
    def move_left(self, distance_cm):
        """Mișcare la stânga cu distanță specificată (cm)."""
        self.tello.move_left(distance_cm)
    
    def move_right(self, distance_cm):
        """Mișcare la dreapta cu distanță specificată (cm)."""
        self.tello.move_right(distance_cm)
    
    def move_forward(self, distance_cm):
        """Mișcare înainte cu distanță specificată (cm)."""
        self.tello.move_forward(distance_cm)
    
    def move_back(self, distance_cm):
        """Mișcare înapoi cu distanță specificată (cm)."""
        self.tello.move_back(distance_cm)
    
    # ==================== ROTAȚIE ====================
    
    def move_clockwise(self, degrees):
        """Rotație în sens orar cu grade specificate."""
        self.tello.rotate_clockwise(degrees)
    
    def move_counter_clockwise(self, degrees):
        """Rotație în sens anti-orar cu grade specificate."""
        self.tello.rotate_counter_clockwise(degrees)
    
    def move_slow_clockwise(self, degrees, speed=9):
        """
        Rotație lentă în sens orar.
        
        Args:
            degrees: Grade de rotație
            speed: Viteză (1-100 cm/s), default 9 pentru mișcare lentă
        """
        self.tello.set_speed(speed)
        self.tello.rotate_clockwise(degrees)
    
    def move_slow_counter_clockwise(self, degrees, speed=9):
        """
        Rotație lentă în sens anti-orar.
        
        Args:
            degrees: Grade de rotație
            speed: Viteză (1-100 cm/s), default 9 pentru mișcare lentă
        """
        self.tello.set_speed(speed)
        self.tello.rotate_counter_clockwise(degrees)
    
    # ==================== CONTROL RC (Continuu) ====================
    
    def send_rc_control(self, left_right_velocity, forward_backward_velocity, 
                       up_down_velocity, yaw_velocity):
        """
        Trimite comenzi RC pentru control continuu.
        
        Args:
            left_right_velocity: -100 (stânga) la 100 (dreapta)
            forward_backward_velocity: -100 (înapoi) la 100 (înainte)
            up_down_velocity: -100 (jos) la 100 (sus)
            yaw_velocity: -100 (anti-orar) la 100 (orar)
        """
        self.tello.send_rc_control(
            left_right_velocity,
            forward_backward_velocity,
            up_down_velocity,
            yaw_velocity
        )
    
    def stop_movement(self):
        """Oprește toate mișcările (setează toate velocitățile la 0)."""
        self.send_rc_control(0, 0, 0, 0)
    
    # ==================== VIDEO STREAMING ====================
    
    def get_frame(self):
        """
        Obține frame-ul curent din stream-ul video.
        
        Returns:
            numpy.ndarray: Frame RGB sau None dacă nu este disponibil
        """
        frame = self.get_frame_bgr()
        if frame is not None:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return None

    def _is_valid_frame(self, frame):
        """Validează rapid frame-ul citit din stream."""
        if frame is None:
            return False
        if not isinstance(frame, np.ndarray):
            return False
        if frame.size == 0:
            return False
        if frame.ndim < 2:
            return False
        return True

    def _get_frame_from_reader(self):
        """Citește frame din reader-ul persistent."""
        if self._frame_read is None:
            self._recover_video_stream(reason="frame reader missing")
            return None
        return self._frame_read.frame

    def _handle_frame_failure(self, reason):
        """Contorizează erori și lansează recovery când se acumulează."""
        self._frame_error_count += 1
        if self._frame_error_count in (1, 10) or self._frame_error_count % 30 == 0:
            print(f"Eroare la citire frame: {reason} (count={self._frame_error_count})")

        if self._frame_error_count >= 8:
            self._recover_video_stream(reason=reason)

    def _handle_frame_success(self):
        """Resetează contorul de erori după captură validă."""
        if self._frame_error_count > 0:
            self._frame_error_count = 0

    def get_frame_bgr(self):
        """
        Obține frame-ul curent în format BGR (pentru OpenCV direct).

        Returns:
            numpy.ndarray: Frame BGR sau None dacă nu este disponibil
        """
        try:
            frame = self._get_frame_from_reader()
            if self._is_valid_frame(frame):
                self._handle_frame_success()
                return frame

            self._handle_frame_failure("invalid/empty frame")
            return None
        except Exception as e:
            self._handle_frame_failure(str(e))
            return None
    
    def streamon(self):
        """Activează stream-ul video."""
        self.tello.streamon()
        self._frame_read = self.tello.get_frame_read()
    
    def streamoff(self):
        """Dezactivează stream-ul video."""
        self.tello.streamoff()
    
    # ==================== INFORMAȚII TELEMETRIE ====================
    
    def get_battery(self):
        """
        Obține nivelul bateriei.
        
        Returns:
            int: Procent baterie (0-100) sau 0 în caz de eroare
        """
        try:
            return self.tello.get_battery()
        except Exception as e:
            print(f"Eroare la citire baterie: {e}")
            return 0
    
    def get_height(self):
        """
        Obține înălțimea curentă.
        
        Returns:
            int: Înălțime în cm sau 0 în caz de eroare
        """
        try:
            return self.tello.get_height()
        except Exception as e:
            return 0
    
    def get_temperature(self):
        """
        Obține temperatura dronei.
        
        Returns:
            int: Temperatura în grade Celsius
        """
        try:
            return self.tello.get_temperature()
        except Exception as e:
            return 0
    
    def get_speed(self):
        """
        Obține viteza curentă setată.
        
        Returns:
            int: Viteză în cm/s
        """
        try:
            return self.tello.get_speed()
        except Exception as e:
            return 0
    
    def get_flight_time(self):
        """
        Obține timpul de zbor curent.
        
        Returns:
            int: Timp în secunde
        """
        try:
            return self.tello.get_flight_time()
        except Exception as e:
            return 0
    
    # ==================== CALIBRARE & UTILITĂȚI ====================
    
    def calibrate(self):
        """Calibrează IMU-ul dronei."""
        print("Calibrare IMU...")
        self.tello.send_control_command("imu_calibrate")
    
    def set_speed(self, speed):
        """
        Setează viteza de mișcare.
        
        Args:
            speed: Viteză în cm/s (10-100)
        """
        self.tello.set_speed(speed)
    
    def calculate_movement_time(self, distance_cm, speed_cms):
        """
        Calculează timpul necesar pentru o mișcare.
        
        Args:
            distance_cm: Distanță în cm
            speed_cms: Viteză în cm/s
            
        Returns:
            float: Timp în secunde
        """
        return distance_cm / speed_cms
    
    # ==================== GESTIONARE ERORI ====================
    
    def _handle_error(self):
        """Gestionare erori - aterizare de siguranță."""
        print("⚠️ Handling error... Returning to safe state.")
        try:
            if self.is_flying():
                self.tello.land()
                with self._flight_lock:
                    self._is_flying = False
        except Exception as e:
            print(f"Eroare la aterizare de siguranță: {e}")
        time.sleep(5)
    
    # ==================== CLEANUP ====================
    
    def cleanup(self):
        """Curățare resurse - apelează la închiderea aplicației."""
        print("Cleanup TelloController...")
        try:
            if hasattr(self, "_flight_lock") and self.is_flying():
                print("Drona încă zboară - aterizare automată...")
                self.land()

            if hasattr(self, "tello") and self.tello is not None:
                try:
                    self.streamoff()
                except Exception:
                    pass
                self._frame_read = None
                self.tello.end()
            print("✓ Cleanup complet")
        except Exception as e:
            print(f"Eroare la cleanup: {e}")
    
    def __del__(self):
        """Destructor - asigură cleanup la ștergerea instanței."""
        try:
            self.cleanup()
        except:
            pass


# ==================== FUNCȚII HELPER ====================

def get_controller():
    """
    Helper function pentru a obține instanța singleton a controller-ului.
    
    Returns:
        TelloController: Instanța unică a controller-ului
    """
    return TelloController()


if __name__ == "__main__":
    # Test simplu
    print("Test TelloController...")
    
    controller = TelloController()
    print(f"Baterie: {controller.get_battery()}%")
    print(f"Temperatură: {controller.get_temperature()}°C")
    
    # Test că singleton funcționează
    controller2 = TelloController()
    assert controller is controller2, "Singleton nu funcționează corect!"
    print("✓ Singleton pattern funcționează corect")
    
    print("\nController gata de utilizare!")
    print("Folosește controller.takeoff() pentru decolare")
    
    controller.cleanup()
