from app import app, socketio

if __name__ == '__main__':
    # Run the Flask app on your local IP (192.168.1.9)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
