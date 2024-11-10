from flask import Flask
from flask_socketio import SocketIO
import mysql.connector
from flask_login import LoginManager, UserMixin  # Remove 'User' from this line

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Initialize SocketIO for real-time updates
socketio = SocketIO(app)

# Database configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'attendance_db'

# Create a connection to MySQL using mysql.connector
def get_db_connection():
    conn = mysql.connector.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB']
    )
    return conn

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Custom User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM administrators WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        return User(user['id'], user['username'], user['password'])
    return None

# Import routes after initializing the app
from app import routes
