"""
Multilingual AI Health Chatbot Service v6.0
Uses OpenAI (gpt-4o-mini) for high-quality, multilingual, medically-safe responses.
Auto-detects language and responds in the same language.
Supports text + optional image (vision) input.
"""

import os
import time
import base64
from openai import OpenAI, APIError, RateLimitError

try:
    import requests
    REQUESTS_OK = True
except Exception:
    REQUESTS_OK = False

# ─── Configuration ──────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "900"))
OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.6"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

IS_GEMINI_KEY_VALID = True
WORKING_PROVIDER = None

try:
    from langdetect import detect as detect_lang, DetectorFactory
    DetectorFactory.seed = 0
    LANGDETECT_OK = True
except Exception:
    LANGDETECT_OK = False

# ─── Language Configuration (15+ languages) ─────────────────────────────────────
LANGUAGE_CONFIG = {
    "en": {"name": "English",    "native": "English"},
    "hi": {"name": "Hindi",      "native": "हिन्दी"},
    "ta": {"name": "Tamil",      "native": "தமிழ்"},
    "te": {"name": "Telugu",     "native": "తెలుగు"},
    "ml": {"name": "Malayalam",  "native": "മലയാളം"},
    "kn": {"name": "Kannada",    "native": "ಕನ್ನಡ"},
    "pa": {"name": "Punjabi",    "native": "ਪੰਜਾਬੀ"},
    "gu": {"name": "Gujarati",   "native": "ગુજરાતી"},
    "mr": {"name": "Marathi",    "native": "मराठी"},
    "bn": {"name": "Bengali",    "native": "বাংলা"},
    "ur": {"name": "Urdu",       "native": "اردو"},
    "es": {"name": "Spanish",    "native": "Español"},
    "fr": {"name": "French",     "native": "Français"},
    "de": {"name": "German",     "native": "Deutsch"},
    "ar": {"name": "Arabic",     "native": "العربية"},
    "pt": {"name": "Portuguese", "native": "Português"},
    "ru": {"name": "Russian",    "native": "Русский"},
    "zh-cn": {"name": "Chinese", "native": "中文"},
    "ja": {"name": "Japanese",   "native": "日本語"},
}

# ─── Emergency Detection ────────────────────────────────────────────────────────
EMERGENCY_TERMS = [
    # English
    "chest pain", "heart attack", "stroke", "seizure", "unconscious",
    "not breathing", "can't breathe", "cannot breathe", "severe bleeding",
    "bleeding heavily", "overdose", "suicide", "kill myself", "end my life",
    "poisoning", "paralysis", "collapsed", "severe chest pain",
    "choking", "anaphylaxis", "no pulse",
    # Hindi
    "सीने में दर्द", "दिल का दौरा", "सांस नहीं", "बेहोश", "खून बहना",
    # Spanish / French / German / Arabic (core terms)
    "dolor en el pecho", "infarto", "ataque cardíaco",
    "douleur thoracique", "crise cardiaque",
    "herzinfarkt", "brustschmerz",
    "ألم في الصدر", "نوبة قلبية",
]

EMERGENCY_HELPLINES = {
    "ambulance_india": "108",
    "general_emergency_india": "112",
    "health_helpline_india": "104",
    "mental_health_india": "Vandrevala Foundation: 1860-2662-345",
    "poison_control_india": "1800-116-117",
}


def _detect_language(text):
    """Detect the ISO-639 language code of the text; fall back to English."""
    if not LANGDETECT_OK or not text.strip():
        return "en"
    try:
        code = detect_lang(text)
        # Normalise langdetect codes to our config
        if code == "zh-cn" or code == "zh-tw":
            return "zh-cn"
        return code if code in LANGUAGE_CONFIG else "en"
    except Exception:
        return "en"


def _detect_emergency(message):
    msg_lower = message.lower()
    return any(term.lower() in msg_lower for term in EMERGENCY_TERMS)


# ─── System Prompt ──────────────────────────────────────────────────────────────
def _build_system_prompt(lang_name, lang_native, is_emergency):
    emergency_block = ""
    if is_emergency:
        emergency_block = (
            "\n\nTHIS MESSAGE APPEARS TO DESCRIBE A MEDICAL EMERGENCY.\n"
            "- Open your reply with a clear, calm emergency alert.\n"
            "- Tell the user to call local emergency services IMMEDIATELY "
            "(India: 108 Ambulance / 112 Emergency; US: 911; UK: 999; EU: 112).\n"
            "- Give 2-4 critical first-aid steps for the described situation.\n"
            "- Do NOT delay by asking long clarifying questions first.\n"
        )

    return f"""You are MedAI, a world-class, empathetic, multilingual AI medical assistant.
You help patients understand symptoms, conditions, medicines, precautions, diet,
fitness, and mental wellness — and guide them to the right specialist or care level.

LANGUAGE RULES (CRITICAL):
- The user's language is {lang_name} ({lang_native}).
- Respond ENTIRELY in {lang_name}. Every sentence, every word, including headings.
- If the user mixes languages (e.g. Hinglish), reply in the SAME mixed style.
- Never switch languages mid-reply unless the user does.

MEDICAL SCOPE — answer clearly and helpfully on:
1. Symptoms and what conditions they MIGHT indicate (possibilities, not diagnoses).
2. Diseases: what they are, causes, risk factors, typical course.
3. Medicines: general category, common uses, common side effects, interactions —
   NEVER prescribe a specific drug or dosage. Always defer dosing to a doctor.
4. Precautions, home-care, lifestyle changes, red-flag warning signs.
5. Diet & nutrition tailored to the condition.
6. Fitness & physical activity suitable for the condition.
7. Mental wellness: anxiety, stress, sleep, low mood — with compassion.
8. Which doctor specialty to consult (e.g. cardiologist, dermatologist, ENT).

SAFETY RULES (NON-NEGOTIABLE):
- You are NOT a doctor. You do NOT diagnose. You do NOT prescribe.
- Never invent medicine names, dosages, or brand names.
- Never tell a user to stop prescribed medication.
- For serious, worsening, or red-flag symptoms, advise seeing a doctor urgently.
- For suicidal ideation or self-harm: respond with warmth, do NOT judge, share
  a helpline, and urge them to reach a trusted person or professional now.
- End each substantive reply with a short disclaimer that this is general
  guidance and a real doctor should be consulted for diagnosis or treatment.

STYLE:
- Warm, calm, professional. Plain language. No heavy jargon.
- Structure longer answers with short sections or bullets.
- Keep replies focused — typically 4-10 short sentences unless more detail is asked.
- If the user's message is unclear, ask ONE concise clarifying question.
- If the user asks something unrelated to health, gently steer back to health topics.{emergency_block}"""


# ─── Message Formatting ─────────────────────────────────────────────────────────
def _format_history(conversation_history):
    """Convert incoming history into OpenAI chat-completion message format."""
    formatted = []
    for msg in conversation_history[-10:]:
        role_in = msg.get("role", "user")
        role = "assistant" if role_in in ("bot", "model", "assistant") else "user"
        content = msg.get("content") or msg.get("text") or ""
        if content.strip():
            formatted.append({"role": role, "content": content})
    return formatted


def _build_user_content(user_message, image=None):
    """Build the user content block. Supports text-only or text+image."""
    if not image:
        return user_message

    # image is a dict: {"base64": "...", "mime_type": "image/png"}
    b64 = image.get("base64", "")
    mime = image.get("mime_type", "image/png")
    if not b64:
        return user_message

    data_url = f"data:{mime};base64,{b64}"
    return [
        {"type": "text", "text": user_message or "Please analyse this image."},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]


def _generate_simulated_response(user_message, detected_lang):
    msg = (user_message or "").lower().strip()
    
    # Multilingual translations for greeting response
    if detected_lang == "hi":
        if any(x in msg for x in ["नमस्ते", "हेलो", "हाय", "hi", "hello"]):
            return "नमस्ते! 👋 मैं MedAI हूँ, आपका क्लिनिकल निर्णय सहायक। मैं आपकी क्या मदद कर सकता हूँ? 🩺 आप मुझसे बीमारी के लक्षणों, दवाओं के साइड इफेक्ट्स या लाइफस्टाइल के बारे में पूछ सकते हैं! 🩹"
        if any(x in msg for x in ["लक्षण", "दर्द", "बुखार", "सिरदर्द", "symptom"]):
            return "मैं समझता हूँ कि आप अस्वस्थ महसूस कर रहे हैं। 🤒 यद्यपि मैं सामान्य चिकित्सा संभावनाएं साझा कर सकता हूँ, कृपया याद रखें कि मैं एक एआई हूँ, डॉक्टर नहीं।\n\n- **संभावित कारण**: वायरल संक्रमण, थकान, या मौसमी बदलाव।\n- **देखभाल युक्तियाँ**: पर्याप्त आराम करें, हाइड्रेटेड रहें। 💧\n\nकृपया उचित जांच के लिए डॉक्टर से परामर्श लें! 🩺"
        if any(x in msg for x in ["रिपोर्ट", "टेस्ट", "ब्लड"]):
            return "मैं मेडिकल रिपोर्ट समझाने में आपकी मदद कर सकता हूँ! 🔬 कृपया एक रिपोर्ट इमेज अपलोड करें या मैन्युअल रूप से मान दर्ज करें, और मैं विश्लेषण करूँगा! 📊"
        return "MedAI स्वास्थ्य सहायक में आपका स्वागत है! 🩺 मैं आपकी स्वास्थ्य संबंधी जानकारी समझने में मदद कर सकता हूँ। कृपया पूछें:\n- 🤒 सामान्य लक्षण और सावधानियां\n- 💊 दवाओं के दुष्प्रभाव और पारस्परिक क्रिया\n- 📊 लैब रिपोर्ट और नुस्खे की जानकारी\n- 🍎 आहार और फिटनेस सलाह\n\nयाद रखें: हमेशा डॉक्टर से सलाह लें! 🏥"
    
    # Default English
    if any(x in msg for x in ["hi", "hello", "hey", "hola", "bonjour"]):
        return "Hello! 👋 I am MedAI, your Clinical Decision Partner. How can I help you today? 🩺 Feel free to ask me about disease symptoms, drug side effects, lifestyle choices, or upload a prescription/report for analysis! 🩹"
    if any(x in msg for x in ["symptom", "pain", "fever", "headache", "cough", "cold"]):
        return "I understand you are experiencing symptoms. 🤒 While I can share typical medical possibilities, please remember I am an AI, not a doctor.\n\n- **Common Causes**: Viral infection, fatigue, mild dehydration, or seasonal changes.\n- **Care Tips**: Rest well, stay hydrated (water/fluids), and monitor your temperature. 💧\n- **Warning Signs**: High fever (>103°F), difficulty breathing, or severe sudden pain.\n\nplease consult a doctor for a proper diagnosis! 🩺"
    if any(x in msg for x in ["report", "blood", "test", "explain", "analyze"]):
        return "I can help explain medical lab reports! 🔬 Please upload a report image (e.g. CBC, Lipid Profile) or enter the values manually, and I will analyze the reference ranges and provide key insights for you! 📊"
    if any(x in msg for x in ["book", "doctor", "appointment"]):
        return "You can find and book an appointment with specialist doctors right from the **Doctor List** page or by using our Doctor Finder tool! 🩺 Let me know if you need help finding a specific specialty!"
    if any(x in msg for x in ["medicine", "drug", "pill", "side effect"]):
        return "I can provide safety information about common medications! 💊 Feel free to check the **Medicine Interactions** tab to see if different drugs have potential warnings, or ask me about side effects. Always follow your doctor's exact dosage! 📋"
    
    return "Thank you for reaching out to MedAI! 🩺 I am here to help you understand your health better. Feel free to ask about:\n- 🩺 Common symptoms & precautions\n- 💊 Medicine side effects & drug interactions\n- 📊 Lab report & prescription insights\n- 🍎 Diet & fitness recommendations\n\nRemember: Always consult a real healthcare professional for any medical conditions! 🏥"


def _generate_dynamic_fallback(user_message, conversation_history, system_prompt, detected_lang):
    global WORKING_PROVIDER
    try:
        import g4f
        
        # Prepare messages
        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history[-10:]:
            role_in = msg.get("role", "user")
            role = "assistant" if role_in in ("bot", "model", "assistant") else "user"
            content = msg.get("content") or msg.get("text") or ""
            if content.strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        # Try cached working provider first
        if WORKING_PROVIDER:
            try:
                print(f"[Chatbot] Attempting dynamic fallback with cached provider {WORKING_PROVIDER.__name__}...")
                response = g4f.ChatCompletion.create(
                    model=g4f.models.default,
                    provider=WORKING_PROVIDER,
                    messages=messages
                )
                text = (response or "").strip()
                if text:
                    return text
            except Exception as e:
                print(f"[Chatbot] Cached provider {WORKING_PROVIDER.__name__} failed: {e}")
                WORKING_PROVIDER = None # Clear cached provider on failure

        # Fallback list of providers to try sequentially
        providers = [
            g4f.Provider.GeminiPro,
            g4f.Provider.Yqcloud,
            g4f.Provider.PollinationsAI
        ]

        for prov in providers:
            try:
                print(f"[Chatbot] Attempting dynamic fallback with provider {prov.__name__}...")
                response = g4f.ChatCompletion.create(
                    model=g4f.models.default,
                    provider=prov,
                    messages=messages
                )
                text = (response or "").strip()
                if text:
                    WORKING_PROVIDER = prov # Cache the successful provider
                    print(f"[Chatbot] Success with provider {prov.__name__}")
                    return text
            except Exception as e:
                print(f"[Chatbot] Provider {prov.__name__} failed: {e}")

    except Exception as e:
        print(f"[Chatbot] Dynamic fallback initialization failed: {e}")
    return None



def _chat_with_gemini(user_message, conversation_history, system_prompt, lang_info, is_emergency, emergency_info, detected_lang, image):
    """Call Google Gemini and get chatbot response."""
    global IS_GEMINI_KEY_VALID
    
    if not IS_GEMINI_KEY_VALID or not GEMINI_API_KEY or not REQUESTS_OK:
        simulated = _generate_dynamic_fallback(user_message, conversation_history, system_prompt, detected_lang)
        if not simulated:
            simulated = _generate_simulated_response(user_message, detected_lang)
        return {
            "response": simulated,
            "detected_language": detected_lang,
            "language_name": lang_info["name"],
            "source": "gemini_simulated",
            "emergency": emergency_info,
            "is_emergency": is_emergency,
        }

    # Format history: alternating roles in user/model format
    contents = []
    for msg in conversation_history[-10:]:
        role_in = msg.get("role", "user")
        role = "model" if role_in in ("bot", "model", "assistant") else "user"
        content = msg.get("content") or msg.get("text") or ""
        if content.strip():
            contents.append({
                "role": role,
                "parts": [{"text": content}]
            })

    # Append current message
    parts = []
    if image and image.get("base64"):
        parts.append({
            "inline_data": {
                "mime_type": image.get("mime_type", "image/png"),
                "data": image.get("base64")
            }
        })
    parts.append({"text": user_message or "Please analyse this image."})
    
    contents.append({
        "role": "user",
        "parts": parts
    })

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "temperature": 0.6,
                "maxOutputTokens": 900
            }
        }
        # 25s timeout — long enough for Render cold-starts, short enough to not block the thread
        resp = requests.post(url, json=payload, timeout=25)
        if resp.status_code == 403:
            IS_GEMINI_KEY_VALID = False
            print("[Chatbot] Gemini API key returned 403. Disabling direct calls and using cached fallbacks.")
            raise RuntimeError("gemini_suspended_key_403")
        elif resp.status_code != 200:
            raise RuntimeError(f"gemini_http_{resp.status_code}: {resp.text[:200]}")

        res_json = resp.json()
        try:
            text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"gemini_response_structure_unexpected: {e}, raw: {res_json}")

        return {
            "response": text.strip(),
            "detected_language": detected_lang,
            "language_name": lang_info["name"],
            "source": f"gemini ({GEMINI_MODEL})",
            "emergency": emergency_info,
            "is_emergency": is_emergency,
        }
    except Exception as e:
        print(f"[Chatbot] Gemini error: {e}")
        simulated = _generate_dynamic_fallback(user_message, conversation_history, system_prompt, detected_lang)
        if not simulated:
            simulated = _generate_simulated_response(user_message, detected_lang)
        return {
            "response": simulated,
            "detected_language": detected_lang,
            "language_name": lang_info["name"],
            "source": "gemini_simulated",
            "emergency": emergency_info,
            "is_emergency": is_emergency,
        }


# ─── Main Chat Function ─────────────────────────────────────────────────────────
def chat_with_ai(user_message, conversation_history=None, language="auto", image=None):
    """
    Args:
        user_message (str): current user message.
        conversation_history (list): prior turns: [{"role": "user"|"bot", "content": "..."}].
        language (str): "auto" to detect, or a language code (e.g. "hi", "es").
        image (dict|None): optional {"base64": str, "mime_type": str} for vision.

    Returns:
        dict with response, detected_language, language_name, source,
        is_emergency, and emergency details if applicable.
    """
    conversation_history = conversation_history or []

    # 1. Language
    detected_lang = _detect_language(user_message) if language == "auto" else language
    lang_info = LANGUAGE_CONFIG.get(detected_lang, LANGUAGE_CONFIG["en"])

    # 2. Emergency
    is_emergency = _detect_emergency(user_message)
    emergency_info = {}
    if is_emergency:
        emergency_info = {
            "is_emergency": True,
            "message": "Possible medical emergency detected. Call 108 (India), 911 (US), or your local emergency number immediately.",
            "helplines": EMERGENCY_HELPLINES,
        }

    # 3. Guard: missing API key
    if _client is None and not GEMINI_API_KEY:
        return {
            "response": (
                "The chatbot is not configured. An API key is missing. "
                "Please set GEMINI_API_KEY or OPENAI_API_KEY in ml_service/.env and restart the service."
            ),
            "detected_language": detected_lang,
            "language_name": lang_info["name"],
            "source": "config_error",
            "emergency": emergency_info,
            "is_emergency": is_emergency,
        }

    # 4. Messages / System Prompt
    system_prompt = _build_system_prompt(
        lang_info["name"], lang_info["native"], is_emergency
    )

    if _client is None and GEMINI_API_KEY:
        return _chat_with_gemini(
            user_message, conversation_history, system_prompt,
            lang_info, is_emergency, emergency_info, detected_lang, image
        )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_format_history(conversation_history))
    messages.append({"role": "user", "content": _build_user_content(user_message, image)})

    # 5. Call OpenAI with retries on transient failures
    last_error = None
    for attempt in range(3):
        try:
            completion = _client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=OPENAI_TEMPERATURE,
                max_tokens=OPENAI_MAX_TOKENS,
            )
            text = (completion.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("Empty response from OpenAI")

            return {
                "response": text,
                "detected_language": detected_lang,
                "language_name": lang_info["name"],
                "source": f"openai ({OPENAI_MODEL})",
                "emergency": emergency_info,
                "is_emergency": is_emergency,
            }
        except RateLimitError as e:
            last_error = e
            wait = (attempt + 1) * 2
            print(f"[Chatbot] Rate limited — waiting {wait}s")
            time.sleep(wait)
        except APIError as e:
            last_error = e
            print(f"[Chatbot] OpenAI API error: {e}")
            break
        except Exception as e:
            last_error = e
            print(f"[Chatbot] Unexpected error: {e}")
            break

    # 6. Graceful multilingual fallback
    fallbacks = {
        "en": "I'm having trouble reaching the AI service right now. Please try again in a moment.",
        "hi": "क्षमा करें, अभी AI सेवा से कनेक्ट नहीं हो पा रहा। कृपया थोड़ी देर में पुनः प्रयास करें।",
        "es": "Lo siento, no puedo conectar con el servicio de IA ahora mismo. Inténtalo de nuevo en un momento.",
        "fr": "Désolé, impossible de joindre le service IA pour l'instant. Veuillez réessayer dans un instant.",
        "de": "Entschuldigung, der KI-Dienst ist momentan nicht erreichbar. Bitte in Kürze erneut versuchen.",
        "ar": "عذرًا، لا يمكنني الاتصال بخدمة الذكاء الاصطناعي الآن. يرجى المحاولة بعد قليل.",
    }
    simulated = _generate_dynamic_fallback(user_message, conversation_history, system_prompt, detected_lang)
    if not simulated:
        simulated = _generate_simulated_response(user_message, detected_lang)
    return {
        "response": simulated,
        "detected_language": detected_lang,
        "language_name": lang_info["name"],
        "source": "openai_simulated",
        "emergency": emergency_info,
        "is_emergency": is_emergency,
    }
