# Imports 
import os 
import re
import difflib
import json
import io
from flask import Flask, render_template, request, jsonify, session, redirect, url_for # for the web app
from dotenv import load_dotenv
import httpx
from supabase import create_client, Client
from PyPDF2 import PdfReader # for pdf processing
from werkzeug.security import generate_password_hash, check_password_hash # for password hashing
from functools import wraps

# Loading environment variables like api keys (optional on Vercel, where env vars are set by the platform)
try:
    load_dotenv()
except Exception:
    pass
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initializing the Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev")

# starting the supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# Authentication decorators, used for login routes

def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    """Decorator to require student role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        if session.get('role') != 'student':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def teacher_required(f):
    """Decorator to require teacher role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        if session.get('role') != 'teacher':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


#helper functions

def extract_text_from_pdf(pdf_file):
    """Extract text from a PDF file and normalize it."""
    try:
        pdf_reader = PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        
        # making the text clearn by normalizing it
        text = text.replace('\n', ' ')
        
        # Remove extra spaces
        text = re.sub(r'\s+', ' ', text)
        
        # Split into sentences ending with . ! or ?
        sentences = re.split(r'([.!?]+)', text)
        
        # Rejoin sentences properly with their punctuation
        normalized_text = ""
        for i in range(0, len(sentences), 2):
            if i < len(sentences):
                sentence = sentences[i].strip()
                if i + 1 < len(sentences):
                    punctuation = sentences[i + 1].strip()
                    if sentence and punctuation:
                        normalized_text += sentence + punctuation + " "
                elif sentence:
                    normalized_text += sentence + " "
        
        return normalized_text.strip()
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return None

# normalizing the words
def normalize_words(s: str):
    """Lowercase, remove punctuation, and split into words."""
    clean = re.sub(r"[^\w\s]", "", s.lower())
    return clean.split()

# comparing target words to transcript words
def align_words(target_text: str, transcript_text: str):
    """
    Compares target passage and transcript.
    Returns which words were read correctly vs. misread, plus accuracy %.
    """
    t_words = normalize_words(target_text)
    r_words = normalize_words(transcript_text)

    sm = difflib.SequenceMatcher(a=t_words, b=r_words)
    result = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for w in t_words[i1:i2]:
                result.append({"word": w, "status": "ok"})
        else:
            for w in t_words[i1:i2]:
                result.append({"word": w, "status": "misread"})

    correct = sum(1 for w in result if w["status"] == "ok")
    acc = round(100.0 * correct / max(1, len(result)), 1)
    return {"words": result, "accuracy": acc}


# routes for html pages for flask app

@app.get("/")
def index():
    """Serves the main web page (login/signup page)."""
    # If already logged in, redirect to appropriate dashboard
    if 'user_id' in session:
        if session.get('role') == 'student':
            return redirect(url_for('student'))
        elif session.get('role') == 'teacher':
            return redirect(url_for('teacher'))
    return render_template("index.html")


@app.get("/teacher")
@teacher_required
def teacher():
    """Serves the teacher page."""
    return render_template("teacher.html")


@app.get("/student")
@student_required
def student():
    """Serves the student page."""
    return render_template("student.html")


@app.get("/assignment")
@student_required
def assignment():
    """Serves the assignment page."""
    return render_template("assignment.html")

# route for signing up a new user, sending to supabase
@app.post("/api/signup")
def signup():
    """Create a new user account."""
    try:
        data = request.get_json()
        full_name = data.get("full_name")
        email = data.get("email")
        password = data.get("password")
        role = data.get("role")
        
        if not all([full_name, email, password, role]):
            return jsonify({"error": "Missing required fields"}), 400
        
        if role not in ["student", "teacher"]:
            return jsonify({"error": "Invalid role"}), 400
        
        # Checking if user alr exists
        existing = supabase.table("users").select("*").eq("email", email).execute()
        if existing.data:
            return jsonify({"error": "Email already registered"}), 400
        
        # Hashing the password for better security
        password_hash = generate_password_hash(password)
        
        # Inserting user into database
        user_data = {
            "full_name": full_name,
            "email": email,
            "password_hash": password_hash,
            "role": role
        }
        
        result = supabase.table("users").insert(user_data).execute()
        user = result.data[0]
        
        # Set session
        session['user_id'] = user['id']
        session['full_name'] = user['full_name']
        session['email'] = user['email']
        session['role'] = user['role']
        #reutrns the user's role and name and success 
        return jsonify({
            "message": "Account created successfully",
            "role": user['role'],
            "full_name": user['full_name']
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for logging in a user, sending to supabase
@app.post("/api/login")
def login():
    """Log in an existing user."""
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400
        
        # Get user from database
        result = supabase.table("users").select("*").eq("email", email).execute()
        
        if not result.data:
            return jsonify({"error": "Invalid email or password"}), 401
        
        user = result.data[0]
        
        # Check password
        if not check_password_hash(user['password_hash'], password):
            return jsonify({"error": "Invalid email or password"}), 401
        
        # Set session
        session['user_id'] = user['id']
        session['full_name'] = user['full_name']
        session['email'] = user['email']
        session['role'] = user['role']
        
        return jsonify({
            "message": "Login successful",
            "role": user['role'],
            "full_name": user['full_name']
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for logging out a user
@app.post("/api/logout")
def logout():
    """Log out the current user."""
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200

# route for getting the current user
@app.get("/api/current-user")
def current_user():
    """Get the current logged-in user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    return jsonify({
        "user_id": session['user_id'],
        "full_name": session['full_name'],
        "email": session['email'],
        "role": session['role']
    }), 200

# route for using the whisper api to transcribe audio
@app.post("/api/transcribe")
def transcribe():
    """Send audio to OpenAI Whisper API and return transcript."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file received"}), 400

    audio_file = request.files["audio"]
    url = "https://api.openai.com/v1/audio/transcriptions"

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    files = {
        "file": (
            audio_file.filename or "audio.webm",
            audio_file.stream,
            audio_file.mimetype or "audio/webm"
        )
    }
    data = {"model": "whisper-1"}

    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, headers=headers, files=files, data=data)

    if r.status_code >= 400:
        return jsonify({"error": r.text}), 500

    out = r.json()
    return jsonify({"text": out.get("text", "")})

# route for evaluating the reading accuracy by comparing target passage to transcript
@app.post("/api/evaluate")
def evaluate():
    """Compares target passage vs. transcript and labels each word."""
    body = request.get_json(force=True)
    target = body.get("target", "")
    transcript = body.get("transcript", "")
    aligned = align_words(target, transcript)
    return jsonify(aligned)

#route for using the gpt api to generate encouragement, tips, and questions using prompt
@app.post("/api/coach")
def coach():
    """
    Calls GPT to produce:
      - encouragement message
      - pronunciation tips for misread words
      - two comprehension questions
    """
    body = request.get_json(force=True)
    target = body.get("target", "")
    transcript = body.get("transcript", "")
    misreads = body.get("misreads", [])
    grade_level = body.get("grade_level", "")
    
    # Create grade level description
    if grade_level:
        if grade_level == "K":
            grade_desc = "Kindergarten"
        elif grade_level == "1":
            grade_desc = "1st grade"
        elif grade_level == "2":
            grade_desc = "2nd grade"
        else:
            grade_desc = f"grade {grade_level}"
        tutor_desc = f"You are a kind reading tutor for a {grade_desc} student."
    else:
        tutor_desc = "You are a kind reading tutor."

    
    prompt = (
        f"{tutor_desc}\n"
        "Return ONLY a JSON object exactly like this:\n"
        "{\n"
        "  \"encouragement\": \"short praise\",\n"
        "  \"tips\": [ {\"word\": \"<misread word>\", \"tip\": \"short correction\"}, ... ],\n"
        "  \"questions\": [\"two short comprehension questions that can be answered only given the target text\"]\n"
        "}\n"
        "Do not skip any keys, even if empty.\n"
        "Do not use emojis in your response.\n\n"
        f"TARGET PASSAGE: {target}\n"
        f"TRANSCRIPT: {transcript}\n"
        f"MISREAD WORDS: {', '.join(misreads) if misreads else 'none'}"
    )

    print("PROMPT SENT TO GPT:\n", prompt)

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You speak simply and kindly to children."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "response_format": {"type": "json_object"}
    }

    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, headers=headers, json=payload)

    if r.status_code >= 400:
        print("COACH ERROR:", r.status_code, r.text)
        return jsonify({"error": "OpenAI API error"}), 500

    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content

        parsed.setdefault("encouragement", "Great reading!")
        parsed.setdefault("tips", [])
        parsed.setdefault("questions", [])

        print("COACH RESPONSE:", parsed)
        return jsonify(parsed)

    except Exception as e:
        print("Error parsing coach response:", e, r.text)
        fallback = {
            "encouragement": "Nice reading! Keep it up.",
            "tips": [],
            "questions": []
        }
        return jsonify(fallback)
    

# route for using the gpt api FOR TTS
@app.post("/api/tts")
def tts():
    """Convert corrected target passage to speech using OpenAI TTS."""
    
    body = request.get_json(force=True)
    text = body.get("text", "")

    if not text:
        return jsonify({"error": "Missing `text`"}), 400

    url = "https://api.openai.com/v1/audio/speech"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",  # you can change later
        "input": text
    }

    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, headers=headers, json=payload)

    if r.status_code >= 400:
        return jsonify({"error": r.text}), 500

    # return raw audio file so browser can play it
    return r.content, 200, {
        "Content-Type": "audio/mpeg"
    }

# route for creating a new assignment, and updating the database from teachers end
@app.post("/api/assignments")
def create_assignment():
    """Create a new assignment (teacher only)."""
    try:
        title = request.form.get("title")
        grade_level = request.form.get("grade_level")
        min_accuracy = request.form.get("min_accuracy", 80)
        pdf_file = request.files.get("pdf")
        
        extracted_text = None
        pdf_filename = None
        
        # Extract text from PDF if provided
        if pdf_file:
            pdf_filename = pdf_file.filename
            extracted_text = extract_text_from_pdf(pdf_file)
            
            if not extracted_text:
                return jsonify({"error": "Failed to extract text from PDF"}), 400
        
        assignment_data = {
            "title": title,
            "grade_level": grade_level,
            "text": extracted_text or "No text provided",
            "pdf_filename": pdf_filename,
            "min_accuracy": float(min_accuracy)
        }
        
        result = supabase.table("assignments").insert(assignment_data).execute()
        return jsonify(result.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for getting all assignments from the database on student page
@app.get("/api/assignments")
def get_assignments():
    """Get all assignments (for students)."""
    try:
        result = supabase.table("assignments").select("*").execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for getting a specific assignment by ID on student page
@app.get("/api/assignments/<int:assignment_id>")
def get_assignment(assignment_id):
    """Get a specific assignment by ID."""
    try:
        result = supabase.table("assignments").select("*").eq("id", assignment_id).execute()
        if result.data:
            return jsonify(result.data[0])
        return jsonify({"error": "Assignment not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for getting all submissions from the database on teacher page
@app.get("/api/submissions")
def get_submissions():
    """Get all submissions (for teacher)."""
    try:
        result = supabase.table("submissions").select("*").order("created_at", desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for getting a specific submission by assignment ID on teacher page
@app.get("/api/submissions/<int:assignment_id>")
def get_submission(assignment_id):
    """Get submission for a specific assignment."""
    try:
        result = supabase.table("submissions").select("*").eq("assignment_id", assignment_id).execute()
        if result.data:
            return jsonify(result.data[0])
        return jsonify({"error": "No submission found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for creating or updating a submission with accuracy and words missed so the teacher can see it
@app.post("/api/submissions")
@login_required
def create_or_update_submission():
    """Create or update a submission with accuracy and words missed."""
    try:
        data = request.get_json()
        assignment_id = data.get("assignment_id")
        accuracy = data.get("accuracy")
        words_missed = data.get("words_missed", [])
        submitted = data.get("submitted", False)
        
        # Use authenticated user's data
        user_id = session['user_id']
        student_name = session['full_name']
        
        # Check if submission already exists for this user and assignment
        existing = supabase.table("submissions").select("*").eq("assignment_id", assignment_id).eq("user_id", user_id).execute()
        
        if existing.data:
            # Update existing submission
            result = supabase.table("submissions").update({
                "accuracy": accuracy,
                "words_missed": words_missed,
                "submitted": submitted
            }).eq("assignment_id", assignment_id).eq("user_id", user_id).execute()
            return jsonify(result.data[0])
        else:
            # Create new submission
            result = supabase.table("submissions").insert({
                "assignment_id": assignment_id,
                "user_id": user_id,
                "student_name": student_name,
                "accuracy": accuracy,
                "words_missed": words_missed,
                "submitted": submitted
            }).execute()
            return jsonify(result.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route for submitting an assignment, marking it as submitted so the teacher can see it
@app.post("/api/submit-assignment")
@login_required
def submit_assignment():
    """Submit an assignment (marks it as submitted)."""
    try:
        data = request.get_json()
        assignment_id = data.get("assignment_id")
        
        # Use authenticated user's data
        user_id = session['user_id']
        
        # Check if submission exists for this user and assignment
        existing = supabase.table("submissions").select("*").eq("assignment_id", assignment_id).eq("user_id", user_id).execute()
        
        if not existing.data:
            return jsonify({"error": "No submission found for this assignment"}), 404
        
        # Update to mark as submitted
        result = supabase.table("submissions").update({
            "submitted": True
        }).eq("assignment_id", assignment_id).eq("user_id", user_id).execute()
        
        return jsonify(result.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500



#running the actual app
if __name__ == "__main__":
    app.run(debug=True, port=5001)