import sqlite3
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid

app = Flask(__name__)
app.secret_key = 'superseri_manga_key_123'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROFILE_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles')
app.config['COVER_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'covers')
app.config['CHAPTER_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'chapters')
app.config['DB_NAME'] = 'database.db'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_FOLDER'], exist_ok=True)
os.makedirs(app.config['COVER_FOLDER'], exist_ok=True)
os.makedirs(app.config['CHAPTER_FOLDER'], exist_ok=True)

default_profile = os.path.join('static', 'profil.png')
if os.path.exists(default_profile) and not os.path.exists(os.path.join(app.config['PROFILE_FOLDER'], 'profil.png')):
    import shutil
    shutil.copy(default_profile, os.path.join(app.config['PROFILE_FOLDER'], 'profil.png'))

def get_db_connection():
    conn = sqlite3.connect(app.config['DB_NAME'])
    conn.row_factory = sqlite3.Row
    return conn

def db_query(query, args=(), one=False):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    conn.commit()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def db_execute(query, args=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, args)
    conn.commit()
    conn.close()

def init_db():
    try:
        get_db_connection() 
    except:
        return 
    db_execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        roles TEXT NOT NULL,
        profile_pic TEXT
    )''')
    db_execute('''CREATE TABLE IF NOT EXISTS series (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT UNIQUE NOT NULL,
        cover_filename TEXT
    )''')
    db_execute('''CREATE TABLE IF NOT EXISTS chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        series_id INTEGER NOT NULL,
        chapter_number INTEGER NOT NULL,
        source_link TEXT,
        status TEXT DEFAULT 'PENDING_TRANSLATION',
        cleaner_id INTEGER,
        proofreader_id INTEGER,
        assigned_to INTEGER,
        is_cleaned INTEGER DEFAULT 0,
        is_proofread INTEGER DEFAULT 0,
        UNIQUE(series_id, chapter_number),
        FOREIGN KEY (series_id) REFERENCES series(id),
        FOREIGN KEY (cleaner_id) REFERENCES users(id),
        FOREIGN KEY (proofreader_id) REFERENCES users(id),
        FOREIGN KEY (assigned_to) REFERENCES users(id)
    )''')
    db_execute('''CREATE TABLE IF NOT EXISTS chapter_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        stage TEXT NOT NULL,
        filename TEXT NOT NULL,
        uploader_id INTEGER NOT NULL,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (chapter_id) REFERENCES chapters(id),
        FOREIGN KEY (uploader_id) REFERENCES users(id)
    )''')
    create_super_user()

def create_super_user():
    super_user = db_query('SELECT * FROM users WHERE username = ?', ('Averis',), one=True)
    if not super_user:
        hashed_password = generate_password_hash('181725')
        db_execute('INSERT INTO users (username, password, roles) VALUES (?, ?, ?)', ('Averis', hashed_password, 'Controller'))
        print("Süper kullanıcı 'Averis' başarıyla oluşturuldu.")

with app.app_context():
    init_db()

def get_current_user():
    if 'user_id' not in session: return None
    user = db_query('SELECT * FROM users WHERE id = ?', (session['user_id'],), one=True)
    return user

def require_role(role):
    def decorator(f):
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if not user or role not in user['roles'].split(','):
                return jsonify({'error': 'Unauthorized'}), 403
            return f(*args, **kwargs)
        wrapped.__name__ = f.__name__
        return wrapped
    return decorator

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/profiles/<filename>')
def profile_pic(filename):
    return send_from_directory(app.config['PROFILE_FOLDER'], filename)

@app.route('/covers/<filename>')
def cover_pic(filename):
    return send_from_directory(app.config['COVER_FOLDER'], filename)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = db_query('SELECT * FROM users WHERE username = ?', (data['username'],), one=True)
    if user and check_password_hash(user['password'], data['password']):
        session['user_id'] = user['id']
        return jsonify({'success': True})
    return jsonify({'error': 'Geçersiz kullanıcı adı veya şifre'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'success': True})

@app.route('/api/me')
def me():
    user = get_current_user()
    if user:
        return jsonify({
            'id': user['id'],
            'username': user['username'],
            'roles': user['roles'],
            'profile_pic': user['profile_pic']
        })
    return jsonify({'error': 'Not logged in'}), 401

@app.route('/api/data')
def get_data():
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute('SELECT id, username, roles, profile_pic FROM users WHERE LOWER(username) != ?', ('averis',))
    users_list = [dict(row) for row in cur.fetchall()]

    cur.execute('SELECT * FROM series')
    series_list = [dict(row) for row in cur.fetchall()]

    cur.execute('''
        SELECT 
            chapters.*, 
            series.title AS series_title, 
            series.cover_filename AS cover_filename,
            assignee.username AS assignee_name,
            cleaner.username AS cleaner_name,
            proofreader.username AS proofreader_name
        FROM chapters
        JOIN series ON chapters.series_id = series.id
        LEFT JOIN users AS assignee ON chapters.assigned_to = assignee.id
        LEFT JOIN users AS cleaner ON chapters.cleaner_id = cleaner.id
        LEFT JOIN users AS proofreader ON chapters.proofreader_id = proofreader.id
    ''')
    chapters_list = []
    for row in cur.fetchall():
        ch = dict(row)
        # NULL HATASI DÜZELTMESİ (Eski eklenmiş null olanları da onarır)
        if not ch['status']:
            ch['status'] = 'PENDING_TRANSLATION'
            
        cur.execute('''
            SELECT chapter_files.*, uploader.username AS uploader_name
            FROM chapter_files
            JOIN users AS uploader ON chapter_files.uploader_id = uploader.id
            WHERE chapter_id = ?
        ''', (ch['id'],))
        ch['files'] = [dict(f_row) for f_row in cur.fetchall()]
        chapters_list.append(ch)

    conn.close()
    return jsonify({'users': users_list, 'series': series_list, 'chapters': chapters_list})

@app.route('/api/profile', methods=['POST'])
def update_profile():
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    
    username = request.form.get('username')
    avatar_file = request.files.get('avatar')

    if not username: return jsonify({'error': 'İsim gerekli'}), 400
    if user['username'] == 'Averis' and username != 'Averis':
        return jsonify({'error': 'Süper yönetici ismi değiştirilemez'}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if avatar_file:
            ext = os.path.splitext(avatar_file.filename)[1]
            filename = f"user_{user['id']}{ext}"
            filepath = os.path.join(app.config['PROFILE_FOLDER'], filename)
            avatar_file.save(filepath)
            cur.execute('UPDATE users SET username = ?, profile_pic = ? WHERE id = ?', (username, filename, user['id']))
        else:
            cur.execute('UPDATE users SET username = ? WHERE id = ?', (username, user['id']))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Bu kullanıcı adı zaten alınmış'}), 400
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/profile/avatar', methods=['DELETE'])
def delete_profile_avatar():
    user = get_current_user()
    if not user or not user['profile_pic']: return jsonify({'error': 'Unauthorized'}), 403
    
    if user['username'] == 'Averis':
        return jsonify({'error': 'Süper yönetici profil resmi silinemez'}), 403

    filepath = os.path.join(app.config['PROFILE_FOLDER'], user['profile_pic'])
    if os.path.exists(filepath):
        os.remove(filepath)
    
    db_execute('UPDATE users SET profile_pic = NULL WHERE id = ?', (user['id'],))
    return jsonify({'success': True})

@app.route('/api/stats')
def get_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('SELECT id, username, profile_pic FROM users WHERE LOWER(username) != ?', ('averis',))
    users_list = []
    for row in cur.fetchall():
        u = dict(row)
        u['tasks'] = {'PENDING_TRANSLATION': 0, 'PENDING_CLEANING': 0, 'PENDING_PROOFREADING': 0, 'PENDING_TYPESETTING': 0}
        
        cur.execute('SELECT stage, count(*) FROM chapter_files WHERE uploader_id = ? GROUP BY stage', (u['id'],))
        for stage, count in cur.fetchall():
            if stage in u['tasks']: u['tasks'][stage] = count
        
        users_list.append(u)
    conn.close()
    return jsonify(users_list)

@app.route('/api/chapters/claim/<int:chapter_id>/<task>', methods=['POST'])
def claim_chapter(chapter_id, task):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    my_roles = user['roles'].split(',')
    
    # DÜZELTME: Eğer kullanıcı Kontrolcü (Controller) ise veya ilgili role sahipse görevi alabilir.
    if task not in ROLE_MAP_TASK or (ROLE_MAP_TASK[task] not in my_roles and 'Controller' not in my_roles):
        return jsonify({'error': 'Bu görev için yetkiniz yok'}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    ch = cur.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,)).fetchone()
    
    if task == 'CLEANING':
        if ch['cleaner_id']: return jsonify({'error': 'Görev zaten alınmış'}), 400
        cur.execute('UPDATE chapters SET cleaner_id = ? WHERE id = ?', (user['id'], chapter_id))
    elif task == 'PROOFREADING':
        if ch['proofreader_id']: return jsonify({'error': 'Görev zaten alınmış'}), 400
        cur.execute('UPDATE chapters SET proofreader_id = ? WHERE id = ?', (user['id'], chapter_id))
    else: 
        if ch['assigned_to']: return jsonify({'error': 'Görev zaten alınmış'}), 400
        cur.execute('UPDATE chapters SET assigned_to = ? WHERE id = ?', (user['id'], chapter_id))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/release/<int:chapter_id>/<task>', methods=['POST'])
def release_chapter(chapter_id, task):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor()
    ch = cur.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,)).fetchone()
    
    if task == 'CLEANING' and ch['cleaner_id'] == user['id']:
        cur.execute('UPDATE chapters SET cleaner_id = NULL WHERE id = ?', (chapter_id,))
    elif task == 'PROOFREADING' and ch['proofreader_id'] == user['id']:
        cur.execute('UPDATE chapters SET proofreader_id = NULL WHERE id = ?', (chapter_id,))
    elif task != 'CLEANING' and task != 'PROOFREADING' and ch['assigned_to'] == user['id']:
        cur.execute('UPDATE chapters SET assigned_to = NULL WHERE id = ?', (chapter_id,))
    else:
        return jsonify({'error': 'Bu görevi bırakamazsınız'}), 403

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/upload/<int:chapter_id>/<task>', methods=['POST'])
def upload_chapter_files(chapter_id, task):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    
    files = request.files.getlist('files')
    if not files: return jsonify({'error': 'Dosya seçilmedi'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    stage = 'PENDING_' + task
    
    if user['username'] != 'Averis':
        ch = cur.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,)).fetchone()
        if not ch or (task == 'CLEANING' and ch['cleaner_id'] != user['id']) or (task == 'PROOFREADING' and ch['proofreader_id'] != user['id']) or (task != 'CLEANING' and task != 'PROOFREADING' and ch['assigned_to'] != user['id']):
             return jsonify({'error': 'Dosya yükleme yetkiniz yok'}), 403

    uploaded_files = []
    for f in files:
        if f.filename:
            filename = f"{stage}_{chapter_id}_{uuid.uuid4().hex}_{secure_filename(f.filename)}"
            f.save(os.path.join(app.config['CHAPTER_FOLDER'], filename))
            cur.execute('INSERT INTO chapter_files (chapter_id, stage, filename, uploader_id) VALUES (?, ?, ?, ?)', (chapter_id, stage, filename, user['id']))
            uploaded_files.append(filename)
    
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'files': uploaded_files})

@app.route('/api/chapters/submit/<int:chapter_id>/<task>', methods=['POST'])
def submit_chapter_stage(chapter_id, task):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor()
    ch = cur.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,)).fetchone()

    if user['username'] != 'Averis':
        if not ch or (task == 'CLEANING' and ch['cleaner_id'] != user['id']) or (task == 'PROOFREADING' and ch['proofreader_id'] != user['id']) or (task != 'CLEANING' and task != 'PROOFREADING' and ch['assigned_to'] != user['id']):
             return jsonify({'error': 'İlerletme yetkiniz yok'}), 403

    stage = 'PENDING_' + task
    if task != 'PUBLISHING':
        file_check = cur.execute('SELECT count(id) FROM chapter_files WHERE chapter_id = ? AND stage = ?', (chapter_id, stage)).fetchone()[0]
        if file_check == 0:
            return jsonify({'error': 'Önce bu aşama için dosya yüklemelisiniz'}), 400

    next_status = ''
    updates = {}
    if task == 'TRANSLATION':
        next_status = 'PENDING_PARALLEL'
        updates = {'assigned_to': None}
    elif task == 'CLEANING':
        updates = {'is_cleaned': 1, 'cleaner_id': None}
        if ch['is_proofread']: next_status = 'PENDING_TYPESETTING'
    elif task == 'PROOFREADING':
        updates = {'is_proofread': 1, 'proofreader_id': None}
        if ch['is_cleaned']: next_status = 'PENDING_TYPESETTING'
    elif task == 'TYPESETTING':
        next_status = 'PENDING_PUBLISHING'
        updates = {'assigned_to': None}
    elif task == 'PUBLISHING':
        if 'Controller' not in user['roles'].split(','):
            return jsonify({'error': 'Yetkisiz'}), 403
        next_status = 'PUBLISHED'
        updates = {'assigned_to': None}
        last_file = cur.execute('SELECT filename FROM chapter_files WHERE chapter_id = ? AND stage = ? ORDER BY upload_time DESC LIMIT 1', (chapter_id, stage)).fetchone()
        if last_file:
             cur.execute('INSERT INTO chapter_files (chapter_id, stage, filename, uploader_id) VALUES (?, ?, ?, ?)', (chapter_id, 'PUBLISHED', last_file['filename'], user['id']))

    set_query = "status = ?"
    if next_status:
        if ch['status'] == 'PENDING_PARALLEL' and next_status == 'PENDING_TYPESETTING':
            pass 
        elif next_status:
             pass
    else: 
        set_query = "status = status" 
        next_status = ch['status']

    update_str = ", ".join([f"{k} = NULL" if v is None else f"{k} = ?" for k, v in updates.items()])
    update_vals = [v for k,v in updates.items() if v is not None]

    cur.execute(f'UPDATE chapters SET status = ?, {update_str} WHERE id = ?', (next_status, *update_vals, chapter_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/chapters/download/<int:chapter_id>/<stage>')
def download_chapter_files(chapter_id, stage):
    user = get_current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    query = 'SELECT filename FROM chapter_files WHERE chapter_id = ?'
    if stage != 'ALL': query += ' AND stage = ?'
    else: query += ' AND stage != "PUBLISHED"' 
    
    args = (chapter_id,) if stage == 'ALL' else (chapter_id, stage)
    files = cur.execute(query, args).fetchall()
    conn.close()

    if not files: return jsonify({'error': 'Dosya bulunamadı'}), 404

    if len(files) == 1:
        return send_from_directory(app.config['CHAPTER_FOLDER'], files[0]['filename'])
    else:
        return jsonify({'error': 'Çoklu dosya indirme ZIP altyapısı bu sürümde yok'}), 501


@app.route('/api/admin/users', methods=['POST'])
@require_role('Controller')
def create_user_api():
    data = request.json
    if not data['username'] or not data['password'] or not data['roles']: return jsonify({'error': 'Eksik bilgi'}), 400
    
    hashed_password = generate_password_hash(data['password'])
    roles_str = ','.join(data['roles'])
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (username, password, roles) VALUES (?, ?, ?)', (data['username'], hashed_password, roles_str))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Bu kullanıcı adı zaten alınmış'}), 400
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:user_id>/roles', methods=['PUT'])
@require_role('Controller')
def update_user_roles_api(user_id):
    data = request.json
    roles_str = ','.join(data['roles'])
    
    user_check = db_query('SELECT * FROM users WHERE id = ?', (user_id,), one=True)
    if user_check and user_check['username'] == 'Averis':
        return jsonify({'error': 'Süper yönetici rolleri değiştirilemez'}), 403
        
    db_execute('UPDATE users SET roles = ? WHERE id = ?', (roles_str, user_id))
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@require_role('Controller')
def delete_user_api(user_id):
    current_user = get_current_user()
    if user_id == current_user['id']: return jsonify({'error': 'Kendi kendinizi silemezsiniz'}), 400
    
    user_check = db_query('SELECT * FROM users WHERE id = ?', (user_id,), one=True)
    if user_check and user_check['username'] == 'Averis':
        return jsonify({'error': 'Süper yönetici hesabı silinemez'}), 403
        
    db_execute('DELETE FROM users WHERE id = ?', (user_id,))
    return jsonify({'success': True})

@app.route('/api/admin/series', methods=['POST'])
@require_role('Controller')
def create_series_api():
    title = request.form.get('title')
    cover_file = request.files.get('cover')
    if not title or not cover_file: return jsonify({'error': 'Eksik bilgi'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO series (title) VALUES (?)', (title,))
        conn.commit()
        series_id = cur.lastrowid
        
        ext = os.path.splitext(cover_file.filename)[1]
        filename = f"series_{series_id}{ext}"
        filepath = os.path.join(app.config['COVER_FOLDER'], filename)
        cover_file.save(filepath)
        
        cur.execute('UPDATE series SET cover_filename = ? WHERE id = ?', (filename, series_id))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Bu seri zaten eklenmiş'}), 400
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/series/<int:series_id>', methods=['DELETE'])
@require_role('Controller')
def delete_series_api(series_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    series = cur.execute('SELECT cover_filename FROM series WHERE id = ?', (series_id,)).fetchone()
    if series and series['cover_filename']:
        try: os.remove(os.path.join(app.config['COVER_FOLDER'], series['cover_filename']))
        except: pass
        
    chapters = cur.execute('SELECT id FROM chapters WHERE series_id = ?', (series_id,)).fetchall()
    for ch in chapters:
        files = cur.execute('SELECT filename FROM chapter_files WHERE chapter_id = ?', (ch['id'],)).fetchall()
        for f in files:
            try: os.remove(os.path.join(app.config['CHAPTER_FOLDER'], f['filename']))
            except: pass
        cur.execute('DELETE FROM chapter_files WHERE chapter_id = ?', (ch['id'],))
        cur.execute('DELETE FROM chapters WHERE id = ?', (ch['id'],))
        
    cur.execute('DELETE FROM series WHERE id = ?', (series_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/chapters', methods=['POST'])
@require_role('Controller')
def create_chapter_api():
    data = request.json
    if not data.get('series_id') or not data.get('chapter_number'): 
        return jsonify({'error': 'Eksik bilgi: Seri ve Bölüm numarası zorunludur'}), 400
    
    source_link = data.get('source_link', '') 
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # NULL HATASI KESİN ÇÖZÜMÜ: status değerini 'PENDING_TRANSLATION' olarak zorla işliyoruz
        cur.execute('INSERT INTO chapters (series_id, chapter_number, source_link, status) VALUES (?, ?, ?, ?)', 
                    (data['series_id'], data['chapter_number'], source_link, 'PENDING_TRANSLATION'))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Bu seri için bu bölüm zaten havuza eklenmiş'}), 400
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/chapters/<int:chapter_id>', methods=['DELETE'])
@require_role('Controller')
def delete_chapter_api(chapter_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    files = cur.execute('SELECT filename FROM chapter_files WHERE chapter_id = ?', (chapter_id,)).fetchall()
    for f in files:
        try: os.remove(os.path.join(app.config['CHAPTER_FOLDER'], f['filename']))
        except: pass
    cur.execute('DELETE FROM chapter_files WHERE chapter_id = ?', (chapter_id,))
    cur.execute('DELETE FROM chapters WHERE id = ?', (chapter_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

ROLE_MAP_TASK = {
    'TRANSLATION': 'Translator',
    'CLEANING': 'Cleaner',
    'PROOFREADING': 'Proofreader',
    'TYPESETTING': 'Typesetter',
    'PUBLISHING': 'Controller'
}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)