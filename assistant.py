"""
assistant.py — AI Assistant to guide users through the Desktop Navigation System.
Provides helpful information and voice prompts.
Powered by Groq LLM for intelligent responses to any question.
Now with text-to-speech for complete hands-free accessibility!
"""

from typing import Optional
import textwrap
import os
from dotenv import load_dotenv
from groq import Groq
import threading

# Text-to-speech engine
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("[Assistant] pyttsx3 not installed - TTS disabled. Run: pip install pyttsx3")

load_dotenv()


class NavigationAssistant:
    """Helps users understand and use the Desktop Navigation System."""
    
    SYSTEM_MESSAGES = {
        "welcome": """Welcome to the Desktop Navigation System!
I can help you activate different modes using voice commands.
Say things like:
• "Cursor Mode" - for head tracking navigation
• "Action Mode" - for file and command management  
• "Typing Mode" - for hands-free typing
• "Web Mode" - for web browsing
• "Help" - to hear your options again""",
        
        "listening": "Listening... Say a mode name or command.",
        
        "mode_activated": lambda mode: {
            "cursor": f"Activating Cursor Navigation Mode. Control your cursor with head movements and blink to click!",
            "action": f"Activating Action Mode. Manage files and execute commands with voice or text input!",
            "typing": f"Activating Typing Mode. Type with your voice using hands-free dictation!",
            "web": f"Activating Web Mode. Browse the web with gesture and voice commands!",
        }.get(mode, f"Activating {mode} mode..."),
        
        "mode_deactivated": lambda mode: f"{mode.title()} mode has been stopped.",
        
        "already_running": lambda mode: f"{mode.title()} mode is already running!",
        
        "help": """Here's what you can do:

1. VOICE COMMANDS:
   • Say "Cursor Mode" to control your cursor with head tracking
   • Say "Action Mode" for file management and voice commands
   • Say "Typing Mode" for hands-free typing
   • Say "Web Mode" for web browsing

2. UI CONTROLS:
   • Click on any mode card to start or stop it
   • Press Ctrl+Q to quit the application
   • Each mode can run independently

3. TIPS:
   • Speak clearly into the microphone
   • One mode can run at a time per card
   • You can have multiple modes running together
   • Check the status indicators on each mode card""",
        
        "error_no_speech": "I didn't hear anything. Please try again.",
        "error_no_understand": "Sorry, I didn't understand that. Could you repeat it?",
        "error_service": "There was a problem with the speech service. Please try again.",
        
        "mode_info": {
            "cursor": """Cursor Navigation Mode:
• Control your cursor with head and nose movement
• Blink to click
• Mouth movements for special interactions
• Great for hands-free navigation""",
            
            "action": """Action Mode (AI File Commander):
• Execute commands with voice or text input
• Manage files and directories
• Open applications
• Powered by AI language model (Groq)""",
            
            "typing": """Typing Mode:
• Type documents with voice dictation
• Hands-free virtual keyboard
• Natural language processing for corrections
• Perfect for note-taking and writing""",
            
            "web": """Web Mode:
• Browse the internet hands-free
• Voice commands for navigation
• Gesture controls for scrolling and clicking
• Designed for accessibility""",
        }
    }
    
    def __init__(self):
        self.context = {}
        self.last_mode = None
        
        # Initialize Text-to-Speech for accessibility
        self.tts_engine = None
        self.tts_queue = []
        self.tts_thread = None
        
        if TTS_AVAILABLE:
            try:
                self.tts_engine = pyttsx3.init()
                self.tts_engine.setProperty('rate', 150)  # Speech speed
                self.tts_engine.setProperty('volume', 0.9)  # Volume (0.0 to 1.0)
                print("[Assistant] Text-to-Speech initialized successfully")
            except Exception as e:
                print(f"[Assistant] TTS initialization failed: {e}")
                self.tts_engine = None
        
        # Initialize Groq LLM for intelligent responses
        self.groq_client = None
        self.groq_available = False
        
        try:
            api_key = os.getenv("GROQ_API_KEY", "")
            if api_key and api_key != "your_groq_api_key_here":
                self.groq_client = Groq(api_key=api_key)
                self.groq_available = True
                print("[Assistant] Groq LLM initialized successfully")
            else:
                print("[Assistant] Groq API key not found - using predefined responses only")
        except Exception as e:
            print(f"[Assistant] Failed to initialize Groq: {e}")
            self.groq_available = False
    
    def get_welcome_message(self) -> str:
        """Get the initial welcome message."""
        return self.SYSTEM_MESSAGES["welcome"]
    
    def get_listening_prompt(self) -> str:
        """Get the listening prompt."""
        return self.SYSTEM_MESSAGES["listening"]
    
    def get_mode_activation_message(self, mode_id: str) -> str:
        """Get the message when a mode is activated."""
        msg_func = self.SYSTEM_MESSAGES["mode_activated"]
        return msg_func(mode_id)
    
    def get_mode_deactivation_message(self, mode_id: str) -> str:
        """Get the message when a mode is stopped."""
        msg_func = self.SYSTEM_MESSAGES["mode_deactivated"]
        return msg_func(mode_id)
    
    def get_already_running_message(self, mode_id: str) -> str:
        """Get message when mode is already running."""
        msg_func = self.SYSTEM_MESSAGES["already_running"]
        return msg_func(mode_id)
    
    def get_help_message(self) -> str:
        """Get detailed help information."""
        return self.SYSTEM_MESSAGES["help"]
    
    def get_mode_info(self, mode_id: str) -> str:
        """Get detailed information about a specific mode."""
        return self.SYSTEM_MESSAGES["mode_info"].get(
            mode_id, 
            f"No information available about {mode_id} mode."
        )
    
    def get_error_message(self, error_type: str) -> str:
        """Get an appropriate error message."""
        messages = {
            "no_speech": self.SYSTEM_MESSAGES["error_no_speech"],
            "no_understand": self.SYSTEM_MESSAGES["error_no_understand"],
            "service": self.SYSTEM_MESSAGES["error_service"],
        }
        return messages.get(error_type, "An error occurred. Please try again.")
    
    def set_context(self, **kwargs):
        """Store context information about the current session."""
        self.context.update(kwargs)
    
    def get_context(self, key: str, default=None):
        """Retrieve stored context information."""
        return self.context.get(key, default)
    
    def get_quick_help(self) -> str:
        """Get a quick reference of voice commands."""
        return """Quick Commands:
🎯 "Cursor Mode" - Head tracking
⚡ "Action Mode" - Files & Commands  
⌨️  "Typing Mode" - Hands-free typing
🌐 "Web Mode" - Web browsing
❓ "Help" - Full instructions"""
    
    def speak(self, text: str):
        """Speak text and stop any previous speech."""
    
        if not TTS_AVAILABLE:
            return
        
        try:
            # Stop previous speech
            engine = pyttsx3.init()
            engine.stop()

            print(f"[Assistant] Speaking: {text[:50]}...")

            engine.setProperty('rate', 150)
            engine.setProperty('volume', 0.9)

            engine.say(text)
            engine.runAndWait()

        except Exception as e:
            print(f"[Assistant] TTS error: {e}")
    
    def speak_async(self, text: str):
        """Async version of speak - fire and forget."""
        if not self.tts_engine:
            print(f"[Assistant] TTS engine not available")
            return
        self.speak(text)
    
    def answer_question(self, question: str) -> str:
        """
        Answer any question using Groq LLM for intelligent responses.
        Falls back to predefined responses if question matches known patterns.
        
        Args:
            question: User's question or statement
            
        Returns:
            Assistant's response (from LLM or predefined)
        """
        if not question or not question.strip():
            return "Please ask me a question or say a mode name to activate it."
        
        question_lower = question.lower().strip()
        
        # Check for known questions first for quick response
        known_patterns = {
            "cursor": self.get_mode_info("cursor"),
            "action": self.get_mode_info("action"),
            "typing": self.get_mode_info("typing"),
            "web": self.get_mode_info("web"),
            "what can i do": self.get_help_message(),
            "tell me": self.get_help_message(),
            "assistance": self.get_help_message(),
        }
        
        for pattern, response in known_patterns.items():
            if pattern in question_lower:
                return response
        
        if self.groq_available and self.groq_client:
            try:
                answer = self._query_groq(question)

                # Speak the answer
                self.speak_async(answer)

                return answer

            except Exception as e:
                print(f"[Assistant] Groq query failed: {e}")
                answer = self._get_fallback_response(question)
                self.speak_async(answer)
                return answer
    
    def _query_groq(self, question: str) -> str:
        """
        Query Groq LLM for intelligent response to any question.
        
        Args:
            question: User's question
            
        Returns:
            LLM-generated response
        """
        system_prompt = """You are a helpful AI assistant for the Desktop Navigation System.

The system has 4 main modes:
1. Cursor Navigation - Control mouse with head/nose tracking
2. Action Mode - Manage files and execute commands with voice/text
3. Typing Mode - Hands-free voice dictation typing
4. Web Mode - Browse the internet with voice and gestures

You can answer questions about:
• How to use the system
• What each mode does
• Troubleshooting issues
• General computer/software questions
• Tips for better voice recognition

Keep responses brief (1-3 sentences), friendly, and helpful.
If it's not related to the Navigation System, still provide helpful answers."""
        
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.7,
                max_tokens=256,
                timeout=10.0,
            )
            
            answer = response.choices[0].message.content.strip()
            return answer
            
        except Exception as e:
            raise e
    
    def _get_fallback_response(self, question: str) -> str:
        """
        Provide a helpful fallback response when Groq is not available.
        
        Args:
            question: User's question
            
        Returns:
            Helpful fallback response
        """
        if any(word in question.lower() for word in ["how", "help", "tutorial", "guide"]):
            return self.get_help_message()
        elif any(word in question.lower() for word in ["cursor", "tracking", "head"]):
            return self.get_mode_info("cursor")
        elif any(word in question.lower() for word in ["file", "command", "action"]):
            return self.get_mode_info("action")
        elif any(word in question.lower() for word in ["type", "typing", "dictation"]):
            return self.get_mode_info("typing")
        elif any(word in question.lower() for word in ["web", "browser", "internet"]):
            return self.get_mode_info("web")
        else:
            return (
                "I'm here to help with the Desktop Navigation System! "
                "Ask about the modes, voice commands, or say a mode name to activate it. "
                "Say 'Help' for detailed instructions."
            )



# Singleton instance
_assistant = None


def get_assistant() -> NavigationAssistant:
    """Get or create the global assistant instance."""
    global _assistant
    if _assistant is None:
        _assistant = NavigationAssistant()
    return _assistant
