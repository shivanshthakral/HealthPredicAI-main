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
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "900"))
OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.6"))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Global HTTP Session for connection reuse and performance optimization
_http_session = requests.Session() if REQUESTS_OK else None

_last_openai_key = None
_client = None

def _get_openai_client():
    global _client, _last_openai_key
    current_key = os.environ.get("OPENAI_API_KEY", "")
    if current_key != _last_openai_key:
        _last_openai_key = current_key
        if current_key:
            _client = OpenAI(api_key=current_key)
        else:
            _client = None
    return _client

_last_gemini_key = None
IS_GEMINI_KEY_VALID = True
WORKING_PROVIDER = None

def _check_gemini_key_update():
    global IS_GEMINI_KEY_VALID, _last_gemini_key
    current_key = os.environ.get("GEMINI_API_KEY", "")
    if current_key != _last_gemini_key:
        IS_GEMINI_KEY_VALID = True
        _last_gemini_key = current_key


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
            "\n\n[CRITICAL] MEDICAL EMERGENCY DETECTED:\n"
            "- Open your response with an immediate, clear emergency warning.\n"
            "- Direct the user to call local emergency services immediately (India: 108 Ambulance / 112 Emergency; US: 911; UK: 999; EU: 112).\n"
            "- Provide 2-4 simple, actionable first-aid steps.\n"
            "- Do not ask clarifying questions first."
        )

    return f"""You are the HealthPredict AI Clinical Copilot, a world-class, medically-accurate, and empathetic AI clinical decision partner.

Capabilities:
- Symptom Analysis: Help patients understand symptoms and potential medical causes (as general possibilities, not definitive diagnoses).
- Medical Education: Explain diseases, conditions, risk factors, and anatomy in simple terms.
- Report Explanation: Explain lab results, medical reports, or vital readings and reference ranges.
- Drug Interaction Guidance: Provide general safety information, common side effects, and potential drug interactions.
- Lifestyle Guidance: Suggest diet, nutrition, fitness, and habits tailored to health conditions.
- Wellness Coaching: Provide guidance on stress management, sleep, and mental well-being with compassion.

Strict Safety Rules:
1. Never claim diagnosis certainty. Always frame possibilities as options to discuss with a physician.
2. Encourage professional consultation. Advise consulting a doctor for definitive diagnosis and treatment.
3. Be concise. Keep replies structured, using clear sections or bullet points. Avoid overwhelming the user.
4. Be medically accurate. Do not invent drug names, dosages, or medical facts. Never tell a user to stop prescribed medication.
5. Use user language: The user's language is {lang_name} ({lang_native}). You MUST reply ENTIRELY in {lang_name}. If the user mixes languages (e.g. Hinglish), adopt the same mixed style for natural communication.
6. Suicidal/Self-Harm Ideation: Respond with immediate warmth and empathy, do not judge, provide helpline resources (e.g. India mental health helpline: 1860-2662-345), and urge them to connect with professionals.
7. End each clinical response with a brief medical disclaimer indicating this is for informational purposes only and a real doctor must be consulted.

{emergency_block}"""


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


def _sanitize_conversation_history(conversation_history, user_message="", image=None):
    """
    Sanitize conversation history for Google Gemini.
    Rules:
    - Must start with a 'user' turn.
    - Roles must strictly alternate between 'user' and 'model'.
    - Consecutive turns with the same role are merged.
    """
    sanitized = []
    for msg in conversation_history:
        role_in = msg.get("role", "user")
        role = "model" if role_in in ("bot", "model", "assistant") else "user"
        content = msg.get("content") or msg.get("text") or ""
        if not content.strip():
            continue

        if sanitized and sanitized[-1]["role"] == role:
            # Merge duplicate consecutive roles
            sanitized[-1]["parts"][0]["text"] += "\n" + content
        else:
            sanitized.append({
                "role": role,
                "parts": [{"text": content}]
            })

    # Ensure conversation starts with 'user'
    while sanitized and sanitized[0]["role"] == "model":
        sanitized.pop(0)

    # Append current user content
    current_parts = []
    if image and image.get("base64"):
        current_parts.append({
            "inline_data": {
                "mime_type": image.get("mime_type", "image/png"),
                "data": image.get("base64")
            }
        })
    current_parts.append({"text": user_message or "Please analyse this image."})

    if sanitized and sanitized[-1]["role"] == "user":
        # If last is user, merge parts
        sanitized[-1]["parts"].extend(current_parts)
    else:
        sanitized.append({
            "role": "user",
            "parts": current_parts
        })

    return sanitized[-10:]



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
    
    # Dynamically check if the environment key was updated
    _check_gemini_key_update()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    
    if not IS_GEMINI_KEY_VALID or not gemini_key or not REQUESTS_OK:
        reason = "GEMINI_API_KEY is not set" if not gemini_key else ("Gemini key marked invalid (returned 403 previously)" if not IS_GEMINI_KEY_VALID else "requests library missing")
        print(f"[CHAT_FALLBACK_REASON] Gemini bypassed. Reason: {reason}")
        print(f"[CHAT_PROVIDER] Using fallback provider (dynamic or simulated)")
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

    # Format history strictly according to Gemini requirements
    contents = _sanitize_conversation_history(conversation_history, user_message, image)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={gemini_key}"
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

    max_retries = 2
    timeout_seconds = 8
    last_err = None
    resp = None

    print(f"[CHAT_PROVIDER] Calling Google Gemini API (model: {GEMINI_MODEL})")

    for attempt in range(max_retries + 1):
        try:
            client_session = _http_session if _http_session else requests
            print("AI_PROVIDER=", "gemini-1.5-flash")
            print("OPENAI_KEY_PRESENT=", bool(os.environ.get("OPENAI_API_KEY")))
            print("GEMINI_KEY_PRESENT=", bool(os.environ.get("GEMINI_API_KEY")))
            print("Incoming message:", user_message)
            resp = client_session.post(url, json=payload, timeout=timeout_seconds)
            
            if resp.status_code == 403:
                IS_GEMINI_KEY_VALID = False
                err_msg = f"Gemini API returned 403 Forbidden: {resp.text}"
                print(f"[CHAT_FALLBACK_REASON] Gemini key auth failure: {err_msg}")
                raise RuntimeError("gemini_suspended_key_403")
            elif resp.status_code != 200:
                raise RuntimeError(f"gemini_http_{resp.status_code}: {resp.text[:300]}")
                
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt < max_retries:
                print(f"[Chatbot] Gemini request failed (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in 1s...")
                time.sleep(1)
            else:
                print(f"[CHAT_FALLBACK_REASON] Gemini failed after {max_retries + 1} attempts. Error: {e}")
                last_err = e
        except Exception as e:
            last_err = e
            break

    if resp is not None and resp.status_code == 200:
        res_json = resp.json()
        try:
            text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            print("AI response:", text)
            print(f"[CHAT_RESPONSE] Source: gemini ({GEMINI_MODEL}), Response: '{text[:100]}...'")
            return {
                "response": text,
                "detected_language": detected_lang,
                "language_name": lang_info["name"],
                "source": f"gemini ({GEMINI_MODEL})",
                "emergency": emergency_info,
                "is_emergency": is_emergency,
            }
        except (KeyError, IndexError) as e:
            print(f"[CHAT_FALLBACK_REASON] Gemini response format unexpected: {e}")
            last_err = RuntimeError(f"gemini_response_structure_unexpected: {e}, raw: {res_json}")

    # Fallback if request failed or response format was bad
    print(f"[CHAT_PROVIDER] Using fallback provider (dynamic or simulated)")
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

    # Log incoming request details
    print(f"[CHAT_REQUEST] Message: '{user_message}', Language: '{language}' (detected: '{detected_lang}'), History Turns: {len(conversation_history)}, Has Image: {image is not None}")

    # Fetch latest API keys and clients
    client = _get_openai_client()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    # 3. Guard: missing both API keys
    if client is None and not gemini_key:
        print("[CHAT_FALLBACK_REASON] Both OpenAI and Gemini API keys are missing in environment")
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

    # 4. System prompt
    system_prompt = _build_system_prompt(
        lang_info["name"], lang_info["native"], is_emergency
    )

    # Route: Try OpenAI first if configured
    if client is not None:
        print(f"[CHAT_PROVIDER] Calling OpenAI API (model: {OPENAI_MODEL})")
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(_format_history(conversation_history))
        messages.append({"role": "user", "content": _build_user_content(user_message, image)})

        last_error = None
        for attempt in range(3):
            try:
                # Apply 8-second timeout for responsive user experience
                print("AI_PROVIDER=", OPENAI_MODEL)
                print("OPENAI_KEY_PRESENT=", bool(os.environ.get("OPENAI_API_KEY")))
                print("GEMINI_KEY_PRESENT=", bool(os.environ.get("GEMINI_API_KEY")))
                print("Incoming message:", user_message)
                completion = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    temperature=OPENAI_TEMPERATURE,
                    max_tokens=OPENAI_MAX_TOKENS,
                    timeout=8
                )
                text = (completion.choices[0].message.content or "").strip()
                if not text:
                     raise RuntimeError("Empty response from OpenAI")

                print("AI response:", text)
                print(f"[CHAT_RESPONSE] Source: openai ({OPENAI_MODEL}), Response: '{text[:100]}...'")
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
                print(f"[CHAT_FALLBACK_REASON] OpenAI API rate limit / quota error: {e}")
                if "insufficient_quota" in str(e):
                    # Out of quota: break retry loop and fall back immediately
                    break
                wait = (attempt + 1) * 2
                print(f"[Chatbot] Rate limited — waiting {wait}s before retry")
                time.sleep(wait)
            except APIError as e:
                last_error = e
                print(f"[CHAT_FALLBACK_REASON] OpenAI API error: {e}")
                break
            except Exception as e:
                last_error = e
                print(f"[CHAT_FALLBACK_REASON] OpenAI unexpected error: {e}")
                break

        # If OpenAI failed/out-of-quota, fall back to Gemini if key exists
        if gemini_key:
            print("[Chatbot] OpenAI failed/rate-limited. Trying secondary provider Gemini...")
            return _chat_with_gemini(
                user_message, conversation_history, system_prompt,
                lang_info, is_emergency, emergency_info, detected_lang, image
            )
    else:
        # No OpenAI, call Gemini directly
        return _chat_with_gemini(
            user_message, conversation_history, system_prompt,
            lang_info, is_emergency, emergency_info, detected_lang, image
        )

    # 6. Fallback if everything else failed
    print(f"[CHAT_PROVIDER] Using fallback provider (dynamic or simulated)")
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
