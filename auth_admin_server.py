#!/usr/bin/env python3
"""
AI泳道图 - 认证与管理后台服务
端口: 6010 (可通过命令行参数或 ADMIN_PORT 环境变量修改)

提供:
  POST /api/auth/send-code    邮箱验证码发送
  POST /api/auth/verify       验证码登录/注册
  POST /api/auth/logout       退出登录
  GET  /api/auth/me           当前用户信息
  POST /api/track/pv          PV 埋点上报
  POST /api/admin/login       管理员登录
  GET  /api/admin/stats       PV/UV 统计
  GET  /api/admin/users       用户列表
  GET  /api/admin/channels    渠道统计
  GET  /admin                 管理后台界面
"""
import os, json, sys, random, string, uuid, re, smtplib, threading, hashlib, mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_OK = True
except ImportError:
    PSYCOPG2_OK = False
    print("[ERROR] psycopg2 未安装，请运行: pip install psycopg2-binary")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# 日志
# ============================================================
LOG_FILE = os.getenv('ADMIN_LOG_FILE', str(Path(__file__).parent / 'admin.log'))

def _log(level, msg):
    line = f"[{level}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

log_debug = lambda m: _log('DEBUG', m)
log_error = lambda m: _log('ERROR', m)

# ============================================================
# 配置 (共用 config.json，追加 database / smtp / auth 字段)
# ============================================================
CONFIG_FILE = os.getenv(
    'SWIMLANE_CONFIG_FILE',
    str(Path(__file__).parent / 'config.json')
)

RUNTIME_CONFIG = {
    'database': {
        'host': os.getenv('DB_HOST', 'pgm-bp13t0m174dhu72ato.pg.rds.aliyuncs.com'),
        'port': int(os.getenv('DB_PORT', '5432')),
        'dbname': os.getenv('DB_NAME', 'postgres'),
        'user': os.getenv('DB_USER', 'shangbian'),
        'password': os.getenv('DB_PASSWORD', 'Sbzy888*'),
    },
    'smtp': {
        'host': os.getenv('SMTP_HOST', ''),
        'port': int(os.getenv('SMTP_PORT', '465')),
        'use_ssl': os.getenv('SMTP_SSL', 'true').lower() == 'true',
        'username': os.getenv('SMTP_USER', ''),
        'password': os.getenv('SMTP_PASS', ''),
        'from_email': os.getenv('SMTP_FROM', ''),
        'from_name': 'AI泳道图',
    },
    'auth': {
        'admin_token': os.getenv('ADMIN_TOKEN', 'swimlane-admin-2024'),
        'channel': 'AI泳道图',
        'code_ttl_minutes': 10,
        'session_days': 30,
    }
}


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for section in ('database', 'smtp', 'auth'):
                if section in cfg and isinstance(cfg[section], dict):
                    RUNTIME_CONFIG[section].update(cfg[section])
    except Exception as e:
        log_error(f"加载配置失败: {e}")


def save_config_section(section):
    try:
        existing = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing[section] = RUNTIME_CONFIG[section]
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_error(f"保存配置失败: {e}")
        return False


load_config()

# ============================================================
# 数据库（线程本地连接）
# ============================================================
_thread_local = threading.local()

INIT_SQL_STMTS = [
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        nickname VARCHAR(100),
        channel VARCHAR(100) NOT NULL DEFAULT 'AI泳道图',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_login_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS verification_codes (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        code VARCHAR(10) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        used BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS user_sessions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token VARCHAR(255) UNIQUE NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ip_address VARCHAR(64),
        user_agent TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS page_views (
        id SERIAL PRIMARY KEY,
        page_path VARCHAR(500) NOT NULL DEFAULT '/',
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        session_id VARCHAR(128) NOT NULL,
        ip_address VARCHAR(64),
        user_agent TEXT,
        channel VARCHAR(100) NOT NULL DEFAULT 'AI泳道图',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pv_created   ON page_views(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_pv_session   ON page_views(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_pv_channel   ON page_views(channel)",
    "CREATE INDEX IF NOT EXISTS idx_sess_token   ON user_sessions(token)",
    "CREATE INDEX IF NOT EXISTS idx_vc_email_exp ON verification_codes(email, expires_at)",
]


def _connect_db():
    cfg = RUNTIME_CONFIG['database']
    return psycopg2.connect(
        host=cfg['host'], port=cfg['port'], dbname=cfg['dbname'],
        user=cfg['user'], password=cfg['password'], connect_timeout=10,
        options="-c client_encoding=utf8"
    )


def get_db():
    """返回当前线程的数据库连接（自动重连）"""
    if not PSYCOPG2_OK:
        raise RuntimeError("psycopg2 未安装，请: pip install psycopg2-binary")
    conn = getattr(_thread_local, 'conn', None)
    if conn is None or conn.closed:
        _thread_local.conn = _connect_db()
        return _thread_local.conn
    try:
        conn.cursor().execute("SELECT 1")
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        _thread_local.conn = _connect_db()
    return _thread_local.conn


def db_query(sql, params=None, fetch='all'):
    conn = get_db()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        conn.commit()
        if fetch == 'one':
            return cur.fetchone()
        return cur.fetchall()


def db_execute(sql, params=None):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    try:
        conn = get_db()
        with conn.cursor() as cur:
            for stmt in INIT_SQL_STMTS:
                cur.execute(stmt)
        conn.commit()
        log_debug("数据库表初始化完成")
    except Exception as e:
        log_error(f"数据库初始化失败: {e}")
        try:
            get_db().rollback()
        except Exception:
            pass

# ============================================================
# 邮件发送
# ============================================================
def send_email_async(to_email, subject, html_body):
    """在后台线程发送邮件，不阻塞请求"""
    threading.Thread(
        target=_send_email,
        args=(to_email, subject, html_body),
        daemon=True
    ).start()


def _send_email(to_email, subject, html_body):
    smtp_cfg = RUNTIME_CONFIG['smtp']
    host = smtp_cfg.get('host', '').strip()
    if not host:
        log_debug(f"[邮件·未配置SMTP] To:{to_email} | {subject}")
        return True

    msg = MIMEMultipart('alternative')
    from_addr = smtp_cfg.get('from_email') or smtp_cfg.get('username', '')
    msg['Subject'] = subject
    msg['From'] = f"{smtp_cfg.get('from_name', 'AI泳道图')} <{from_addr}>"
    msg['To'] = to_email
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    try:
        port = smtp_cfg.get('port', 465)
        if smtp_cfg.get('use_ssl', True):
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.ehlo()
            server.starttls()
        server.login(smtp_cfg.get('username', ''), smtp_cfg.get('password', ''))
        server.sendmail(from_addr, to_email, msg.as_string())
        server.quit()
        log_debug(f"邮件发送成功: {to_email}")
        return True
    except Exception as e:
        log_error(f"邮件发送失败({to_email}): {e}")
        return False


def _build_code_email(code, ttl_minutes, channel):
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:40px 0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.1);">
    <div style="background:linear-gradient(135deg,#7C5CFF 0%,#5B8DEF 100%);padding:32px;text-align:center;">
      <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">{channel}</h1>
      <p style="color:rgba(255,255,255,.8);margin:8px 0 0;font-size:14px;">邮箱验证码</p>
    </div>
    <div style="padding:32px 40px;">
      <p style="color:#555;font-size:15px;margin:0 0 20px;">您好，感谢使用 {channel}！</p>
      <p style="color:#333;font-size:15px;margin:0 0 20px;">您的登录验证码为：</p>
      <div style="background:#f0ecff;border-radius:12px;padding:22px;text-align:center;margin:0 0 24px;">
        <span style="font-size:40px;font-weight:700;color:#7C5CFF;letter-spacing:10px;">{code}</span>
      </div>
      <p style="color:#999;font-size:13px;margin:0;line-height:1.7;">
        验证码 <strong style="color:#333;">{ttl_minutes} 分钟</strong>内有效，请勿泄露给他人。<br>
        如非本人操作，请忽略此邮件。
      </p>
    </div>
    <div style="background:#f9f9f9;padding:16px 40px;text-align:center;border-top:1px solid #eee;">
      <p style="color:#bbb;font-size:12px;margin:0;">© {channel} · 熵变智元</p>
    </div>
  </div>
</body>
</html>"""

# ============================================================
# 工具函数
# ============================================================
def generate_code(length=6):
    return ''.join(random.choices(string.digits, k=length))


def generate_token():
    return hashlib.sha256(os.urandom(48)).hexdigest() + uuid.uuid4().hex


def is_valid_email(email):
    return bool(re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email))


def get_client_ip(handler):
    fwd = handler.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return handler.client_address[0]


def get_session_user(handler):
    """从请求头提取并校验 session，返回用户字典或 None"""
    auth = handler.headers.get('Authorization', '')
    token = auth[7:].strip() if auth.startswith('Bearer ') else ''
    token = token or handler.headers.get('X-Session-Token', '').strip()
    if not token:
        return None
    try:
        row = db_query(
            """SELECT s.user_id, s.expires_at, u.email, u.nickname, u.channel
               FROM user_sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.token = %s""",
            (token,), fetch='one'
        )
        if not row:
            return None
        if row['expires_at'] < datetime.now(timezone.utc):
            return None
        return dict(row)
    except Exception as e:
        log_error(f"Session 校验失败: {e}")
        return None


def check_admin(handler):
    auth = handler.headers.get('Authorization', '')
    token = auth[7:].strip() if auth.startswith('Bearer ') else ''
    token = token or handler.headers.get('X-Admin-Token', '').strip()
    return token == RUNTIME_CONFIG['auth'].get('admin_token', '')

# ============================================================
# HTTP 请求处理器
# ============================================================
class AuthAdminHandler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE')
        self.send_header('Access-Control-Allow-Headers',
                         'Content-Type, Authorization, X-Session-Token, X-Admin-Token')
        self.send_header('Access-Control-Max-Age', '3600')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length > 0 else b''
            return json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            return None

    # ------ GET ------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Admin UI
        if path in ('/admin', '/admin/', '/admin/index.html'):
            self._serve_static('admin.html', 'text/html; charset=utf-8')
            return

        routes = {
            '/api/auth/me':         self._h_auth_me,
            '/api/admin/stats':     self._h_admin_stats,
            '/api/admin/users':     self._h_admin_users,
            '/api/admin/channels':  self._h_admin_channels,
            '/api/health':          self._h_health,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json(404, {'error': 'Not Found'})

    # ------ POST ------
    def do_POST(self):
        path = urlparse(self.path).path
        routes = {
            '/api/auth/send-code':  self._h_send_code,
            '/api/auth/verify':     self._h_verify_code,
            '/api/auth/logout':     self._h_logout,
            '/api/track/pv':        self._h_track_pv,
            '/api/admin/login':     self._h_admin_login,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json(404, {'error': 'Not Found'})

    # ------ Static ------
    def _serve_static(self, filename, content_type=None):
        base = Path(__file__).parent
        fp = (base / filename).resolve()
        if not str(fp).startswith(str(base)) or not fp.is_file():
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        ct = content_type or mimetypes.guess_type(str(fp))[0] or 'application/octet-stream'
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    # ------ Health ------
    def _h_health(self):
        self._json(200, {'status': 'ok', 'service': 'auth-admin'})

    # ------ Auth: send code ------
    def _h_send_code(self):
        data = self._read_body()
        if data is None:
            return self._json(400, {'success': False, 'error': '无效请求'})
        email = (data.get('email') or '').strip().lower()
        if not email or not is_valid_email(email):
            return self._json(400, {'success': False, 'error': '邮箱格式不正确'})

        try:
            # 60 秒内同邮箱限发一次
            recent = db_query(
                "SELECT id FROM verification_codes WHERE email=%s "
                "AND created_at > NOW() - INTERVAL '60 seconds' LIMIT 1",
                (email,), fetch='one'
            )
            if recent:
                return self._json(429, {'success': False, 'error': '发送太频繁，请等待 60 秒后重试'})

            code = generate_code()
            ttl = RUNTIME_CONFIG['auth'].get('code_ttl_minutes', 10)
            channel = RUNTIME_CONFIG['auth'].get('channel', 'AI泳道图')

            db_execute(
                "INSERT INTO verification_codes(email, code, expires_at) "
                "VALUES(%s, %s, NOW() + INTERVAL '1 minute' * %s)",
                (email, code, ttl)
            )
            log_debug(f"验证码 [{email}] → {code}")

            subject = f"【{channel}】您的验证码是 {code}"
            send_email_async(email, subject, _build_code_email(code, ttl, channel))

            return self._json(200, {'success': True, 'message': f'验证码已发送至 {email}，请在 {ttl} 分钟内使用'})
        except Exception as e:
            log_error(f"send-code 异常: {e}")
            return self._json(500, {'success': False, 'error': '服务器错误，请稍后重试'})

    # ------ Auth: verify code ------
    def _h_verify_code(self):
        data = self._read_body()
        if data is None:
            return self._json(400, {'success': False, 'error': '无效请求'})
        email   = (data.get('email') or '').strip().lower()
        code    = (data.get('code') or '').strip()
        channel = (data.get('channel') or RUNTIME_CONFIG['auth'].get('channel', 'AI泳道图')).strip()

        if not email or not code:
            return self._json(400, {'success': False, 'error': '请填写邮箱和验证码'})

        try:
            row = db_query(
                """SELECT id FROM verification_codes
                   WHERE email=%s AND code=%s AND used=FALSE AND expires_at > NOW()
                   ORDER BY created_at DESC LIMIT 1""",
                (email, code), fetch='one'
            )
            if not row:
                return self._json(400, {'success': False, 'error': '验证码错误或已过期'})

            # 标记验证码已使用
            db_execute('UPDATE verification_codes SET used=TRUE WHERE id=%s', (row['id'],))

            # 新建或更新用户
            user = db_query(
                """INSERT INTO users(email, channel)
                   VALUES(%s, %s)
                   ON CONFLICT(email) DO UPDATE SET last_login_at=NOW()
                   RETURNING id, email, nickname, channel, created_at""",
                (email, channel), fetch='one'
            )

            # 创建 session
            token = generate_token()
            session_days = RUNTIME_CONFIG['auth'].get('session_days', 30)
            ip = get_client_ip(self)
            ua = self.headers.get('User-Agent', '')[:500]
            db_execute(
                """INSERT INTO user_sessions(user_id, token, expires_at, ip_address, user_agent)
                   VALUES(%s, %s, NOW() + INTERVAL '1 day' * %s, %s, %s)""",
                (user['id'], token, session_days, ip, ua)
            )

            nickname = user.get('nickname') or email.split('@')[0]
            return self._json(200, {
                'success': True,
                'token': token,
                'user': {
                    'id':         user['id'],
                    'email':      user['email'],
                    'nickname':   nickname,
                    'channel':    user['channel'],
                    'created_at': str(user['created_at']),
                }
            })
        except Exception as e:
            log_error(f"verify-code 异常: {e}")
            return self._json(500, {'success': False, 'error': '服务器错误'})

    # ------ Auth: logout ------
    def _h_logout(self):
        auth = self.headers.get('Authorization', '')
        token = auth[7:].strip() if auth.startswith('Bearer ') else ''
        token = token or self.headers.get('X-Session-Token', '').strip()
        if token:
            try:
                db_execute('DELETE FROM user_sessions WHERE token=%s', (token,))
            except Exception:
                pass
        return self._json(200, {'success': True})

    # ------ Auth: me ------
    def _h_auth_me(self):
        user = get_session_user(self)
        if not user:
            return self._json(401, {'success': False, 'error': '未登录'})
        return self._json(200, {
            'success': True,
            'user': {
                'id':       user['user_id'],
                'email':    user['email'],
                'nickname': user.get('nickname') or user['email'].split('@')[0],
                'channel':  user['channel'],
            }
        })

    # ------ PV tracking ------
    def _h_track_pv(self):
        data = self._read_body()
        if data is None:
            return self._json(400, {'success': False})
        session_id = (data.get('session_id') or '').strip()[:128]
        page_path  = (data.get('page_path') or '/').strip()[:500]
        channel    = (data.get('channel') or RUNTIME_CONFIG['auth'].get('channel', 'AI泳道图')).strip()[:100]

        if not session_id:
            return self._json(400, {'success': False, 'error': '缺少 session_id'})

        try:
            user = get_session_user(self)
            user_id = user['user_id'] if user else None
            ip = get_client_ip(self)
            ua = self.headers.get('User-Agent', '')[:500]
            db_execute(
                """INSERT INTO page_views(page_path, user_id, session_id, ip_address, user_agent, channel)
                   VALUES(%s, %s, %s, %s, %s, %s)""",
                (page_path, user_id, session_id, ip, ua, channel)
            )
            return self._json(200, {'success': True})
        except Exception as e:
            log_error(f"track-pv 异常: {e}")
            return self._json(500, {'success': False})

    # ------ Admin: login ------
    def _h_admin_login(self):
        data = self._read_body()
        if data is None:
            return self._json(400, {'success': False, 'error': '无效请求'})
        token = (data.get('token') or '').strip()
        admin_token = RUNTIME_CONFIG['auth'].get('admin_token', '')
        if token and token == admin_token:
            return self._json(200, {'success': True, 'admin_token': token})
        return self._json(401, {'success': False, 'error': '管理员令牌错误'})

    # ------ Admin: stats ------
    def _h_admin_stats(self):
        if not check_admin(self):
            return self._json(401, {'success': False, 'error': '无权访问'})
        try:
            qs   = parse_qs(urlparse(self.path).query)
            days = min(int((qs.get('days') or ['30'])[0]), 365)

            totals = db_query(
                """SELECT COUNT(*) AS total_pv,
                          COUNT(DISTINCT session_id) AS total_uv,
                          (SELECT COUNT(*) FROM users) AS total_users
                   FROM page_views""",
                fetch='one'
            )
            today = db_query(
                """SELECT COUNT(*) AS pv, COUNT(DISTINCT session_id) AS uv
                   FROM page_views
                   WHERE created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Asia/Shanghai')
                         AT TIME ZONE 'Asia/Shanghai'""",
                fetch='one'
            )
            daily = db_query(
                """SELECT DATE(created_at AT TIME ZONE 'Asia/Shanghai') AS day,
                          COUNT(*) AS pv,
                          COUNT(DISTINCT session_id) AS uv
                   FROM page_views
                   WHERE created_at > NOW() - INTERVAL '1 day' * %s
                   GROUP BY day ORDER BY day""",
                (days,), fetch='all'
            )
            return self._json(200, {
                'success': True,
                'totals': dict(totals) if totals else {},
                'today':  dict(today)  if today  else {},
                'daily':  [dict(r) for r in (daily or [])],
            })
        except Exception as e:
            log_error(f"admin-stats 异常: {e}")
            return self._json(500, {'success': False, 'error': str(e)})

    # ------ Admin: users ------
    def _h_admin_users(self):
        if not check_admin(self):
            return self._json(401, {'success': False, 'error': '无权访问'})
        try:
            qs     = parse_qs(urlparse(self.path).query)
            page   = max(int((qs.get('page')  or ['1'])[0]), 1)
            limit  = min(int((qs.get('limit') or ['20'])[0]), 100)
            offset = (page - 1) * limit

            total = db_query('SELECT COUNT(*) AS cnt FROM users', fetch='one')
            users = db_query(
                """SELECT id, email, nickname, channel, created_at, last_login_at
                   FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (limit, offset), fetch='all'
            )
            return self._json(200, {
                'success': True,
                'total':  total['cnt'] if total else 0,
                'page':   page,
                'limit':  limit,
                'users':  [dict(u) for u in (users or [])],
            })
        except Exception as e:
            log_error(f"admin-users 异常: {e}")
            return self._json(500, {'success': False, 'error': str(e)})

    # ------ Admin: channel stats ------
    def _h_admin_channels(self):
        if not check_admin(self):
            return self._json(401, {'success': False, 'error': '无权访问'})
        try:
            data = db_query(
                """SELECT channel,
                          COUNT(*) AS pv,
                          COUNT(DISTINCT session_id) AS uv,
                          COUNT(DISTINCT user_id) AS logged_in_uv
                   FROM page_views
                   GROUP BY channel ORDER BY pv DESC""",
                fetch='all'
            )
            return self._json(200, {'success': True, 'data': [dict(r) for r in (data or [])]})
        except Exception as e:
            log_error(f"admin-channels 异常: {e}")
            return self._json(500, {'success': False, 'error': str(e)})

    def log_message(self, fmt, *args):
        msg = f"[{self.address_string()}] {fmt % args}"
        print(msg)
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')
        except Exception:
            pass


# ============================================================
# 启动入口
# ============================================================
def run_server(port=6010):
    log_debug(f"认证/管理后台服务正在启动 → 端口 {port}")
    log_debug(f"数据库: {RUNTIME_CONFIG['database']['host']}:{RUNTIME_CONFIG['database']['port']}")

    init_db()

    server = ThreadingHTTPServer(('', port), AuthAdminHandler)
    admin_token = RUNTIME_CONFIG['auth'].get('admin_token', '')
    print("=" * 60)
    print("AI泳道图 · 认证/管理后台服务")
    print("=" * 60)
    print(f"服务地址: http://0.0.0.0:{port}")
    print(f"管理后台: http://0.0.0.0:{port}/admin")
    print(f"管理员令牌: {admin_token}")
    print(f"按 Ctrl+C 停止")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭...")
        server.shutdown()


if __name__ == '__main__':
    port = int(os.getenv('ADMIN_PORT', sys.argv[1] if len(sys.argv) > 1 else '6010'))
    run_server(port)
