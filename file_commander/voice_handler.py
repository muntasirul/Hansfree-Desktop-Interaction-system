"""
voice_handler.py — Captures audio from mic and converts to text using SpeechRecognition.
"""

import threading
import speech_recognition as sr


class VoiceHandler:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8
        self._is_listening = False

    def listen_once(self, on_result, on_error, on_listening):
        """
        Listen for a single voice command in a background thread.
        Callbacks:
          on_result(text: str)  — called with recognized text
          on_error(msg: str)    — called on error
          on_listening()        — called when mic opens (UI feedback)
        """
        def _run():
            self._is_listening = True
            try:
                with sr.Microphone() as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    on_listening()
                    audio = self.recognizer.listen(source, timeout=10, phrase_time_limit=15)

                text = self.recognizer.recognize_google(audio)
                on_result(text)
            except sr.WaitTimeoutError:
                on_error("No speech detected. Please try again.")
            except sr.UnknownValueError:
                on_error("Could not understand the audio. Please speak clearly.")
            except sr.RequestError as e:
                on_error(f"Speech recognition service error: {e}")
            except Exception as e:
                on_error(f"Microphone error: {e}")
            finally:
                self._is_listening = False

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    @property
    def is_listening(self):
        return self._is_listening
