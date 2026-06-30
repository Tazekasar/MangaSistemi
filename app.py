import os
import sqlite3
import zipfile
import io
import time
import shutil
import re  
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_file, session, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'manga_gizli_anahtar_123'

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
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'covers'), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'profiles'), exist_ok=True)

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, roles TEXT NOT NULL, profile_pic TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, cover_filename TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS chapters (id INTEGER PRIMARY KEY AUTOINCREMENT, series_id INTEGER, chapter_number INTEGER, source_link TEXT, status TEXT, assigned_to INTEGER, FOREIGN KEY(series_id) REFERENCES series(id), FOREIGN KEY(assigned_to) REFERENCES users(id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER, stage TEXT, uploader_id INTEGER, filename TEXT, filepath TEXT, uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS task_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, stage TEXT, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

        try:
            cursor.execute('ALTER TABLE chapters ADD COLUMN cleaner_id INTEGER')
            cursor.execute('ALTER TABLE chapters ADD COLUMN proofreader_id INTEGER')
            cursor.execute('ALTER TABLE chapters ADD COLUMN is_cleaned BOOLEAN DEFAULT 0')
            cursor.execute('ALTER TABLE chapters ADD COLUMN is_proofread BOOLEAN DEFAULT 0')
            conn.commit()
            cursor.execute("UPDATE chapters SET status = 'PENDING_PARALLEL', is_proofread = 1, cleaner_id = assigned_to, assigned_to = NULL WHERE status = 'PENDING_CLEANING'")
            cursor.execute("UPDATE chapters SET status = 'PENDING_PARALLEL', is_cleaned = 1, proofreader_id = assigned_to, assigned_to = NULL WHERE status = 'PENDING_PROOFREADING'")
            conn.commit()
        except sqlite3.OperationalError:
            pass 

        cursor.execute('SELECT * FROM users WHERE username = ?', ('averisadmin',))
        if not cursor.fetchone():
            default_pw = generate_password_hash('averis?yonetim')
            cursor.execute('INSERT INTO users (username, password, roles, profile_pic) VALUES (?, ?, ?, ?)', ('averisadmin', default_pw, 'Controller', None))

        conn.commit()
    except Exception as e:
        print("DB Init Hatası:", e)
    finally:
        conn.close()

init_db()

@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/covers/<filename>')
def serve_cover(filename): 
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'covers'), filename)

@app.route('/profiles/<filename>')
def serve_profile(filename): 
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), filename)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Geçersiz istek verisi'}), 400

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (data['username'],))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], data['password']):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['roles'] = user['roles']
            session['profile_pic'] = user['profile_pic']
            return jsonify({'success': True})
        return jsonify({'error': 'Hatalı kullanıcı adı veya şifre!'}), 401
    except Exception as e:
        return jsonify({'error': f'Sunucu Hatası: {str(e)}'}), 500
    finally:
        conn.close()

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me', methods=['GET'])
def get_me():
    if 'user_id' not in session: return jsonify({'error': 'Giriş yapılmadı'}), 401
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT username, roles, profile_pic FROM users WHERE id = ?', (session['user_id'],))
        user = cursor.fetchone()
        if not user: return jsonify({'error': 'Kullanıcı bulunamadı'}), 401
        return jsonify({'id': session['user_id'], 'username': user['username'], 'roles': user['roles'], 'profile_pic': user['profile_pic']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    user_id = session['user_id']
    new_username = request.form.get('username')
    avatar = request.files.get('avatar')
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        if avatar and allowed_file(avatar.filename, ALLOWED_EXTENSIONS_IMG):
            timestamp = int(time.time())
            filename = secure_filename(f"user_{user_id}_{timestamp}_{avatar.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles', filename)
            avatar.save(filepath)
            cursor.execute('UPDATE users SET profile_pic = ? WHERE id = ?', (filename, user_id))

        if new_username:
            try: 
                cursor.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, user_id))
            except sqlite3.IntegrityError:
                return jsonify({'error': 'Bu isim zaten kullanılıyor!'}), 400

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/profile/avatar', methods=['DELETE'])
def delete_avatar():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET profile_pic = NULL WHERE id = ?', (session['user_id'],))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/stats', methods=['GET'])
def get_stats():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''SELECT u.id, u.username, u.profile_pic, th.stage, COUNT(th.id) as count FROM users u LEFT JOIN task_history th ON u.id = th.user_id GROUP BY u.id, th.stage''')
        rows = cursor.fetchall()
        stats = {}
        for r in rows:
            uid = r['id']
            if uid not in stats: stats[uid] = {'username': r['username'], 'profile_pic': r['profile_pic'], 'tasks': {}}
            if r['stage']: stats[uid]['tasks'][r['stage']] = r['count']
        return jsonify(list(stats.values()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/data', methods=['GET'])
def get_data():
    if 'user_id' not in session: return jsonify({'error': 'Yetkisiz'}), 401
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.*, s.title as series_title, s.cover_filename, 
            u1.username as assignee_name, 
            u2.username as cleaner_name, 
            u3.username as proofreader_name 
            FROM chapters c 
            JOIN series s ON c.series_id = s.id 
            LEFT JOIN users u1 ON c.assigned_to = u1.id 
            LEFT JOIN users u2 ON c.cleaner_id = u2.id 
            LEFT JOIN users u3 ON c.proofreader_id = u3.id
        ''')
        chapters = [dict(row) for row in cursor.fetchall()]
        for ch in chapters:
            cursor.execute('''SELECT f.id, f.stage, f.filename, f.uploaded_at, u.username as uploader_name FROM files f LEFT JOIN users u ON f.uploader_id = u.id WHERE f.chapter_id = ?''', (ch['id'],))
            ch['files'] = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute('SELECT id, username, roles, profile_pic FROM users')
        users = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute('SELECT id, title FROM series')
        series = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({'chapters': chapters, 'users': users, 'series': series})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/users', methods=['POST'])
def add_user():
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    data = request.json
    roles_str = ','.join(data['roles'])
    hashed_pw = generate_password_hash(data['password'])
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (username, password, roles) VALUES (?, ?, ?)', (data['username'], hashed_pw, roles_str))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.IntegrityError: 
        return jsonify({'error': 'Bu kullanıcı adı zaten var'}), 400
    finally: 
        conn.close()

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    if user_id == session.get('user_id'): return jsonify({'error': 'Kendi hesabınızı silemezsiniz!'}), 400
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE chapters SET assigned_to = NULL WHERE assigned_to = ?', (user_id,))
        cursor.execute('UPDATE chapters SET cleaner_id = NULL WHERE cleaner_id = ?', (user_id,))
        cursor.execute('UPDATE chapters SET proofreader_id = NULL WHERE proofreader_id = ?', (user_id,))
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/users/<int:user_id>/roles', methods=['PUT'])
def update_user_roles(user_id):
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    roles_str = ','.join(request.json['roles'])
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET roles = ? WHERE id = ?', (roles_str, user_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/series', methods=['POST'])
def add_series():
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    title = request.form.get('title')
    cover = request.files.get('cover')
    if not title or not cover or not allowed_file(cover.filename, ALLOWED_EXTENSIONS_IMG): return jsonify({'error': 'Geçersiz başlık veya kapak'}), 400
    
    conn = get_db()
    try:
        cursor = conn.cursor()
        filename = secure_filename(cover.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', filename)
        cover.save(filepath)
        cursor.execute('INSERT INTO series (title, cover_filename) VALUES (?, ?)', (title, filename))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/chapters', methods=['POST'])
def add_chapter():
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz'}), 403
    data = request.json
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO chapters (series_id, chapter_number, source_link, status, assigned_to) VALUES (?, ?, ?, "PENDING_TRANSLATION", NULL)', (data['series_id'], data['chapter_number'], data['source_link']))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/chapters/claim/<int:chapter_id>/<task_type>', methods=['POST'])
def claim_chapter(chapter_id, task_type):
    user_id = session.get('user_id')
    user_roles = session.get('roles', '').split(',')
    ROLE_MAP_TASK = {'TRANSLATION': 'Translator', 'CLEANING': 'Cleaner', 'PROOFREADING': 'Proofreader', 'TYPESETTING': 'Typesetter', 'PUBLISHING': 'Controller'}
    req_role = ROLE_MAP_TASK.get(task_type, 'Controller')

    if 'Controller' not in user_roles and req_role not in user_roles:
        return jsonify({'error': 'Yetkisiz departman'}), 403

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
        chapter = cursor.fetchone()

        if not chapter: return jsonify({'error': 'Bulunamadı'}), 400

        if task_type == 'CLEANING':
            if chapter['cleaner_id'] is not None: return jsonify({'error': 'Bu görev alınmış'}), 400
            cursor.execute('UPDATE chapters SET cleaner_id = ? WHERE id = ?', (user_id, chapter_id))
        elif task_type == 'PROOFREADING':
            if chapter['proofreader_id'] is not None: return jsonify({'error': 'Bu görev alınmış'}), 400
            cursor.execute('UPDATE chapters SET proofreader_id = ? WHERE id = ?', (user_id, chapter_id))
        else:
            if chapter['assigned_to'] is not None: return jsonify({'error': 'Bu görev alınmış'}), 400
            cursor.execute('UPDATE chapters SET assigned_to = ? WHERE id = ?', (user_id, chapter_id))

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/chapters/release/<int:chapter_id>/<task_type>', methods=['POST'])
def release_chapter(chapter_id, task_type):
    user_id = session.get('user_id')
    user_roles = session.get('roles', '').split(',')

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
        chapter = cursor.fetchone()

        if not chapter: return jsonify({'error': 'Bulunamadı'}), 400

        if task_type == 'CLEANING':
            if chapter['cleaner_id'] != user_id and 'Controller' not in user_roles: return jsonify({'error': 'Yetkisiz'}), 403
            cursor.execute('UPDATE chapters SET cleaner_id = NULL WHERE id = ?', (chapter_id,))
        elif task_type == 'PROOFREADING':
            if chapter['proofreader_id'] != user_id and 'Controller' not in user_roles: return jsonify({'error': 'Yetkisiz'}), 403
            cursor.execute('UPDATE chapters SET proofreader_id = NULL WHERE id = ?', (chapter_id,))
        else:
            if chapter['assigned_to'] != user_id and 'Controller' not in user_roles: return jsonify({'error': 'Yetkisiz'}), 403
            cursor.execute('UPDATE chapters SET assigned_to = NULL WHERE id = ?', (chapter_id,))

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/chapters/upload/<int:chapter_id>/<task_type>', methods=['POST'])
def upload_files(chapter_id, task_type):
    user_id = session.get('user_id')
    user_roles = session.get('roles', '').split(',')
    uploaded_files = request.files.getlist('files')

    if not uploaded_files or uploaded_files[0].filename == '': return jsonify({'error': 'Dosya seçilmedi'}), 400

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
        chapter = cursor.fetchone()

        if task_type == 'CLEANING': assignee = chapter['cleaner_id']
        elif task_type == 'PROOFREADING': assignee = chapter['proofreader_id']
        else: assignee = chapter['assigned_to']

        if assignee != int(user_id) and 'Controller' not in user_roles:
            return jsonify({'error': 'Yetkisiz yükleme'}), 403

        stage = 'PENDING_' + task_type
        ch_dir = os.path.join(app.config['UPLOAD_FOLDER'], f'chapter_{chapter_id}', stage)
        os.makedirs(ch_dir, exist_ok=True)

        success_count = 0
        timestamp = int(time.time())  # DOSYA EZİLMELERİNİ ÖNLEYEN ZAMAN DAMGASI
        
        for file in uploaded_files:
            ext_ok = False
            if task_type in ['TRANSLATION', 'PROOFREADING']: ext_ok = allowed_file(file.filename, ALLOWED_EXTENSIONS_TXT)
            elif task_type in ['CLEANING', 'TYPESETTING']: ext_ok = allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG)
            if 'Controller' in user_roles: ext_ok = True

            if ext_ok:
                # İSİMLERİN BAŞINA TIMESTAMP EKLENDİ
                filename = f"{timestamp}_{secure_filename(file.filename)}"
                filepath = os.path.join(ch_dir, filename)
                file.save(filepath)
                cursor.execute('INSERT INTO files (chapter_id, stage, uploader_id, filename, filepath) VALUES (?, ?, ?, ?, ?)', (chapter_id, stage, user_id, filename, filepath))
                success_count += 1
                
        conn.commit()
        if success_count == 0: return jsonify({'error': 'Seçilen dosyaların formatı bu departman için uyumsuz.'}), 400
        return jsonify({'success': True, 'count': success_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/chapters/submit/<int:chapter_id>/<task_type>', methods=['POST'])
def submit_chapter(chapter_id, task_type):
    user_roles = session.get('roles', '').split(',')
    user_id = session.get('user_id')
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
        chapter = cursor.fetchone()

        folder_stage = 'PENDING_' + task_type

        if 'Controller' not in user_roles and task_type != 'PUBLISHING':
            cursor.execute('SELECT count(*) as c FROM files WHERE chapter_id = ? AND stage = ?', (chapter_id, folder_stage))
            if cursor.fetchone()['c'] == 0:
                return jsonify({'error': 'Bu aşamayı tamamlamak için dosya yüklemek zorunludur!'}), 400

        if task_type == 'TRANSLATION': credit_user = chapter['assigned_to'] or user_id
        elif task_type == 'CLEANING': credit_user = chapter['cleaner_id'] or user_id
        elif task_type == 'PROOFREADING': credit_user = chapter['proofreader_id'] or user_id
        else: credit_user = chapter['assigned_to'] or user_id

        if task_type != 'PUBLISHING':
            cursor.execute('INSERT INTO task_history (user_id, stage) VALUES (?, ?)', (credit_user, folder_stage))

        if chapter['status'] == 'PENDING_TRANSLATION' and task_type == 'TRANSLATION':
            cursor.execute('UPDATE chapters SET status = "PENDING_PARALLEL", assigned_to = NULL WHERE id = ?', (chapter_id,))
        elif chapter['status'] == 'PENDING_PARALLEL':
            if task_type == 'CLEANING':
                cursor.execute('UPDATE chapters SET is_cleaned = 1 WHERE id = ?', (chapter_id,))
            elif task_type == 'PROOFREADING':
                cursor.execute('UPDATE chapters SET is_proofread = 1 WHERE id = ?', (chapter_id,))

            cursor.execute('SELECT is_cleaned, is_proofread FROM chapters WHERE id = ?', (chapter_id,))
            updated_ch = cursor.fetchone()
            
            if updated_ch['is_cleaned'] and updated_ch['is_proofread']:
                cursor.execute('UPDATE chapters SET status = "PENDING_TYPESETTING", cleaner_id = NULL, proofreader_id = NULL WHERE id = ?', (chapter_id,))
                
        elif chapter['status'] == 'PENDING_TYPESETTING' and task_type == 'TYPESETTING':
            cursor.execute('UPDATE chapters SET status = "PENDING_PUBLISHING", assigned_to = NULL WHERE id = ?', (chapter_id,))
        elif chapter['status'] == 'PENDING_PUBLISHING' and task_type == 'PUBLISHING':
            cursor.execute('UPDATE chapters SET status = "PUBLISHED", assigned_to = NULL WHERE id = ?', (chapter_id,))

        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/chapters/download/<int:chapter_id>/<stage_filter>', methods=['GET'])
def download_zip(chapter_id, stage_filter):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT s.title, c.chapter_number FROM chapters c JOIN series s ON c.series_id = s.id WHERE c.id = ?', (chapter_id,))
        ch_info = cursor.fetchone()
        
        if not ch_info:
            return "Bölüm bulunamadı.", 404
            
        series_title = ch_info['title']
        chapter_number = ch_info['chapter_number']

        if stage_filter == 'ALL': 
            cursor.execute('SELECT filename, filepath FROM files WHERE chapter_id = ?', (chapter_id,))
        else: 
            cursor.execute('SELECT filename, filepath FROM files WHERE chapter_id = ? AND stage = ?', (chapter_id, stage_filter))
        
        files = cursor.fetchall()
        
        if not files: return "Dosya bulunamadı.", 404
        
        stage_names = {
            'PENDING_TRANSLATION': 'Redakte Bekliyor',
            'PENDING_CLEANING': 'Temiz Sayfalar Dizgi Bekliyor',
            'PENDING_PROOFREADING': 'Redakte Edilmiş Dizgi Bekliyor',
            'PENDING_TYPESETTING': 'Dizgili Sayfalar Yayınlanma Bekliyor',
            'PENDING_PUBLISHING': 'Yayınlanma Bekliyor',
            'ALL': 'Tüm Geçmiş'
        }
        stage_tr = stage_names.get(stage_filter, stage_filter)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", series_title)
        zip_filename = f"{safe_title}_Bölüm {chapter_number}_{stage_tr}.zip"

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if os.path.exists(f['filepath']): zf.write(f['filepath'], f['filename'])
        memory_file.seek(0)
        
        return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name=zip_filename)
    except Exception as e:
        print("Download Hatası:", e)
        return "İndirme Hatası", 500
    finally:
        conn.close()

@app.route('/api/admin/series/<int:series_id>', methods=['DELETE'])
def delete_series_api(series_id):
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz erişim'}), 403
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM chapters WHERE series_id = ?', (series_id,))
        chapters = cursor.fetchall()
        
        for ch in chapters:
            folder_path = os.path.join(app.config['UPLOAD_FOLDER'], f'chapter_{ch["id"]}')
            try: 
                shutil.rmtree(folder_path)
            except Exception as e: 
                print(f"Klasör silinemedi ({folder_path}): {e}") # SESSİZ HATA GİDERİLDİ
                
        cursor.execute('DELETE FROM files WHERE chapter_id IN (SELECT id FROM chapters WHERE series_id = ?)', (series_id,))
        cursor.execute('DELETE FROM chapters WHERE series_id = ?', (series_id,))
        cursor.execute('DELETE FROM series WHERE id = ?', (series_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/chapters/<int:chapter_id>', methods=['DELETE'])
def delete_chapter_api(chapter_id):
    if 'Controller' not in session.get('roles', ''): return jsonify({'error': 'Yetkisiz erişim'}), 403
    conn = get_db()
    try:
        cursor = conn.cursor()
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], f'chapter_{chapter_id}')
        try: 
            shutil.rmtree(folder_path)
        except Exception as e: 
            print(f"Klasör silinemedi ({folder_path}): {e}") # SESSİZ HATA GİDERİLDİ
            
        cursor.execute('DELETE FROM files WHERE chapter_id = ?', (chapter_id,))
        cursor.execute('DELETE FROM chapters WHERE id = ?', (chapter_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)