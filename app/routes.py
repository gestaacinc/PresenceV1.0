import os
import time
import qrcode
import hashlib
import base64
from datetime import datetime 
 
from flask_socketio import SocketIO, emit
from werkzeug.security import check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from flask import render_template, request, jsonify, send_file,redirect, url_for, flash
from app import app, get_db_connection, socketio,User
from flask_socketio import SocketIO, emit
import csv


@app.route('/')
def landing_page():
    return render_template('index.html')

# Route for login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM administrators WHERE username = %s', (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            user_obj = User(user['id'], user['username'], user['password'])
            login_user(user_obj)  # This logs in the user and sets up the session
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid credentials. Please try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

# Route for logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

 
# Function to generate a session token based on the current date and time
def generate_session_token():
    session_data = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return hashlib.sha256(session_data.encode()).hexdigest()

# Function to generate the QR code for the class session
@app.route('/generate_class_qr')
def generate_class_qr():
    # Generate a new session token
    session_token = generate_session_token()

    # Full URL containing the session token
    attendance_url = f"http://192.168.1.9:5000/attendance?token={session_token}"

    # Path to save the QR code - create an absolute path to avoid Flask issues
    base_dir = os.path.abspath(os.path.dirname(__file__))  # Get absolute path of the current file
    qr_code_directory = os.path.join(base_dir, 'static', 'qr_codes')
    qr_code_path = os.path.join(qr_code_directory, 'class_session_qr.png')

    # Ensure the directory exists
    if not os.path.exists(qr_code_directory):
        os.makedirs(qr_code_directory, exist_ok=True)

    # Generate the QR code with the full URL
    img = qrcode.make(attendance_url)
    img.save(qr_code_path)

    # Store the session token in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO session_tokens (token) VALUES (%s)', (session_token,))
    conn.commit()
    conn.close()

    # Path to the QR code for rendering in the template
    qr_code_url = url_for('static', filename='qr_codes/class_session_qr.png')

    # Render the HTML page and pass the QR code URL to the template
    return render_template('qr_code.html', qr_code_url=qr_code_url)


# Attendance page (student access after scanning the QR code)
@app.route('/attendance')
def attendance():
    session_token = request.args.get('token')

    # Verify if the session token matches the one in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT token FROM session_tokens ORDER BY created_at DESC LIMIT 1')
    stored_token = cursor.fetchone()
    conn.close()

    if stored_token and session_token == stored_token[0]:
        return render_template('attendance.html')  # Display the attendance form
    else:
        return "Invalid session token", 403

# Test route to access attendance page without a token (for development use only)
@app.route('/attendance/test')
def attendance_test():
    return render_template('attendance.html')  # Display the attendance form without token validation

# Fetch student names for autocomplete
@app.route('/students_autocomplete')
def students_autocomplete():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch both active and inactive students if required, otherwise just active ones
    cursor.execute('SELECT student_name FROM students WHERE status = %s', ('active',))
    students = cursor.fetchall()
    conn.close()

    # Extract student names, convert to lower case for case-insensitive comparison
    student_names = [student['student_name'] for student in students]
    return jsonify(student_names)


@app.route('/log_attendance', methods=['POST'])
def log_attendance():
    data = request.get_json()
    student_name = data['name']
    student_image = data['image']
    filename = data['filename']
    session_token = data.get('token')  # Retrieve the session token from the request

    conn = get_db_connection()
    cursor = conn.cursor()

    # Validate the session token by checking the latest token in the database
    cursor.execute('SELECT token FROM session_tokens ORDER BY created_at DESC LIMIT 1')
    stored_token = cursor.fetchone()

    if not stored_token or session_token != stored_token[0]:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': 'Invalid session token.'
        }), 403

    # Check if the student exists and is active
    cursor.execute('SELECT student_id FROM students WHERE student_name LIKE %s AND status = %s', (f'%{student_name}%', 'active'))
    student = cursor.fetchone()

    if student:
        student_id = student[0]

        # Check if the student has already logged attendance today
        cursor.execute('''
            SELECT timestamp FROM attendance 
            WHERE student_id = %s AND DATE(timestamp) = CURDATE()''', (student_id,))
        existing_log = cursor.fetchone()

        if existing_log:
            log_time = existing_log[0].strftime("%Y-%m-%d %H:%M:%S")
            conn.close()
            return jsonify({
                'status': 'already_logged',
                'message': f'You have already logged in today at {log_time}.'
            }), 200

        # Directory where the images will be saved
        current_date = datetime.now().strftime("%Y-%m-%d")
        image_directory = os.path.join('app', 'static', 'images', current_date)

        if not os.path.exists(image_directory):
            os.makedirs(image_directory)

        # Save the student's picture
        image_data = base64.b64decode(student_image.split(',')[1])
        image_path = os.path.join(image_directory, filename)
        with open(image_path, 'wb') as f:
            f.write(image_data)

        # Log attendance in the database (without student_name)
        cursor.execute('INSERT INTO attendance (student_id, attendance_status) VALUES (%s, %s)', (student_id, 'present'))
        conn.commit()
        
        # Get the ID of the newly inserted attendance record
        attendance_id = cursor.lastrowid

        # Insert image path into the images table, associated with the attendance_id
        cursor.execute('INSERT INTO images (attendance_id, image_path) VALUES (%s, %s)', (attendance_id, f'/static/images/{current_date}/{filename}'))
        conn.commit()

        # Get the timestamp of the attendance log
        cursor.execute('SELECT timestamp FROM attendance WHERE id = %s', (attendance_id,))
        log_time = cursor.fetchone()[0].strftime("%Y-%m-%d %H:%M:%S")

        conn.close()

        # Emit the real-time event for the teacher's page
        socketio.emit('new_attendance', {
            'id': attendance_id,  # Ensure `id` is included in the emitted data
            'student_id': student_id,
            'student_name': student_name,
            'timestamp': log_time,
            'status': 'present',
            'image_path': f'/static/images/{current_date}/{filename}?t={str(time.time())}'  # Use `image_path` for consistency
        })

        return jsonify({
            'status': 'success',
            'message': 'Attendance logged successfully!',
            'log_time': log_time
        }), 200
    else:
        conn.close()
        return jsonify({
            'status': 'error',
            'message': 'Student not found or inactive.'
        }), 404

@app.route('/fetch_attendance_data')
def fetch_attendance_data():
    try:
        selected_date = request.args.get('date')
        formatted_date = datetime.strptime(selected_date, "%d/%m/%Y").date()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to fetch attendance records with images and student details for the selected date
        cursor.execute('''
            SELECT 
                a.id,  
                s.student_name, 
                a.timestamp, 
                i.image_path, 
                a.attendance_status
            FROM attendance a
            JOIN students s ON a.student_id = s.student_id
            LEFT JOIN images i ON a.id = i.attendance_id
            WHERE DATE(a.timestamp) = %s
            ORDER BY a.timestamp DESC
        ''', (formatted_date,))
        
        attendance_data = cursor.fetchall()
        conn.close()

        # Ensure you return JSON data
        return jsonify(attendance_data)
    except Exception as e:
        # Log the error and return an error response
        print(f"Error in fetch_attendance_data: {e}")
        return jsonify({"error": "Internal server error"}), 500

# success page
@app.route('/success')
def success():
    student_name = request.args.get('student_name')
    log_time = request.args.get('log_time')
    return render_template('success.html', student_name=student_name, log_time=log_time)

# student page
@app.route('/students')
def manage_students():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch all students from the database
    cursor.execute('SELECT student_id, student_name, status FROM students')
    students = cursor.fetchall()

    conn.close()

    # Render the students.html template with the students data
    return render_template('students.html', students=students)


@app.route('/update_status/<id>', methods=['POST'])
def update_student_status(id):
    data = request.get_json()
    new_status = data.get('status')

    # Debugging Logs
    print(f"Received id: {id}")
    print(f"Received status: {new_status}")

    if not new_status:
        return jsonify({"status": "error", "message": "Status not provided"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        print(f"Executing SQL query for id {id}")  # Debugging
        cursor.execute(
            'UPDATE attendance SET attendance_status = %s WHERE id = %s',
            (new_status, id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        # Emit real-time update to all connected clients
        print(f"Emitting status_updated for id {id} with status {new_status}")
        socketio.emit('status_updated', {'id': id, 'new_status': new_status})

        return jsonify({"status": "success", "message": "Status updated successfully"}), 200
    except Exception as e:
        print(f"Error updating status: {e}")
        return jsonify({"status": "error", "message": "Database error"}), 500


@app.route('/teacher_dashboard')
@login_required
def teacher_dashboard():
    selected_date = request.args.get('date', None)

    if selected_date:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch attendance records for the selected date, including student_id
        cursor.execute('''
            SELECT student_id, student_name, timestamp, attendance_status, image_path
            FROM attendance
            WHERE DATE(timestamp) = %s
        ''', (selected_date,))

        attendance_records = cursor.fetchall()
        conn.close()

        # Format the data into JSON with proper image paths
        attendance_data = [
            {
                "student_id": record['student_id'],  # Include student_id
                "student_name": record['student_name'].replace('_', ' '),
                "timestamp": record['timestamp'].strftime("%B %d, %Y %I:%M:%S %p") if record['timestamp'] else "N/A",
                "status": record['attendance_status'],
                "image": record['image_path']
            }
            for record in attendance_records
        ]

        return jsonify(attendance_data)

    return render_template('teacher_dashboard.html', current_user=current_user)




@app.route('/update_attendance_status', methods=['POST'])
def update_attendance_status():
    data = request.get_json()
    student_name = data['student_name']
    attendance_status = data['attendance_status']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Update the status in the database
    cursor.execute('''
        UPDATE attendance
        SET attendance_status = %s
        WHERE student_name = %s AND DATE(timestamp) = CURDATE()
    ''', (attendance_status, student_name))

    conn.commit()
    conn.close()

    return jsonify({'status': 'success', 'message': 'Attendance status updated successfully.'})




@app.route('/attendance_by_date')
def attendance_by_date():
    selected_date = request.args.get('date')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch attendance records for the selected date
    cursor.execute('''
        SELECT a.student_name, a.timestamp, a.attendance_status AS status,
        CONCAT('/static/images/', DATE(a.timestamp), '/', s.student_id, '_attendance.png') AS image
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE DATE(a.timestamp) = %s
    ''', (selected_date,))

    attendance_records = cursor.fetchall()
    conn.close()

    return jsonify(attendance_records)


@app.route('/add_student', methods=['POST'])
def add_student():
    try:
        data = request.get_json()
        student_name = data.get('student_name')
        status = data.get('status')

        # Ensure all required fields are provided
        if not student_name or not status:
            return jsonify({'status': 'error', 'message': 'All fields are required.'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if a student with the same name already exists
        cursor.execute('SELECT * FROM students WHERE student_name = %s', (student_name,))
        existing_student = cursor.fetchone()
        if existing_student:
            return jsonify({'status': 'error', 'message': f'Student "{student_name}" already exists.'}), 409

        # Generate student_id
        initials = student_name[:2].upper()
        current_month = datetime.now().strftime("%m")

        # Find the next sequential number for the current month
        cursor.execute(
            'SELECT COUNT(*) FROM students WHERE student_id LIKE %s', 
            (f"{initials}{current_month}%",)
        )
        count = cursor.fetchone()[0] + 1  # Increment to get the next sequence

        # Format the ID as per "CH1101" example
        student_id = f"{initials}{current_month}{str(count).zfill(2)}"

        # Insert new student record
        cursor.execute(
            'INSERT INTO students (student_id, student_name, status) VALUES (%s, %s, %s)',
            (student_id, student_name, status)
        )
        
        conn.commit()
        print("Student added successfully:", student_id, student_name, status)

        return jsonify({'status': 'success', 'message': 'Student added successfully.', 'student_id': student_id}), 200
    except Exception as e:
        print(f"Error adding student: {e}")
        return jsonify({'status': 'error', 'message': f'Database error: {str(e)}'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


 

# Bulk upload route
@app.route('/bulk_upload', methods=['POST'])
def bulk_upload_students():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No selected file'}), 400

    if file and file.filename.endswith('.csv'):
        try:
            # Parse CSV and add students to the database
            conn = get_db_connection()
            cursor = conn.cursor()

            csv_data = file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(csv_data)

            for row in reader:
                student_name = row.get('student_name')
                if not student_name:
                    continue  # Skip if there's no student_name in the row

                status = 'active'  # Set default status to 'active'

                # Generate student ID
                initials = student_name[:2].upper()
                current_month = datetime.now().strftime("%m")

                cursor.execute('SELECT COUNT(*) FROM students WHERE student_id LIKE %s', (f"{initials}{current_month}%",))
                count = cursor.fetchone()[0] + 1  # Increment to get the next sequence
                student_id = f"{initials}{current_month}{str(count).zfill(2)}"

                # Insert student record into the database
                cursor.execute(
                    'INSERT INTO students (student_id, student_name, status) VALUES (%s, %s, %s)',
                    (student_id, student_name, status)
                )

            conn.commit()
            cursor.close()
            conn.close()

            # Return success JSON response
            return jsonify({'status': 'success', 'message': 'Students uploaded successfully!'}), 200

        except Exception as e:
            print(f"Error uploading students: {e}")
            return jsonify({'status': 'error', 'message': f'Error processing file: {str(e)}'}), 500

    return jsonify({'status': 'error', 'message': 'Invalid file type'}), 400


# bulk delete

# Route for deleting a single student
@app.route('/delete_student/<student_id>', methods=['POST'])
def delete_student(student_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM students WHERE student_id = %s", (student_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Student deleted successfully"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Route for bulk deleting students
@app.route('/bulk_delete_students', methods=['POST'])
def bulk_delete_students():
    data = request.get_json()
    student_ids = data.get('student_ids', [])

    if not student_ids:
        return jsonify({"status": "error", "message": "No students selected"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        format_strings = ','.join(['%s'] * len(student_ids))
        cursor.execute(f"DELETE FROM students WHERE student_id IN ({format_strings})", tuple(student_ids))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Students deleted successfully"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    

@app.route('/delete_attendance/<int:attendance_id>', methods=['DELETE'])
def delete_attendance(attendance_id):
    try:
        print(f"Received attendance_id to delete: {attendance_id}")  # Debugging line

        # Connect to the database
        conn = get_db_connection()
        cursor = conn.cursor()

        # First, fetch the image path from the images table to delete the file from the filesystem
        cursor.execute("SELECT image_path FROM images WHERE attendance_id = %s", (attendance_id,))
        image_record = cursor.fetchone()

        if image_record:
            image_path = os.path.join('app', image_record[0])  # Adjust path if needed
            print(f"Image path to delete: {image_path}")  # Debugging line
            if os.path.exists(image_path):
                os.remove(image_path)
                print("Image file deleted from filesystem")  # Debugging line

        # Delete the image record from the images table
        cursor.execute("DELETE FROM images WHERE attendance_id = %s", (attendance_id,))

        # Delete the attendance record from the attendance table
        cursor.execute("DELETE FROM attendance WHERE id = %s", (attendance_id,))
        
        # Check if the attendance record was found and deleted
        if cursor.rowcount == 0:
            print("No rows deleted. Check if attendance_id exists in the database.")  # Debugging line
            conn.close()
            return jsonify({'status': 'error', 'message': 'Attendance record not found.'}), 404

        # Commit the transaction
        conn.commit()
        print("Record deleted successfully")  # Debugging line

        # Close the database connection
        conn.close()

        # Emit a real-time event to notify clients of deletion
        socketio.emit('attendance_deleted', {'attendance_id': attendance_id})

        return jsonify({'status': 'success', 'message': 'Attendance record deleted successfully.'}), 200

    except Exception as e:
        print("Error during deletion:", e)  # Debugging line
        return jsonify({'status': 'error', 'message': 'An error occurred during deletion.'}), 500
