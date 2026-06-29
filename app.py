import os
import sqlite3
import zipfile
import io
import time
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_file, session, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'manga_gizli_anahtar_123'

# Maksimum 500 MB dosya yükleme izni
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS_IMG = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_EXTENSIONS_TXT = {'txt'}

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def get_db():
    # timeout=30 ile canlı sunuculardaki veritabanı kilitlenme hataları engellenir
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'covers'), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'profiles'), exist_ok=True)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, roles TEXT NOT NULL, profile_pic TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, cover_filename TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS chapters (id INTEGER PRIMARY KEY AUTOINCREMENT, series_id INTEGER, chapter_number INTEGER, source_link TEXT, status TEXT, assigned_to INTEGER, FOREIGN KEY(series_id) REFERENCES series(id), FOREIGN KEY(assigned_to) REFERENCES users(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER, stage TEXT, uploader_id INTEGER, filename TEXT, filepath TEXT, uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS task_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, stage TEXT, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # averisadmin kullanıcısı yoksa otomatik ekle
    cursor.execute('SELECT * FROM users WHERE username = ?', ('averisadmin',))
    if not cursor.fetchone():
        default_pw = generate_password_hash('admin123')
        cursor.execute('INSERT INTO users (username, password, roles, profile_pic) VALUES (?, ?, ?, ?)', ('averisadmin', default_pw, 'Controller', None))

    conn.commit()
    conn.close()

# Sunucu her uyandığında veritabanını sağlama al
init_db()

PIPELINE = ['PENDING_TRANSLATION', 'PENDING_CLEANING', 'PENDING_TYPESETTING', 'PENDING_PROOFREADING', 'PENDING_PUBLISHING', 'PUBLISHED']
ROLE_MAP = {'PENDING_TRANSLATION': 'Translator', 'PENDING_CLEANING': 'Cleaner', 'PENDING_TYPESETTING': 'Typesetter', 'PENDING_PROOFREADING': 'Proofreader', 'PENDING_PUBLISHING': 'Controller'}

@app.route('/kurtar')
def kurtar():
    try:
        init_db()
        conn = get_db()
        cursor = conn.cursor()
        default_pw = generate_password_hash('admin123')
        cursor.execute('SELECT * FROM users WHERE username = ?', ('averisadmin',))
        if cursor.fetchone():
            cursor.execute('UPDATE users SET password = ?, roles = ? WHERE username = ?', (default_pw, 'Controller', 'averisadmin'))
        else:
            cursor.execute('INSERT INTO users (username, password, roles, profile_pic) VALUES (?, ?, ?, ?)', ('averisadmin', default_pw, 'Controller', None))
        conn.commit()
        conn.close()
        return "Sistem Başarıyla Sıfırlandı! K.Adı: averisadmin | Şifre: admin123"
    except Exception as e:
        return f"Hata: {str(e)}"

@app.route('/')
def index(): return render_template('index.html')

@app.route('/covers/<filename>')
def serve_cover(filename): return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'covers'), filename)

@app.route('/profiles/<filename>')
def serve_profile(filename): return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), filename)

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({'error': 'Geçersiz istek verisi'}), 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (data['username'],))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password'], data['password']):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['roles'] = user['roles']
            session['profile_pic'] = user['profile_pic']
            return jsonify({'success': True})
        return jsonify({'error': 'Hatalı kullanıcı adı veya şifre!'}), 401
    except Exception as e:
        return jsonify({'error': f'Sunucu Hatası: {str(e)}'}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me', methods=['GET'])
def get_me():
    if 'user_id' not in session: return jsonify({'error': 'Giriş yapılmadı'}), 401
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT username, roles, profile_pic FROM users WHERE id = ?', (session['user_id'],))
        user = cursor.fetchone()
        conn.close()
        if not user: return jsonify({'error': 'Kullanıcı bulunamadı'}), 401
        return jsonify({'id': session['user_id'], 'username': user['username'], 'roles': user['roles'], 'profile_pic': user['profile_pic']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    user_id = session['user_id']
    new_username = request.form.get('username')
    avatar = request.files.get('avatar')
    conn = get_db()
    cursor = conn.cursor()

    if avatar and allowed_file(avatar.filename, ALLOWED_EXTENSIONS_IMG):
        timestamp = int(time.time())
        filename = secure_filename(f"user_{user_id}_{timestamp}_{avatar.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles', filename)
        avatar.save(filepath)
        cursor.execute('UPDATE users SET profile_pic = ? WHERE id = ?', (filename, user_id))

    if new_username:
        try: cursor.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, user_id))
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': 'Bu isim zaten kullanılıyor!'}), 400

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/profile/avatar', methods=['DELETE'])
def delete_avatar():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET profile_pic = NULL WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''SELECT u.id, u.username, u.profile_pic, th.stage, COUNT(th.id) as count FROM users u LEFT JOIN task_history th ON u.id = th.user_id GROUP BY u.id, th.stage''')
    rows = cursor.fetchall()
    stats = {}
    for r in rows:
        uid = r['id']
        if uid not in stats: stats[uid] = {'username': r['username'], 'profile_pic': r['profile_pic'], 'tasks': {}}
        if r['stage']: stats[uid]['tasks'][r['stage']] = r['count']
    conn.close()
    return jsonify(list(stats.values()))

@app.route('/api/data', methods=['GET'])
def get_data():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''SELECT c.id, c.chapter_number, c.source_link, c.status, c.assigned_to, s.title as series_title, s.cover_filename, u.username as assignee_name FROM chapters c JOIN series s ON c.series_id = s.id LEFT JOIN users u ON c.assigned_to = u.id''')
    chapters = [dict(row) for row in cursor.fetchall()]
    for ch in chapters:
        cursor.execute('''SELECT f.id, f.stage, f.filename, f.uploaded_at, u.username as uploader_name FROM files f LEFT JOIN users u ON f.uploader_id = u.id WHERE f.chapter_id = ?''', (ch['id'],))
        ch['files'] = [dict(row) for row in cursor.fetchall()]
    cursor.execute('SELECT id, username, roles, profile_pic FROM users')
    users = [dict(row) for row in cursor.fetchall()]
    cursor.execute('SELECT id, title FROM series')
    series = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'chapters': chapters, 'users': users, 'series': series})

@app.route('/api/admin/users', methods=['POST'])
def add_user():
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    data = request.json
    roles_str = ','.join(data['roles'])
    hashed_pw = generate_password_hash(data['password'])
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password, roles) VALUES (?, ?, ?)', (data['username'], hashed_pw, roles_str))
        conn.commit()
    except sqlite3.IntegrityError: return jsonify({'error': 'Bu kullanıcı adı zaten var'}), 400
    finally: conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    if user_id == session.get('user_id'): return jsonify({'error': 'Kendi hesabınızı silemezsiniz!'}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE chapters SET assigned_to = NULL WHERE assigned_to = ?', (user_id,))
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:user_id>/roles', methods=['PUT'])
def update_user_roles(user_id):
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    roles_str = ','.join(request.json['roles'])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET roles = ? WHERE id = ?', (roles_str, user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/series', methods=['POST'])
def add_series():
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    title = request.form.get('title')
    cover = request.files.get('cover')
    if not title or not cover or not allowed_file(cover.filename, ALLOWED_EXTENSIONS_IMG): return jsonify({'error': 'Geçersiz başlık veya kapak'}), 400
    filename = secure_filename(cover.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', filename)
    cover.save(filepath)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO series (title, cover_filename) VALUES (?, ?)', (title, filename))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/chapters', methods=['POST'])
def add_chapter():
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chapters (series_id, chapter_number, source_link, status, assigned_to) VALUES (?, ?, ?, "PENDING_TRANSLATION", NULL)', (data['series_id'], data['chapter_number'], data['source_link']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/claim/<int:chapter_id>', methods=['POST'])
def claim_chapter(chapter_id):
    user_id = session.get('user_id')
    user_roles = session.get('roles', '').split(',')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT status, assigned_to FROM chapters WHERE id = ?', (chapter_id,))
    chapter = cursor.fetchone()
    if not chapter or chapter['assigned_to'] is not None: return jsonify({'error': 'Bölüm bulunamadı veya alınmış'}), 400
    req_role = ROLE_MAP.get(chapter['status'])
    if 'Controller' not in user_roles and req_role not in user_roles: return jsonify({'error': 'Yetkisiz departman'}), 403
    cursor.execute('UPDATE chapters SET assigned_to = ? WHERE id = ?', (user_id, chapter_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/release/<int:chapter_id>', methods=['POST'])
def release_chapter(chapter_id):
    user_id = session.get('user_id')
    user_roles = session.get('roles', '').split(',')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT assigned_to FROM chapters WHERE id = ?', (chapter_id,))
    chapter = cursor.fetchone()
    if not chapter or (chapter['assigned_to'] != user_id and 'Controller' not in user_roles): return jsonify({'error': 'Bunu bırakmaya yetkiniz yok'}), 403
    cursor.execute('UPDATE chapters SET assigned_to = NULL WHERE id = ?', (chapter_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/upload/<int:chapter_id>', methods=['POST'])
def upload_files(chapter_id):
    user_id = session.get('user_id')
    user_roles = session.get('roles', '').split(',')
    uploaded_files = request.files.getlist('files')
    if not uploaded_files or uploaded_files[0].filename == '': return jsonify({'error': 'Dosya seçilmedi'}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT status, assigned_to FROM chapters WHERE id = ?', (chapter_id,))
    chapter = cursor.fetchone()
    if not chapter or (chapter['assigned_to'] != int(user_id) and 'Controller' not in user_roles): return jsonify({'error': 'Yetkisiz yükleme'}), 403
    stage = chapter['status']
    ch_dir = os.path.join(app.config['UPLOAD_FOLDER'], f'chapter_{chapter_id}', stage)
    os.makedirs(ch_dir, exist_ok=True)
    success_count = 0
    for file in uploaded_files:
        ext_ok = False
        if stage == 'PENDING_TRANSLATION': ext_ok = allowed_file(file.filename, ALLOWED_EXTENSIONS_TXT)
        elif stage in ['PENDING_CLEANING', 'PENDING_TYPESETTING', 'PENDING_PROOFREADING']: ext_ok = allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG)
        if 'Controller' in user_roles: ext_ok = True
        if ext_ok:
            filename = secure_filename(file.filename)
            filepath = os.path.join(ch_dir, filename)
            file.save(filepath)
            cursor.execute('INSERT INTO files (chapter_id, stage, uploader_id, filename, filepath) VALUES (?, ?, ?, ?, ?)', (chapter_id, stage, user_id, filename, filepath))
            success_count += 1
    conn.commit()
    conn.close()
    if success_count == 0: return jsonify({'error': 'Seçilen dosyaların formatı uyumsuz.'}), 400
    return jsonify({'success': True, 'count': success_count})

@app.route('/api/chapters/submit/<int:chapter_id>', methods=['POST'])
def submit_chapter(chapter_id):
    user_roles = session.get('roles', '').split(',')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT status, assigned_to FROM chapters WHERE id = ?', (chapter_id,))
    chapter = cursor.fetchone()
    stage = chapter['status']
    if 'Controller' not in user_roles and stage != 'PENDING_PROOFREADING':
        cursor.execute('SELECT count(*) as c FROM files WHERE chapter_id = ? AND stage = ?', (chapter_id, stage))
        if cursor.fetchone()['c'] == 0: return jsonify({'error': 'Dosya yüklemek zorunludur!'}), 400
    credit_user = chapter['assigned_to'] if chapter['assigned_to'] else session['user_id']
    if stage != 'PENDING_PUBLISHING':
        cursor.execute('INSERT INTO task_history (user_id, stage) VALUES (?, ?)', (credit_user, stage))
    next_idx = PIPELINE.index(stage) + 1
    next_stage = PIPELINE[next_idx] if next_idx < len(PIPELINE) else 'PUBLISHED'
    cursor.execute('UPDATE chapters SET status = ?, assigned_to = NULL WHERE id = ?', (next_stage, chapter_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/download/<int:chapter_id>/<stage_filter>', methods=['GET'])
def download_zip(chapter_id, stage_filter):
    conn = get_db()
    cursor = conn.cursor()
    if stage_filter == 'ALL': cursor.execute('SELECT filename, filepath FROM files WHERE chapter_id = ?', (chapter_id,))
    else: cursor.execute('SELECT filename, filepath FROM files WHERE chapter_id = ? AND stage = ?', (chapter_id, stage_filter))
    files = cursor.fetchall()
    conn.close()
    if not files: return "Dosya bulunamadı.", 404
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if os.path.exists(f['filepath']): zf.write(f['filepath'], f['filename'])
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=f"bolum_{chapter_id}_{stage_filter}.zip")